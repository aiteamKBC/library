"""Gmail protocol, selection and worker regressions. All identities are synthetic."""
import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from unittest.mock import patch
from urllib.parse import parse_qs

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from . import test_email_system as fixtures
from .email_models import EmailOutbox
from .email_policy import EVENTS, require_live_delivery, require_live_gmail, routes_to_django
from .email_providers import create_email_client
from .email_transport import DeliveryResult, NoRedirect
from .email_worker import EmailWorker, retry_message
from .gmail_client import GmailClient, SEND_SCOPE, TOKEN_URL
from .graph_client import GraphClient


GMAIL = dict(LIBRARY_EMAIL_PROVIDER="gmail", LIBRARY_GMAIL_CLIENT_ID="synthetic-client",
             LIBRARY_GMAIL_CLIENT_SECRET="synthetic-client-secret", LIBRARY_GMAIL_REFRESH_TOKEN="synthetic-refresh-token",
             LIBRARY_GMAIL_ACCOUNT_EMAIL="google-account@example.test", LIBRARY_GMAIL_SENDER="library@example.test",
             LIBRARY_GMAIL_REPLY_TO="", LIBRARY_GMAIL_SENDER_NAME="KBC Library")
TOKEN = json.dumps({"access_token": "synthetic-access-token", "expires_in": 3600,
                    "token_type": "Bearer", "scope": SEND_SCOPE}).encode()


