"""The one authorized self-test must never become a general mail sender."""
import base64
from email.message import EmailMessage
from email.policy import SMTP
import json
from pathlib import Path
import tempfile
from urllib.request import Request

from django.test import SimpleTestCase

from .gmail_test_safety import (ADDRESS, SUBJECT, SEND_URL, TOKEN_URL, AI_TEAM_TEST, CHARLY_TEST,
    SingleSendGuard, SingleTestError, first_test_marker, validate_grant)


class GmailSingleSendSafetyTests(SimpleTestCase):
    def request(self, *, to=ADDRESS, sender=ADDRESS, subject=SUBJECT, cc=None, scenario=AI_TEAM_TEST):
        mime = EmailMessage(policy=SMTP)
        mime["From"], mime["To"], mime["Reply-To"], mime["Subject"] = sender, to, scenario.sender, subject
        if cc:
            mime["Cc"] = cc
        mime.set_content("Synthetic safety test", subtype="html")
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        return Request(scenario.send_url, data=json.dumps({"raw":raw}).encode(), method="POST")

    def test_one_post_creates_durable_fence_and_records_only_safe_response_fields(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-send-budget-") as directory:
            marker = Path(directory) / "attempted"
            calls = []
            def fake(request):
                calls.append(request)
                return 200, {}, b'{"id":"synthetic-id","labelIds":["SENT","INBOX"],"private":"never-copy"}'
            guard = SingleSendGuard(fake, marker, "synthetic-outbox")
            self.assertEqual(guard(self.request())[0], 200)
            self.assertEqual(guard.send_calls, 1)
            self.assertEqual(json.loads(marker.read_text())["message_id"], "synthetic-outbox")
            self.assertEqual(guard.response["system_labels"], ["SENT","INBOX"])
            self.assertNotIn("private", guard.response)
            with self.assertRaises(SingleTestError):
                guard(self.request())
            with self.assertRaises(SingleTestError):
                SingleSendGuard(fake, marker, "another-outbox")(self.request())
            self.assertEqual(len(calls), 1)

    def test_timeout_consumes_budget_and_never_permits_a_replay(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-send-budget-") as directory:
            marker = Path(directory) / "attempted"
            calls = []
            def timeout(request):
                calls.append(request)
                raise TimeoutError()
            guard = SingleSendGuard(timeout, marker, "synthetic")
            with self.assertRaises(TimeoutError):
                guard(self.request())
            with self.assertRaises(SingleTestError):
                guard(self.request())
            self.assertEqual(len(calls), 1)
            self.assertTrue(marker.exists())

    def test_wrong_sender_recipient_extra_recipient_or_subject_is_blocked_before_network(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-send-budget-") as directory:
            calls = []
            marker = Path(directory) / "attempted"
            guard = SingleSendGuard(lambda request: calls.append(request), marker, "synthetic")
            for values in ({"to":"student@example.test"}, {"sender":"other@example.test"},
                           {"cc":ADDRESS}, {"subject":"Wrong test subject"},
                           {"to":ADDRESS + ", other@example.test"}):
                with self.subTest(values=values), self.assertRaises(SingleTestError):
                    guard(self.request(**values))
            self.assertFalse(calls)
            self.assertFalse(marker.exists())

    def test_no_other_gmail_api_endpoints_or_read_scope_are_used(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-send-budget-") as directory:
            guard = SingleSendGuard(lambda request: (200,{},b'{}'), Path(directory) / "attempted", "synthetic")
            with self.assertRaises(SingleTestError):
                guard(Request("https://gmail.googleapis.com/gmail/v1/users/me/messages"))
            self.assertEqual(guard(Request(TOKEN_URL, data=b"synthetic", method="POST"))[0], 200)
            self.assertEqual(guard.send_calls, 0)

    def test_grant_must_be_test_only_same_account_same_sender_and_not_production_approved(self):
        value = {"credential_usage":"test_only", "profile_name":"ai-team-test", "production_sender_approved":False,
                 "account_email":ADDRESS,"sender":ADDRESS,"account_sub":"synthetic-sub",
                 "client_id":"synthetic","client_secret":"synthetic","refresh_token":"synthetic"}
        validate_grant(value)
        for changed in ({"credential_usage":"library"}, {"sender":"other@example.test"},
                        {"account_email":"other@example.test"}, {"production_sender_approved":True}):
            with self.subTest(changed=changed), self.assertRaises(SingleTestError):
                validate_grant({**value, **changed})

    def test_charly_requires_confirmed_library_identity_and_exact_saved_sender(self):
        value = {"account_email":CHARLY_TEST.sender, "sender":CHARLY_TEST.sender,
                 "n8n_identity_confirmed":True, "account_sub":"synthetic-sub",
                 "scopes":["https://www.googleapis.com/auth/gmail.send"],
                 "client_id":"synthetic", "client_secret":"synthetic", "refresh_token":"synthetic"}
        validate_grant(value, CHARLY_TEST)
        for changed in ({"credential_usage":"test_only"}, {"profile_name":"ai-team-test"},
                        {"account_email":ADDRESS}, {"sender":ADDRESS}, {"sender":""},
                        {"n8n_identity_confirmed":False}, {"scopes":[]}, {"refresh_token":""}):
            with self.subTest(changed=changed), self.assertRaises(SingleTestError):
                validate_grant({**value, **changed}, CHARLY_TEST)

    def test_charly_has_exact_envelope_subject_and_its_own_durable_budget(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-charly-budget-") as directory:
            marker = Path(directory) / "charly-attempted"
            calls = []
            def fake(request):
                calls.append(request)
                return 200, {}, b'{"id":"synthetic-charly","labelIds":["SENT"]}'
            guard = SingleSendGuard(fake, marker, "synthetic-charly-outbox", scenario=CHARLY_TEST)
            request = self.request(sender=CHARLY_TEST.sender, subject=CHARLY_TEST.subject, scenario=CHARLY_TEST)
            self.assertEqual(guard(request)[0], 200)
            recorded = json.loads(marker.read_text())
            self.assertEqual(recorded["sender"], CHARLY_TEST.sender)
            self.assertEqual(recorded["recipient"], ADDRESS)
            self.assertEqual(recorded["subject"], CHARLY_TEST.subject)
            with self.assertRaises(SingleTestError):
                SingleSendGuard(fake, marker, "second-outbox", scenario=CHARLY_TEST)(request)
            self.assertEqual(len(calls), 1)

    def test_charly_rejects_ai_team_sender_student_recipient_or_other_subject_before_network(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-charly-budget-") as directory:
            calls = []
            guard = SingleSendGuard(lambda request: calls.append(request), Path(directory) / "attempted",
                                    "synthetic", scenario=CHARLY_TEST)
            valid = {"sender":CHARLY_TEST.sender, "subject":CHARLY_TEST.subject, "scenario":CHARLY_TEST}
            for changed in ({"sender":ADDRESS}, {"to":CHARLY_TEST.sender}, {"subject":SUBJECT},
                            {"cc":ADDRESS}, {"to":ADDRESS + ", another@example.test"}):
                with self.subTest(changed=changed), self.assertRaises(SingleTestError):
                    guard(self.request(**{**valid, **changed}))
            with self.assertRaises(SingleTestError):
                guard(self.request())  # The old test's Gmail endpoint is also forbidden.
            self.assertFalse(calls)
            self.assertFalse(guard.marker.exists())

    def test_charly_timeout_cannot_be_replayed(self):
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-charly-budget-") as directory:
            calls = []
            marker = Path(directory) / "attempted"
            def timeout(request):
                calls.append(request)
                raise TimeoutError()
            request = self.request(sender=CHARLY_TEST.sender, subject=CHARLY_TEST.subject, scenario=CHARLY_TEST)
            with self.assertRaises(TimeoutError):
                SingleSendGuard(timeout, marker, "synthetic", scenario=CHARLY_TEST)(request)
            with self.assertRaises(SingleTestError):
                SingleSendGuard(timeout, marker, "retry", scenario=CHARLY_TEST)(request)
            self.assertEqual(len(calls), 1)

    def test_existing_ai_team_fence_and_new_charly_fence_have_distinct_fixed_names(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix="kbc-synthetic-test-markers-") as directory:
            with patch.dict("os.environ", {"LOCALAPPDATA":directory}):
                self.assertEqual(first_test_marker().name, "first-gmail-integration-test.attempted")
                self.assertEqual(first_test_marker(CHARLY_TEST).name, "first-charly-gmail-integration-test.attempted")
                self.assertNotEqual(first_test_marker(), first_test_marker(CHARLY_TEST))
