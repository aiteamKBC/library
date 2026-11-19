"""Google-only dotenv compatibility and explicit account-confirmation regressions."""
from contextlib import redirect_stdout
from io import StringIO
import json
import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase

from .gmail_oauth import OAuthError, OAuthSession, confirm_discovered_account, json_request
from .gmail_oauth_config import GoogleConfigError, resolve_google_config
from .test_gmail_oauth import CLIENT, ACCOUNT, GRANT


class GoogleEnvLoadingTests(SimpleTestCase):
    def resolve(self, text, environment=None):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-google-env-") as directory:
            path = Path(directory) / "synthetic.env"
            path.write_text(text, encoding="utf-8-sig")
            original = path.read_bytes()
            value = resolve_google_config(env_path=path, environment=environment or {})
            self.assertEqual(path.read_bytes(), original)
            return value

    def test_existing_space_separated_labels_load_without_changing_values_or_file(self):
        value, sources = self.resolve(f"Client ID = {CLIENT['client_id']}\nClient secret = {CLIENT['client_secret']}\n")
        self.assertEqual(value["client_id"], CLIENT["client_id"])
        self.assertEqual(value["client_secret"], CLIENT["client_secret"])
        self.assertEqual(sources["client_id"], ["CLIENT ID"])
        self.assertEqual(sources["client_secret"], ["CLIENT SECRET"])

    def test_canonical_google_aliases_quotes_comments_export_and_bom(self):
        for prefix in ("LIBRARY_GMAIL", "GOOGLE", "GOOGLE_OAUTH"):
            with self.subTest(prefix=prefix):
                value, _ = self.resolve(f'export {prefix}_CLIENT_ID="{CLIENT["client_id"]}" # comment\n'
                                        f"{prefix}_CLIENT_SECRET='{CLIENT['client_secret']}'\n")
                self.assertEqual(value["client_secret"], CLIENT["client_secret"])

    def test_non_google_secrets_are_not_returned_or_used(self):
        value, sources = self.resolve("DATABASE_URL=never-return-this\nMICROSOFT_CLIENT_ID=not-google\nMICROSOFT_CLIENT_SECRET=never-return-this\n")
        self.assertEqual(value["client_id"], "")
        self.assertNotIn("never-return-this", json.dumps((value, sources)))

    def test_conflicting_file_process_or_duplicate_aliases_fail_closed(self):
        text = f"Client ID={CLIENT['client_id']}\nClient secret={CLIENT['client_secret']}\n"
        with self.assertRaises(GoogleConfigError):
            self.resolve(text, {"GOOGLE_CLIENT_SECRET": "different-secret"})
        with self.assertRaises(GoogleConfigError):
            self.resolve(text + "Client secret=different-secret\n")

    def test_partial_pair_invalid_id_and_quoting_do_not_echo_values(self):
        for text in ("Client ID=not-a-google-id\nClient secret=sensitive-value\n",
                     f"Client ID={CLIENT['client_id']}\n", 'GOOGLE_CLIENT_SECRET="sensitive-value\n'):
            with self.subTest(case=len(text)), self.assertRaises(GoogleConfigError) as caught:
                self.resolve(text)
            self.assertNotIn("sensitive-value", str(caught.exception))

    def test_process_aliases_are_supported_without_reading_an_env_file(self):
        value, _ = resolve_google_config(environment={"Client ID":CLIENT["client_id"], "Client secret":CLIENT["client_secret"]})
        self.assertEqual(value["client_id"], CLIENT["client_id"])

    def test_cli_check_reports_only_sources_and_never_prints_credentials(self):
        import connect_gmail_oauth
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-google-cli-") as directory:
            path = Path(directory) / "synthetic.env"
            path.write_text(f"Client ID={CLIENT['client_id']}\nClient secret={CLIENT['client_secret']}\n")
            output = StringIO()
            with patch.dict("os.environ", {}, clear=True), patch("connect_gmail_oauth.default_vault_path", return_value=Path(directory) / "missing.dpapi"), redirect_stdout(output):
                result = connect_gmail_oauth.main(["--check", "--env-file", str(path)])
            self.assertEqual(result, 0)
            self.assertTrue(json.loads(output.getvalue())["client_available_locally"])
            self.assertNotIn(CLIENT["client_secret"], output.getvalue())
            self.assertNotIn(CLIENT["client_id"], output.getvalue())

    def import_synthetic_settings(self, vault_client_id):
        source = Path(__file__).resolve().parents[1] / "config" / "settings.py"
        spec = importlib.util.spec_from_file_location("synthetic_google_settings", source)
        module = importlib.util.module_from_spec(spec)
        environment = {"Client ID":CLIENT["client_id"], "Client secret":CLIENT["client_secret"],
                       "LIBRARY_GMAIL_CREDENTIALS_FILE":"synthetic-vault-not-read"}
        values = {"LIBRARY_GMAIL_CLIENT_ID":vault_client_id, "LIBRARY_GMAIL_CLIENT_SECRET":CLIENT["client_secret"]}
        # Import only pure settings with no app/DB setup. The real .env and vault
        # are blocked/mocked before import, including on this settings-only path.
        with patch.dict("os.environ", environment, clear=True), patch("pathlib.Path.exists", return_value=False), \
                patch("library.gmail_credential_store.settings_from_vault", return_value=values):
            spec.loader.exec_module(module)
        return module

    def test_django_settings_load_existing_aliases_and_matching_vault_without_enabling_flags(self):
        module = self.import_synthetic_settings(CLIENT["client_id"])
        self.assertEqual(module.LIBRARY_GMAIL_CLIENT_ID, CLIENT["client_id"])
        self.assertEqual(module.LIBRARY_GMAIL_CLIENT_SECRET, CLIENT["client_secret"])
        self.assertFalse(module.LIBRARY_GMAIL_SEND_ENABLED)
        self.assertFalse(module.LIBRARY_EMAIL_WORKER_ENABLED)
        self.assertFalse(module.LIBRARY_EMAIL_SCHEDULER_ENABLED)

    def test_vault_cannot_silently_override_a_different_google_alias_pair(self):
        with self.assertRaises(ValueError) as caught:
            self.import_synthetic_settings("different.apps.googleusercontent.com")
        self.assertNotIn(CLIENT["client_secret"], str(caught.exception))