@override_settings(**GMAIL, LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("student@example.test",))
class GmailTransportTests(SimpleTestCase):
    def message(self, email="student@example.test"):
        return EmailOutbox(event_type="manual_email", recipient_email=email)

    def fake(self, *, status=200, raw=b'{"id":"synthetic-message-id"}', headers=None, auth_status=200, auth_raw=TOKEN):
        calls = []
        def transport(request):
            calls.append(request)
            if request.full_url == TOKEN_URL:
                return auth_status, headers or {}, auth_raw
            return status, headers or {}, raw
        return calls, transport

    def mime(self, request):
        raw = json.loads(request.data)["raw"]
        return BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))

    def test_refresh_protocol_html_utf8_identity_reply_to_and_cache(self):
        calls, transport = self.fake()
        client, message = GmailClient(transport), self.message()
        for _ in range(2):
            result = client.send(message, "Synthetic — مرحبًا", "<p>مرحبا &amp; HTML</p>")
            self.assertEqual(result.outcome, "accepted")
            self.assertEqual(result.request_id, "gmail:synthetic-message-id")
        self.assertEqual(len(calls), 3)
        oauth = parse_qs(calls[0].data.decode())
        self.assertEqual(oauth, {"grant_type": ["refresh_token"], "client_id": ["synthetic-client"],
                               "client_secret": ["synthetic-client-secret"], "refresh_token": ["synthetic-refresh-token"]})
        self.assertEqual(calls[-1].full_url, "https://gmail.googleapis.com/gmail/v1/users/google-account%40example.test/messages/send")
        self.assertEqual(calls[-1].get_header("Authorization"), "Bearer synthetic-access-token")
        mime = self.mime(calls[-1])
        self.assertEqual(mime["From"].addresses[0].addr_spec, "library@example.test")
        self.assertEqual(mime["From"].addresses[0].display_name, "KBC Library")
        self.assertEqual(mime["Reply-To"].addresses[0].addr_spec, "library@example.test")
        self.assertEqual(mime["To"].addresses[0].addr_spec, message.recipient_email)
        self.assertEqual(str(mime["Subject"]), "Synthetic — مرحبًا")
        self.assertEqual(mime.get_content_type(), "text/html")
        self.assertIn("مرحبا", mime.get_content())
        self.assertEqual(str(mime["Message-ID"]), f"<{message.id}@example.test>")
        self.assertIsNone(mime["Bcc"])
        self.assertNotIn("synthetic-refresh-token", calls[-1].data.decode())

    @override_settings(LIBRARY_GMAIL_REPLY_TO="approved-replies@example.test")
    def test_explicit_reply_to_does_not_change_recipient(self):
        calls, transport = self.fake()
        GmailClient(transport).send(self.message(), "Synthetic", "Body")
        mime = self.mime(calls[-1])
        self.assertEqual(mime["Reply-To"].addresses[0].addr_spec, "approved-replies@example.test")
        self.assertEqual(mime["To"].addresses[0].addr_spec, "student@example.test")

    def test_recipient_allowlist_blocks_before_authentication_even_with_cached_token(self):
        calls, transport = self.fake()
        client = GmailClient(transport)
        self.assertEqual(client.send(self.message("unauthorized@example.test"), "Synthetic", "Body").code, "recipient_not_allowlisted")
        self.assertEqual(calls, [])
        client.send(self.message(), "Synthetic", "Body")
        count = len(calls)
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            self.assertEqual(client.send(self.message(), "Synthetic", "Body").code, "recipient_not_allowlisted")
        self.assertEqual(len(calls), count)

    def test_bad_identity_or_subject_is_rejected_before_any_external_request(self):
        for name, value in (("LIBRARY_GMAIL_ACCOUNT_EMAIL", ""), ("LIBRARY_GMAIL_SENDER", ""),
                            ("LIBRARY_GMAIL_REPLY_TO", "bad"), ("LIBRARY_GMAIL_SENDER_NAME", "Bad\nBcc: other@example.test"),
                            ("LIBRARY_GMAIL_SENDER", "library@example.test\r\nBcc: bad@example.test")):
            with self.subTest(name=name), override_settings(**{name: value}):
                calls, transport = self.fake()
                with self.assertRaises(ValidationError):
                    GmailClient(transport).send(self.message(), "Synthetic", "Body")
                self.assertEqual(calls, [])
        calls, transport = self.fake()
        for subject in ("", "Bad\r\nBcc: bad@example.test"):
            with self.assertRaises(ValidationError):
                GmailClient(transport).send(self.message(), subject, "Body")
        self.assertEqual(calls, [])

    def test_cache_refreshes_before_expiry_and_after_expiry_without_persisting_tokens(self):
        calls, transport = self.fake()
        client = GmailClient(transport)
        with patch("library.gmail_client.time.monotonic", return_value=100):
            client.send(self.message(), "Synthetic", "Body")
        with patch("library.gmail_client.time.monotonic", return_value=3600):
            client.send(self.message(), "Synthetic", "Body")
        self.assertEqual(sum(r.full_url == TOKEN_URL for r in calls), 1)  # 100s remain.
        with patch("library.gmail_client.time.monotonic", return_value=3650):
            client.send(self.message(), "Synthetic", "Body")
        with patch("library.gmail_client.time.monotonic", return_value=8000):
            client.send(self.message(), "Synthetic", "Body")
        self.assertEqual(sum(r.full_url == TOKEN_URL for r in calls), 3)
        self.assertEqual(settings.LIBRARY_GMAIL_REFRESH_TOKEN, "synthetic-refresh-token")

    def test_concurrent_refresh_uses_one_token_request(self):
        calls, transport = self.fake()
        client = GmailClient(transport)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: client.send(self.message(), "Synthetic", "Body"), range(4)))
        self.assertEqual([r.outcome for r in results], ["accepted"] * 4)
        self.assertEqual(sum(r.full_url == TOKEN_URL for r in calls), 1)

    def test_unauthorized_invalidates_token_without_hidden_message_replay(self):
        calls, transport = self.fake(status=401, raw=b'{"error":{"code":401}}')
        client = GmailClient(transport)
        for _ in range(2):
            result = client.send(self.message(), "Synthetic", "Body")
            self.assertEqual(result.code, "gmail_token_rejected")
            self.assertEqual(result.outcome, "retryable_failure")
        self.assertEqual(len(calls), 4)  # Each recorded caller attempt: one refresh, one POST.
        self.assertIsNone(client._token)

    def test_revoked_refresh_token_needs_reauthorization_without_sending(self):
        calls, transport = self.fake(auth_status=400, auth_raw=b'{"error":"invalid_grant","error_description":"sensitive"}')
        result = GmailClient(transport).send(self.message(), "Synthetic", "Body")
        self.assertEqual((result.outcome, result.code), ("permanent_failure", "gmail_reauthorization_required"))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("sensitive", repr(result))

    def test_auth_transient_rejection_and_timeout_are_safe_retries_before_send(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                calls, transport = self.fake(auth_status=status, auth_raw=b'{"error":"temporarily_unavailable"}',
                                             headers={"Retry-After": "120"})
                result = GmailClient(transport).send(self.message(), "Synthetic", "Body")
                self.assertEqual(result.outcome, "retryable_failure")
                self.assertEqual(result.retry_after, 120)
                self.assertEqual(len(calls), 1)
        def timeout(request):
            raise TimeoutError("sensitive token details")
        result = GmailClient(timeout).send(self.message(), "Synthetic", "Body")
        self.assertEqual((result.outcome, result.code), ("retryable_failure", "gmail_auth_unavailable"))

    def test_bad_auth_client_or_incomplete_scopes_do_not_send(self):
        for status, raw, code in (
            (400, b'{"error":"invalid_client"}', "gmail_auth_rejected"),
            (200, json.dumps({"access_token":"synthetic", "expires_in":3600, "token_type":"Bearer", "scope":"openid email"}).encode(), "gmail_scope_missing"),
            (200, b'{"access_token":"synthetic","expires_in":0,"token_type":"Bearer"}', "gmail_auth_unavailable"),
            (200, b'not-json', "gmail_auth_unavailable"),
        ):
            with self.subTest(code=code):
                calls, transport = self.fake(auth_status=status, auth_raw=raw)
                self.assertEqual(GmailClient(transport).send(self.message(), "Synthetic", "Body").code, code)
                self.assertEqual(len(calls), 1)

    def test_rate_limits_and_structured_server_rejections_use_worker_backoff(self):
        cases = ((429, {}), (403, {"error":{"code":403,"errors":[{"reason":"userRateLimitExceeded"}]}}),
                 (500, {"error":{"code":500}}), (502, {"error":{"code":502}}), (503, {"error":{"code":503}}))
        for status, body in cases:
            with self.subTest(status=status):
                calls, transport = self.fake(status=status, raw=json.dumps(body).encode(), headers={"Retry-After":"90"})
                result = GmailClient(transport).send(self.message(), "Synthetic", "Body")
                self.assertEqual(result.outcome, "retryable_failure")
                self.assertEqual(result.retry_after, 90)
                self.assertEqual(len(calls), 2)

    def test_timeout_ambiguous_gateway_and_malformed_success_are_uncertain(self):
        for status, raw in ((408, b""), (504, b'{"error":{"code":504}}'), (503, b"gateway-page"),
                            (200, b'{}'), (200, b'not-json'), (200, b'{"id":"bad id"}'), (202, b""), (302, b"")):
            with self.subTest(status=status, raw=raw):
                calls, transport = self.fake(status=status, raw=raw)
                self.assertEqual(GmailClient(transport).send(self.message(), "Synthetic", "Body").outcome, "uncertain")
                self.assertEqual(len(calls), 2)
        def timeout(request):
            if request.full_url == TOKEN_URL:
                return 200, {}, TOKEN
            raise TimeoutError("sensitive request/recipient details")
        self.assertEqual(GmailClient(timeout).send(self.message(), "Synthetic", "Body").outcome, "uncertain")

    def test_permission_and_bad_request_errors_are_permanent_without_leaking_body(self):
        for status in (400, 403, 404):
            calls, transport = self.fake(status=status, raw=b'{"error":{"message":"sensitive","code":403}}')
            result = GmailClient(transport).send(self.message(), "Synthetic", "Body")
            self.assertEqual(result.outcome, "permanent_failure")
            self.assertNotIn("sensitive", repr(result))
            self.assertEqual(len(calls), 2)

    def test_redirects_are_never_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 307, "Temporary", {}, "https://other.example.test"))

    def test_live_flags_and_test_injection_guard_apply_before_io(self):
        with self.assertRaises(ImproperlyConfigured):
            GmailClient().send(self.message(), "Synthetic", "Body")
        with override_settings(LIBRARY_ISOLATED_TESTS=False):
            with self.assertRaises(ImproperlyConfigured):
                GmailClient(lambda request: None)
        calls, fake = self.fake()
        client = GmailClient(fake)
        with override_settings(LIBRARY_ISOLATED_TESTS=False), self.assertRaises(ImproperlyConfigured):
            client.send(self.message(), "Synthetic", "Body")
        self.assertEqual(calls, [])


