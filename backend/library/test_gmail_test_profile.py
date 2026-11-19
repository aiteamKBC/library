"""Separate AI Team grants: no n8n identity assertion or application activation."""
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from .gmail_credential_store import (CredentialStoreError, TEST_PROFILE, default_vault_path,
    load_credentials, save_credentials, settings_from_vault)
from .gmail_oauth import OAuthError, OAuthSession, confirmation_page, confirm_discovered_account
from .test_gmail_oauth import CLIENT, GRANT


TEST_ACCOUNT = "ai-team@example.test"


class GmailTestProfileTests(SimpleTestCase):
    def test_extended_session_preserves_one_use_state_and_bounded_expiry(self):
        session = OAuthSession(CLIENT, profile=TEST_PROFILE, timeout_seconds=1800)
        target = f"/oauth2/callback?state={session.state}&code=synthetic-only"
        with patch("library.gmail_oauth.time.monotonic", return_value=session.started + 601):
            self.assertFalse(session.expired())
            self.assertEqual(session.callback_code(target, "127.0.0.1:8765"), "synthetic-only")
            with self.assertRaises(OAuthError):
                session.callback_code(target, "127.0.0.1:8765")
        with patch("library.gmail_oauth.time.monotonic", return_value=session.started + 1800):
            self.assertTrue(session.expired())
            with self.assertRaises(OAuthError):
                self.grant(session)

    def test_default_lifetime_and_invalid_unbounded_sessions_remain_rejected(self):
        session = self.session()
        with patch("library.gmail_oauth.time.monotonic", return_value=session.started + 600):
            self.assertTrue(session.expired())
        for timeout in (0, 59, 3601, True, "1800"):
            with self.subTest(timeout=timeout), self.assertRaises(OAuthError):
                OAuthSession(CLIENT, profile=TEST_PROFILE, timeout_seconds=timeout)

    def session(self, expected_account=None):
        return OAuthSession(CLIENT, expected_account, profile=TEST_PROFILE)

    def grant(self, session=None):
        session = session or self.session()
        return confirm_discovered_account(session, {**GRANT, "account_email": TEST_ACCOUNT},
            {"state":[session.confirm_state], "confirm_test_account":["yes"]},
            host="127.0.0.1:8765", origin="http://127.0.0.1:8765")

    def test_test_ui_does_not_request_a_false_n8n_or_old_from_assertion(self):
        page = confirmation_page(self.session(), {**GRANT, "account_email": TEST_ACCOUNT})
        self.assertIn("TEST SENDER ONLY", page)
        self.assertIn('name="confirm_test_account"', page)
        self.assertNotIn("Charly Account", page)
        self.assertNotIn('name="same_n8n_account"', page)
        self.assertNotIn('name="same_n8n_sender"', page)

    def test_test_account_becomes_only_the_test_sender_after_explicit_confirmation(self):
        grant = self.grant()
        self.assertEqual(grant["account_email"], TEST_ACCOUNT)
        self.assertEqual(grant["sender"], TEST_ACCOUNT)
        self.assertEqual(grant["credential_usage"], "test_only")
        self.assertEqual(grant["profile_name"], TEST_PROFILE)
        self.assertFalse(grant["n8n_identity_confirmed"])
        self.assertFalse(grant["production_sender_approved"])

    def test_test_confirmation_still_requires_matching_state_origin_and_owner_acknowledgement(self):
        session = self.session()
        good = {"state":[session.confirm_state], "confirm_test_account":["yes"]}
        for form, origin in (({"state":[session.confirm_state]}, "http://127.0.0.1:8765"),
                             ({**good,"state":["wrong"]}, "http://127.0.0.1:8765"),
                             (good, "null"), (good, "https://foreign.example.test"),
                             ({**good,"same_n8n_account":["yes"]}, "http://127.0.0.1:8765")):
            with self.subTest(origin=origin), self.assertRaises(OAuthError):
                confirm_discovered_account(session, GRANT, form, host="127.0.0.1:8765", origin=origin)

    def test_legacy_confirmation_stays_unchanged_and_does_not_accept_test_checkbox(self):
        session = OAuthSession(CLIENT)
        page = confirmation_page(session, GRANT)
        self.assertIn("Charly Account", page)
        with self.assertRaises(OAuthError):
            confirm_discovered_account(session, GRANT,
                {"state":[session.confirm_state], "confirm_test_account":["yes"]},
                host="127.0.0.1:8765", origin="http://127.0.0.1:8765")

    def test_google_scopes_redirect_and_account_selection_are_unchanged(self):
        params = parse_qs(urlsplit(self.session().authorization_url()).query)
        self.assertNotIn("login_hint", params)
        self.assertEqual(params["redirect_uri"], ["http://127.0.0.1:8765/oauth2/callback"])
        self.assertEqual(set(params["scope"][0].split()), {"openid","email","https://www.googleapis.com/auth/gmail.send"})
        self.assertEqual(params["access_type"], ["offline"])

    def test_cli_test_mode_does_not_inherit_library_account_sender_or_reply_to(self):
        import connect_gmail_oauth
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-test-profile-") as directory:
            root = Path(directory)
            env_file = root / "synthetic.env"
            env_file.write_text(f'Client ID={CLIENT["client_id"]}\nClient secret={CLIENT["client_secret"]}\n'
                'LIBRARY_GMAIL_ACCOUNT_EMAIL=old-library@example.test\nLIBRARY_GMAIL_SENDER=old-from@example.test\n'
                'LIBRARY_GMAIL_REPLY_TO=old-replies@example.test\n')
            vault = root / "test.dpapi"
            sessions = []
            def fake_authorize(session, *args, **kwargs):
                sessions.append(session)
                return TEST_ACCOUNT
            output = StringIO()
            with patch.dict("os.environ", {}, clear=True), \
                    patch("connect_gmail_oauth.default_vault_path", return_value=vault) as vault_path, \
                    patch("connect_gmail_oauth.authorize", side_effect=fake_authorize), \
                    patch("connect_gmail_oauth.load_credentials", return_value=self.grant()), redirect_stdout(output):
                result = connect_gmail_oauth.main(["--authorize","--profile",TEST_PROFILE,"--env-file",str(env_file)])
            self.assertEqual(result, 0)
            vault_path.assert_called_once_with(TEST_PROFILE)
            self.assertEqual(len(sessions), 1)
            self.assertIsNone(sessions[0].expected_account)
            self.assertEqual((sessions[0].sender, sessions[0].reply_to), ("", ""))
            self.assertNotIn(CLIENT["client_secret"], output.getvalue())
            self.assertIn('"credential_usage": "test_only"', output.getvalue())

    def test_cli_never_overwrites_an_existing_test_grant(self):
        import connect_gmail_oauth
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-test-profile-") as directory:
            path = Path(directory) / "existing.dpapi"
            path.write_bytes(b"synthetic-existing-preserved")
            config = {"client_id":CLIENT["client_id"], "client_secret":CLIENT["client_secret"],
                      "redirect_uri":"", "account_email":"", "sender":"", "reply_to":""}
            with patch("connect_gmail_oauth.default_vault_path",return_value=path), \
                    patch("connect_gmail_oauth.resolve_google_config",return_value=(config,{})), \
                    patch("connect_gmail_oauth.authorize") as authorize_mock, redirect_stderr(StringIO()):
                self.assertEqual(connect_gmail_oauth.main(["--authorize","--profile",TEST_PROFILE]),2)
            self.assertEqual(path.read_bytes(), b"synthetic-existing-preserved")
            authorize_mock.assert_not_called()

    @skipUnless(os.name == "nt", "Windows DPAPI.")
    def test_separate_encrypted_test_vault_preserves_library_grant_and_cannot_configure_application(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-profile-vaults-") as directory:
            with patch.dict("os.environ", {"LOCALAPPDATA":directory}):
                original = default_vault_path()
                test_vault = default_vault_path(TEST_PROFILE)
                self.assertNotEqual(original, test_vault)
                save_credentials(original, GRANT)
                original_bytes = original.read_bytes()
                test_grant = self.grant()
                save_credentials(test_vault, test_grant)
                self.assertEqual(load_credentials(test_vault), test_grant)
                self.assertEqual(original.read_bytes(), original_bytes)
                self.assertNotIn(test_grant["refresh_token"].encode(), test_vault.read_bytes())
                with self.assertRaises(CredentialStoreError):
                    settings_from_vault(test_vault)
                self.assertEqual(settings_from_vault(original)["LIBRARY_GMAIL_CLIENT_ID"], CLIENT["client_id"])
