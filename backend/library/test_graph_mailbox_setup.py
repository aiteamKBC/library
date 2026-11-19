import json
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import SimpleTestCase, override_settings

from .email_models import EmailOutbox
from .email_policy import graph_mailbox_target, require_live_graph
from .graph_client import GraphClient


@override_settings(LIBRARY_GRAPH_TENANT_ID="synthetic", LIBRARY_GRAPH_CLIENT_ID="synthetic",
    LIBRARY_GRAPH_CLIENT_SECRET="synthetic", LIBRARY_GRAPH_SENDER="sender@example.test",
    LIBRARY_GRAPH_MAILBOX_ID="", LIBRARY_GRAPH_REPLY_TO="",
    LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("test-inbox@example.test",))
class GraphMailboxSetupTests(SimpleTestCase):
    def message(self, address="test-inbox@example.test"):
        return EmailOutbox(event_type="manual_email", recipient_email=address)

    def transport(self):
        calls = []
        def fake(request):
            calls.append(request)
            if "/token" in request.full_url:
                return 200, {}, b'{"access_token":"synthetic-token","expires_in":3600}'
            return 202, {"request-id": "synthetic-request"}, b""
        return calls, fake

    def test_missing_reply_to_uses_the_configured_sender_without_changing_recipient(self):
        calls, fake = self.transport()
        result = GraphClient(fake).send(self.message(), "Synthetic test", "<p>Test</p>")
        self.assertEqual(result.outcome, "accepted")
        payload = json.loads(calls[-1].data)["message"]
        self.assertEqual(payload["replyTo"], [{"emailAddress": {"address": "sender@example.test"}}])
        self.assertEqual(payload["toRecipients"], [{"emailAddress": {"address": "test-inbox@example.test"}}])
        self.assertIn("/users/sender%40example.test/sendMail", calls[-1].full_url)

    def test_explicit_approved_reply_to_is_retained(self):
        calls, fake = self.transport()
        with override_settings(LIBRARY_GRAPH_REPLY_TO="approved-replies@example.test"):
            GraphClient(fake).send(self.message(), "Synthetic", "Body")
        self.assertEqual(json.loads(calls[-1].data)["message"]["replyTo"][0]["emailAddress"]["address"], "approved-replies@example.test")

    def test_explicit_mailbox_user_id_can_differ_from_the_smtp_address(self):
        calls, fake = self.transport()
        mailbox_id = "00000000-0000-0000-0000-000000000123"
        with override_settings(LIBRARY_GRAPH_MAILBOX_ID=mailbox_id):
            GraphClient(fake).send(self.message(), "Synthetic", "Body")
        self.assertIn(f"/users/{mailbox_id}/sendMail", calls[-1].full_url)
        self.assertEqual(json.loads(calls[-1].data)["message"]["replyTo"][0]["emailAddress"]["address"], "sender@example.test")

    def test_invalid_mailbox_id_and_reply_to_are_rejected_before_authentication(self):
        for setting, value in (("LIBRARY_GRAPH_MAILBOX_ID", "not-a-uuid"), ("LIBRARY_GRAPH_REPLY_TO", "invalid-email")):
            with self.subTest(setting=setting), override_settings(**{setting: value}):
                calls, fake = self.transport()
                with self.assertRaises((ImproperlyConfigured, ValidationError)):
                    GraphClient(fake).send(self.message(), "Synthetic", "Body")
                self.assertEqual(calls, [])

    def test_sender_is_never_inferred_from_smtp_default_or_legacy_microsoft_credentials(self):
        with override_settings(LIBRARY_GRAPH_SENDER="", DEFAULT_FROM_EMAIL="legacy@example.test",
                              MICROSOFT_CLIENT_ID="legacy-unapproved", MICROSOFT_TENANT_ID="legacy-unapproved"):
            calls, fake = self.transport()
            with self.assertRaises(ValidationError):
                GraphClient(fake).send(self.message(), "Synthetic", "Body")
            self.assertEqual(calls, [])

    def test_recipient_allowlist_still_blocks_before_token_or_send(self):
        calls, fake = self.transport()
        self.assertEqual(GraphClient(fake).send(self.message("other@example.test"), "Synthetic", "Body").code, "recipient_not_allowlisted")
        self.assertEqual(calls, [])

    def test_new_mailbox_option_does_not_enable_delivery(self):
        self.assertEqual(graph_mailbox_target(), "sender@example.test")
        with self.assertRaises(ImproperlyConfigured):
            require_live_graph()