class GmailConfigurationTests(SimpleTestCase):
    def test_gmail_is_default_but_every_live_gate_is_off_and_identity_is_empty(self):
        self.assertEqual(settings.LIBRARY_EMAIL_PROVIDER, "gmail")
        self.assertIsInstance(create_email_client(), GmailClient)
        for name in ("LIBRARY_GMAIL_SEND_ENABLED", "LIBRARY_GMAIL_CREDENTIALS_APPROVED", "LIBRARY_GRAPH_SEND_ENABLED",
                     "LIBRARY_EMAIL_ENQUEUE_ENABLED", "LIBRARY_EMAIL_WORKER_ENABLED", "LIBRARY_EMAIL_SCHEDULER_ENABLED"):
            self.assertFalse(getattr(settings, name))
        for name in ("LIBRARY_GMAIL_CLIENT_ID", "LIBRARY_GMAIL_CLIENT_SECRET", "LIBRARY_GMAIL_REFRESH_TOKEN",
                     "LIBRARY_GMAIL_ACCOUNT_EMAIL", "LIBRARY_GMAIL_SENDER", "LIBRARY_GMAIL_REPLY_TO"):
            self.assertEqual(getattr(settings, name), "")
        with self.assertRaises(ImproperlyConfigured):
            EmailWorker()

    def test_graph_requires_explicit_selection_unknown_values_never_fall_back(self):
        with override_settings(LIBRARY_EMAIL_PROVIDER="graph"):
            self.assertIsInstance(create_email_client(), GraphClient)
            with self.assertRaises(ImproperlyConfigured):
                require_live_gmail()
        for provider in ("", "other", "GMAIL"):
            with override_settings(LIBRARY_EMAIL_PROVIDER=provider), self.assertRaises(ImproperlyConfigured):
                create_email_client()

    @override_settings(**GMAIL, LIBRARY_EMAIL_ENQUEUE_ENABLED=True, LIBRARY_EMAIL_WORKER_ENABLED=True,
        LIBRARY_GMAIL_SEND_ENABLED=True, LIBRARY_GMAIL_CREDENTIALS_APPROVED=True,
        LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=True, LIBRARY_EMAIL_OWNED_EVENTS=tuple(EVENTS),
        LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("test-inbox@example.test",))
    def test_handoff_uses_gmail_gates_and_never_needs_graph_credentials(self):
        require_live_delivery()
        self.assertTrue(routes_to_django("loan_submitted"))
        self.assertFalse(routes_to_django("unknown"))
        for name, value in (("LIBRARY_GMAIL_SEND_ENABLED", False), ("LIBRARY_GMAIL_CREDENTIALS_APPROVED", False),
                            ("LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED", False), ("LIBRARY_EMAIL_WORKER_ENABLED", False),
                            ("LIBRARY_EMAIL_ENQUEUE_ENABLED", False), ("LIBRARY_EMAIL_RECIPIENT_ALLOWLIST", ()),
                            ("LIBRARY_GMAIL_REFRESH_TOKEN", ""), ("LIBRARY_GMAIL_CLIENT_SECRET", ""),
                            ("LIBRARY_GMAIL_CLIENT_ID", ""), ("LIBRARY_GMAIL_ACCOUNT_EMAIL", ""), ("LIBRARY_GMAIL_SENDER", "")):
            with self.subTest(setting=name), override_settings(**{name: value}):
                self.assertFalse(routes_to_django("loan_submitted"))
                with self.assertRaises(ImproperlyConfigured):
                    require_live_delivery()


