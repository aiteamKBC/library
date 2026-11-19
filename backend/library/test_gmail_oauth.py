"""No real Google traffic, credentials or app/database initialization."""
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from .gmail_credential_store import (CredentialStoreError, checked_path, load_credentials,
    save_credentials, settings_from_vault)
from .gmail_oauth import (AUTH_URL, TOKEN_URL, USERINFO_URL, REDIRECT_URI, SEND_SCOPE,
    OAuthError, OAuthSession, load_client, verify_identity)
from .gmail_client import GmailClient


CLIENT = {"client_id": "synthetic.apps.googleusercontent.com", "client_secret": "synthetic-client-secret"}
ACCOUNT = "same-n8n-account@example.test"
GRANT = {**CLIENT, "refresh_token": "synthetic-new-django-refresh-token", "account_email": ACCOUNT,
         "account_sub": "synthetic-google-sub", "sender": "", "reply_to": "", "sender_name": "",
         "scopes": ["openid", "email", SEND_SCOPE]}


class GmailOAuthTests(SimpleTestCase):
    def session(self):
        return OAuthSession(CLIENT, ACCOUNT)

    def callback(self, session, **extra):
        return "/oauth2/callback?" + urlencode({"state": session.state, "code": "synthetic-code", **extra})

    def token_transport(self, *, email=ACCOUNT, verified=True, sub="synthetic-google-sub", scopes=None, refresh=True):
        calls = []
        def fake(request):
            calls.append(request)
            if request.full_url == TOKEN_URL:
                value = {"access_token": "synthetic-access", "token_type": "Bearer", "expires_in": 3600,
                         "scope": scopes if scopes is not None else "openid email " + SEND_SCOPE}
                if refresh:
                    value["refresh_token"] = GRANT["refresh_token"]
            elif request.full_url == USERINFO_URL:
                value = {"email": email, "email_verified": verified, "sub": sub}
            else:
                self.fail("Unexpected OAuth endpoint; Gmail send is forbidden.")
            return 200, {}, json.dumps(value).encode()
        return calls, fake

    def test_authorization_requests_only_send_identity_offline_pkce_and_random_state(self):
        session = self.session()
        params = parse_qs(urlsplit(session.authorization_url()).query)
        self.assertTrue(session.authorization_url().startswith(AUTH_URL + "?"))
        self.assertEqual(set(params["scope"][0].split()), {"openid", "email", SEND_SCOPE})
        self.assertEqual(params["access_type"], ["offline"])
        self.assertEqual(params["redirect_uri"], [REDIRECT_URI])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        challenge = base64.urlsafe_b64encode(hashlib.sha256(session.verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(params["code_challenge"], [challenge])
        self.assertNotIn(session.verifier, session.authorization_url())
        self.assertNotIn(CLIENT["client_secret"], session.authorization_url())
        self.assertNotEqual(session.state, self.session().state)

    def test_valid_callback_consumes_state_once(self):
        session = self.session()
        self.assertEqual(session.callback_code(self.callback(session), "127.0.0.1:8765"), "synthetic-code")
        with self.assertRaises(OAuthError):
            session.callback_code(self.callback(session), "127.0.0.1:8765")

    def test_wrong_state_host_path_or_duplicate_state_is_rejected(self):
        session = self.session()
        cases = ((self.callback(session, state="wrong"), "127.0.0.1:8765"),
                 (self.callback(session), "evil.example.test"),
                 (self.callback(session).replace("/oauth2/callback", "/other"), "127.0.0.1:8765"),
                 (self.callback(session) + "&state=duplicate", "127.0.0.1:8765"),
                 ("https://evil.example.test" + self.callback(session), "127.0.0.1:8765"))
        for target, host in cases:
            with self.subTest(target=target), self.assertRaises(OAuthError):
                session.callback_code(target, host)
        self.assertFalse(session.used)

    def test_expiry_denial_and_duplicate_code_are_rejected(self):
        session = self.session()
        with patch("library.gmail_oauth.time.monotonic", return_value=session.started + 600), self.assertRaises(OAuthError):
            session.callback_code(self.callback(session), "127.0.0.1:8765")
        for extra in ("&error=access_denied", "&code=duplicate"):
            session = self.session()
            with self.assertRaises(OAuthError):
                session.callback_code(self.callback(session) + extra, "127.0.0.1:8765")

    def test_no_token_exchange_without_callback_validation(self):
        calls, fake = self.token_transport()
        with self.assertRaises(OAuthError):
            self.session().exchange_and_verify("synthetic-code", transport=fake)
        self.assertEqual(calls, [])

    def test_exchange_verifies_google_identity_and_never_persists_access_or_id_token(self):
        session = self.session()
        code = session.callback_code(self.callback(session), "127.0.0.1:8765")
        calls, fake = self.token_transport()
        grant = session.exchange_and_verify(code, transport=fake)
        self.assertEqual(grant["account_email"], ACCOUNT)
        self.assertEqual(grant["account_sub"], GRANT["account_sub"])
        self.assertEqual(grant["sender"], "")  # Identity does not guess old From/alias.
        self.assertNotIn("access_token", grant)
        self.assertNotIn("id_token", grant)
        self.assertEqual(len(calls), 2)
        params = parse_qs(calls[0].data.decode())
        self.assertEqual(params["redirect_uri"], [REDIRECT_URI])
        self.assertEqual(params["code_verifier"], [session.verifier])
        self.assertEqual(calls[1].get_header("Authorization"), "Bearer synthetic-access")

    def test_wrong_account_unverified_email_or_changed_google_sub_fail_closed(self):
        for options in ({"email":"other@example.test"}, {"verified":False}, {"sub":"different"}):
            calls, fake = self.token_transport(**options)
            with self.assertRaises(OAuthError):
                verify_identity("synthetic-access", expected_account=ACCOUNT, expected_sub=GRANT["account_sub"], transport=fake)
            self.assertEqual(len(calls), 1)

    def test_missing_offline_grant_or_send_scope_does_not_verify_or_save(self):
        for options in ({"refresh":False}, {"scopes":"openid email"}):
            session = self.session()
            session.callback_code(self.callback(session), "127.0.0.1:8765")
            calls, fake = self.token_transport(**options)
            with self.assertRaises(OAuthError):
                session.exchange_and_verify("synthetic-code", transport=fake)
            self.assertEqual(len(calls), 1)

    def test_network_errors_never_include_codes_or_secrets(self):
        def broken(request):
            raise OSError("synthetic-client-secret sensitive-callback-code")
        with self.assertRaises(OAuthError) as caught:
            verify_identity("synthetic-access", expected_account=ACCOUNT, transport=broken)
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("sensitive", str(caught.exception))

    def test_client_import_requires_google_endpoints_and_exact_registered_redirect(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-oauth-") as directory:
            path = Path(directory) / "synthetic-client.json"
            document = {**CLIENT, "redirect_uris":[REDIRECT_URI], "auth_uri":AUTH_URL, "token_uri":TOKEN_URL}
            path.write_text(json.dumps({"web":document}))
            self.assertEqual(load_client(path), CLIENT)
            for changed in ({"redirect_uris":["https://other.example.test"]}, {"token_uri":"https://evil.example.test/token"},
                            {"auth_uri":"https://evil.example.test/auth"}, {"client_secret":""}):
                path.write_text(json.dumps({"web":{**document, **changed}}))
                with self.assertRaises(OAuthError):
                    load_client(path)

    @override_settings(LIBRARY_GMAIL_CLIENT_ID=CLIENT["client_id"], LIBRARY_GMAIL_CLIENT_SECRET=CLIENT["client_secret"],
                       LIBRARY_GMAIL_REFRESH_TOKEN=GRANT["refresh_token"])
    def test_existing_gmail_client_can_verify_refresh_while_sending_is_disabled(self):
        calls, fake = self.token_transport()
        client = GmailClient(fake)
        token, error = client._access_token()
        self.assertIsNone(error)
        self.assertEqual(verify_identity(token, expected_account=ACCOUNT, expected_sub=GRANT["account_sub"], transport=fake),
                         (ACCOUNT, GRANT["account_sub"]))
        self.assertEqual(len(calls), 2)
        self.assertFalse(settings.LIBRARY_GMAIL_SEND_ENABLED)
        self.assertFalse(settings.LIBRARY_EMAIL_WORKER_ENABLED)


@skipUnless(os.name == "nt", "Windows current-user DPAPI vault.")
class GmailVaultTests(SimpleTestCase):
    def test_dpapi_roundtrip_and_settings_mapping_do_not_enable_sending(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-vault-") as directory:
            path = Path(directory) / "synthetic.dpapi"
            save_credentials(path, GRANT)
            self.assertEqual(load_credentials(path), GRANT)
            raw = path.read_bytes()
            self.assertNotIn(GRANT["refresh_token"].encode(), raw)
            self.assertNotIn(CLIENT["client_secret"].encode(), raw)
            mapped = settings_from_vault(path)
            self.assertEqual(mapped["LIBRARY_GMAIL_ACCOUNT_EMAIL"], ACCOUNT)
            self.assertEqual(mapped["LIBRARY_GMAIL_SENDER"], "")
            self.assertFalse(any(key.endswith("ENABLED") or key.endswith("APPROVED") for key in mapped))
            with self.assertRaises(CredentialStoreError):
                save_credentials(path, GRANT)

    def test_access_tokens_or_git_paths_are_not_saved(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-vault-") as directory:
            with self.assertRaises(CredentialStoreError):
                save_credentials(Path(directory) / "synthetic.dpapi", {**GRANT, "access_token":"never-persist"})
        with self.assertRaises(CredentialStoreError):
            checked_path(Path(__file__).parent / "must-not-exist.dpapi")

    def test_corrupt_or_plaintext_vault_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-vault-") as directory:
            path = Path(directory) / "synthetic.dpapi"
            path.write_text(json.dumps(GRANT))
            with self.assertRaises(CredentialStoreError):
                load_credentials(path)