class GoogleAccountDiscoveryTests(SimpleTestCase):
    def test_null_origin_is_still_rejected_rather_than_bypassing_csrf_checks(self):
        session = OAuthSession(CLIENT)
        with self.assertRaisesRegex(OAuthError, "google_account_confirmation_origin_invalid"):
            confirm_discovered_account(session, GRANT,
                {"state":[session.confirm_state], "same_n8n_account":["yes"]},
                host="127.0.0.1:8765", origin="null")

    def test_expired_confirmation_is_reported_before_any_refresh_or_storage(self):
        session = OAuthSession(CLIENT)
        with patch("library.gmail_oauth.time.monotonic", return_value=session.started + 600):
            with self.assertRaisesRegex(OAuthError, "google_account_confirmation_session_expired"):
                confirm_discovered_account(session, GRANT,
                    {"state":[session.confirm_state], "same_n8n_account":["yes"]},
                    host="127.0.0.1:8765", origin="http://127.0.0.1:8765")

    def test_missing_first_checkbox_never_confirms_identity(self):
        session = OAuthSession(CLIENT)
        with self.assertRaisesRegex(OAuthError, "discovered_google_account_confirmation_required"):
            confirm_discovered_account(session, GRANT,
                {"state":[session.confirm_state]}, host="127.0.0.1:8765", origin="http://127.0.0.1:8765")

    def test_discovery_requests_account_selection_without_inventing_login_hint(self):
        session = OAuthSession(CLIENT)
        params = parse_qs(urlsplit(session.authorization_url()).query)
        self.assertNotIn("login_hint", params)
        self.assertIn("select_account", params["prompt"][0])

    def test_verified_account_confirmation_does_not_assume_sender(self):
        session = OAuthSession(CLIENT)
        confirmed = confirm_discovered_account(session, GRANT,
            {"state":[session.confirm_state], "same_n8n_account":["yes"]},
            host="127.0.0.1:8765", origin="http://127.0.0.1:8765")
        self.assertTrue(confirmed["n8n_identity_confirmed"])
        self.assertEqual(confirmed["sender"], "")
        self.assertNotIn("n8n_identity_confirmed", GRANT)

    def test_sender_is_used_only_on_explicit_matching_original_sender_confirmation(self):
        session = OAuthSession(CLIENT)
        confirmed = confirm_discovered_account(session, GRANT,
            {"state":[session.confirm_state], "same_n8n_account":["yes"], "same_n8n_sender":["yes"]},
            host="127.0.0.1:8765", origin="http://127.0.0.1:8765")
        self.assertEqual(confirmed["sender"], ACCOUNT)

    def test_foreign_origin_missing_confirmation_bad_nonce_or_conflicting_sender_fails(self):
        session = OAuthSession(CLIENT)
        good = {"state":[session.confirm_state], "same_n8n_account":["yes"]}
        for form, host, origin in ((good, "evil.example.test", "http://127.0.0.1:8765"),
                                  (good, "127.0.0.1:8765", "https://evil.example.test"),
                                  ({"state":[session.confirm_state]}, "127.0.0.1:8765", "http://127.0.0.1:8765"),
                                  ({**good, "state":["wrong"]}, "127.0.0.1:8765", "http://127.0.0.1:8765")):
            with self.subTest(origin=origin), self.assertRaises(OAuthError):
                confirm_discovered_account(session, GRANT, form, host=host, origin=origin)
        with self.assertRaises(OAuthError):
            confirm_discovered_account(session, {**GRANT, "sender":"old-alias@example.test"}, {**good, "same_n8n_sender":["yes"]},
                                       host="127.0.0.1:8765", origin="http://127.0.0.1:8765")

    def test_google_error_diagnostics_are_allowlisted_without_error_description(self):
        from urllib.request import Request
        def rejected(request):
            return 400, {}, b'{"error":"invalid_client","error_description":"sensitive-value"}'
        with self.assertRaises(OAuthError) as caught:
            json_request(Request("https://oauth2.googleapis.com/token"), rejected)
        self.assertEqual(str(caught.exception), "google_oauth_invalid_client")