@override_settings(**GMAIL)
class GmailWorkerTests(TestCase):
    setUp = fixtures.EmailSystemTests.setUp
    new_loan = fixtures.EmailSystemTests.new_loan
    one_message = fixtures.EmailSystemTests.one_message

    def gmail_client_fixture(self, *, status=200, raw=b'{"id":"synthetic-message-id"}'):
        calls = []
        def fake(request):
            calls.append(request)
            if request.full_url == TOKEN_URL:
                return 200, {}, TOKEN
            return status, {"Retry-After": "120"}, raw
        return GmailClient(fake), calls

    def test_existing_worker_selects_gmail_client_with_live_gates_checked(self):
        with override_settings(LIBRARY_GMAIL_SEND_ENABLED=True, LIBRARY_GMAIL_CREDENTIALS_APPROVED=True):
            worker = EmailWorker()
            self.assertIsInstance(worker.client, GmailClient)
            self.assertEqual(worker.provider, "gmail")

    def test_acceptance_records_one_attempt_no_repeat_and_no_tokens_in_storage(self):
        row = self.one_message()
        client, calls = self.gmail_client_fixture()
        worker = EmailWorker(client=client)
        self.assertEqual(worker.run_once(now=fixtures.NOW), ["accepted"])
        self.assertEqual(worker.run_once(now=fixtures.NOW + timedelta(days=1)), [])
        row.refresh_from_db()
        self.assertEqual(row.attempts_count, 1)
        self.assertEqual(row.payload["_email_provider"], "gmail")
        self.assertEqual(row.provider_request_id, "gmail:synthetic-message-id")
        self.assertEqual(row.attempts.get().result, "accepted")
        self.assertEqual(len(calls), 2)
        stored = json.dumps({"message": row.__dict__, "attempt": row.attempts.get().__dict__}, default=str)
        self.assertNotIn("synthetic-access-token", stored)
        self.assertNotIn("synthetic-refresh-token", stored)
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)

    def test_uncertain_is_not_retried_or_sent_via_graph(self):
        row = self.one_message()
        client, calls = self.gmail_client_fixture(status=504, raw=b"gateway-timeout")
        worker = EmailWorker(client=client)
        self.assertEqual(worker.run_once(now=fixtures.NOW), ["uncertain"])
        self.assertEqual(worker.run_once(now=fixtures.NOW + timedelta(days=1)), [])
        row.refresh_from_db()
        self.assertEqual(row.error_code, "gmail_submission_unknown")
        self.assertEqual(row.attempts.get().result, "uncertain")
        self.assertEqual(len(calls), 2)
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)

    def test_temporary_rejection_uses_existing_backoff_and_attempt_history(self):
        row = self.one_message()
        client, calls = self.gmail_client_fixture(status=503, raw=b'{"error":{"code":503,"message":"sensitive"}}')
        worker = EmailWorker(client=client)
        self.assertEqual(worker.run_once(now=fixtures.NOW), ["retry_wait"])
        row.refresh_from_db()
        self.assertGreaterEqual(row.available_at, fixtures.NOW + timedelta(seconds=120))
        self.assertEqual(row.error_code, "gmail_temporary_rejection")
        good_client, good_calls = self.gmail_client_fixture()
        self.assertEqual(EmailWorker(client=good_client).run_once(now=row.available_at), ["accepted"])
        self.assertEqual(list(row.attempts.order_by("attempt_number").values_list("result", flat=True)), ["retryable_failure", "accepted"])
        self.assertNotIn("sensitive", row.attempts.first().error_summary)

    def test_provider_change_between_attempts_is_blocked(self):
        row = self.one_message()
        client, calls = self.gmail_client_fixture(status=429, raw=b"quota")
        self.assertEqual(EmailWorker(client=client).run_once(now=fixtures.NOW), ["retry_wait"])
        row.refresh_from_db()
        # A different provider cannot replay a message even after a definite failure.
        fake_graph = fixtures.FakeGraph()
        fake_graph.provider = "graph"
        self.assertEqual(EmailWorker(client=fake_graph).run_once(now=row.available_at), ["blocked"])
        row.refresh_from_db()
        self.assertEqual(row.error_code, "delivery_provider_changed")
        self.assertEqual(row.attempts_count, 1)
        self.assertFalse(fake_graph.sent)

    def test_preexisting_graph_attempt_without_provider_metadata_is_not_replayed(self):
        row = self.one_message()
        fake_graph = fixtures.FakeGraph(DeliveryResult("retryable_failure", 429, "graph_temporary_rejection"))
        fake_graph.provider = "graph"
        self.assertEqual(EmailWorker(client=fake_graph).run_once(now=fixtures.NOW), ["retry_wait"])
        row.refresh_from_db()
        del row.payload["_email_provider"]  # Represents an actual pre-integration row.
        row.save(update_fields={"payload"})
        client, calls = self.gmail_client_fixture()
        self.assertEqual(EmailWorker(client=client).run_once(now=row.available_at), ["blocked"])
        self.assertEqual(calls, [])

    def test_allowlist_is_enforced_before_worker_creates_an_attempt(self):
        row = self.one_message()
        client, calls = self.gmail_client_fixture()
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            self.assertEqual(EmailWorker(client=client).run_once(now=fixtures.NOW), ["blocked"])
        self.assertEqual(calls, [])
        self.assertFalse(row.attempts.exists())
