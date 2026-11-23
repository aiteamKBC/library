"""Source-scoped recipient authorization with synthetic identities and transports."""
import json
from unittest.mock import Mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from . import test_email_system as fixtures
from .email_policy import (
    EVENTS, recipient_allowed, recipient_mode, recipient_rejection,
    require_live_delivery, routes_to_django,
)
from .email_models import EmailOutbox
from .gmail_client import GmailClient
from .graph_client import GraphClient
from .models import BookRequest, Loan, UserProfile
from .n8n_email_templates import ADMIN_RECIPIENT
from .test_gmail_client import GMAIL, TOKEN


GRAPH = {
    "LIBRARY_EMAIL_PROVIDER": "graph",
    "LIBRARY_GRAPH_TENANT_ID": "synthetic-tenant",
    "LIBRARY_GRAPH_CLIENT_ID": "synthetic-client",
    "LIBRARY_GRAPH_CLIENT_SECRET": "synthetic-secret",
    "LIBRARY_GRAPH_SENDER": "library@example.test",
    "LIBRARY_GRAPH_REPLY_TO": "",
}
COMMON_GATES = {
    "LIBRARY_EMAIL_WORKER_ENABLED": True,
    "LIBRARY_EMAIL_ENQUEUE_ENABLED": True,
    "LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED": True,
    "LIBRARY_EMAIL_OWNED_EVENTS": tuple(EVENTS),
    "LIBRARY_EMAIL_RECIPIENT_MODE": "source_scoped",
    "LIBRARY_EMAIL_RECIPIENT_ALLOWLIST": (),
    "LIBRARY_GMAIL_SEND_ENABLED": True,
    "LIBRARY_GMAIL_CREDENTIALS_APPROVED": True,
    "LIBRARY_GRAPH_SEND_ENABLED": True,
    "LIBRARY_GRAPH_CREDENTIALS_APPROVED": True,
}


class RecipientModeTests(SimpleTestCase):
    def test_default_preserves_exact_allowlist_without_requiring_source_context(self):
        self.assertEqual(settings.LIBRARY_EMAIL_RECIPIENT_MODE, "allowlist")
        self.assertEqual(recipient_mode(), "allowlist")
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("Student@example.test",)):
            self.assertTrue(recipient_allowed("student@example.test"))
            self.assertFalse(recipient_allowed("other@example.test"))
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            self.assertFalse(recipient_allowed("student@example.test"))

    def test_allowlist_still_rejects_wildcards_and_malformed_addresses(self):
        for values in (("*@example.test",), ("student@example.test", "invalid"), "student@example.test"):
            with self.subTest(values=values), override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=values):
                self.assertFalse(recipient_allowed("student@example.test"))
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("student@example.test",)):
            for address in (None, "", " student@example.test", "student@example.test\n", "bad"):
                with self.subTest(address=address):
                    self.assertFalse(recipient_allowed(address))

    @override_settings(LIBRARY_EMAIL_RECIPIENT_MODE="source_scoped",
                       LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("student@example.test",))
    def test_source_mode_requires_message_even_for_an_allowlisted_address(self):
        self.assertFalse(recipient_allowed("student@example.test"))
        self.assertEqual(recipient_rejection("student@example.test"), "recipient_source_mismatch")

    def test_unknown_mode_does_not_silently_fall_back(self):
        for mode in ("", "all", "SOURCE_SCOPED", None):
            with self.subTest(mode=mode), override_settings(LIBRARY_EMAIL_RECIPIENT_MODE=mode):
                with self.assertRaises(ImproperlyConfigured):
                    recipient_mode()

    def test_source_mode_accepts_empty_allowlist_but_keeps_live_delivery_gates(self):
        for provider, credentials in (("gmail", GMAIL), ("graph", GRAPH)):
            with self.subTest(provider=provider), override_settings(**COMMON_GATES, **credentials):
                require_live_delivery()
                self.assertTrue(routes_to_django("loan_submitted"))
                mandatory = {
                    "LIBRARY_EMAIL_WORKER_ENABLED": False,
                    "LIBRARY_EMAIL_ENQUEUE_ENABLED": False,
                    "LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED": False,
                    f"LIBRARY_{provider.upper()}_SEND_ENABLED": False,
                    f"LIBRARY_{provider.upper()}_CREDENTIALS_APPROVED": False,
                }
                if provider == "gmail":
                    mandatory.update({name: "" for name in (
                        "LIBRARY_GMAIL_CLIENT_ID", "LIBRARY_GMAIL_CLIENT_SECRET",
                        "LIBRARY_GMAIL_REFRESH_TOKEN", "LIBRARY_GMAIL_ACCOUNT_EMAIL", "LIBRARY_GMAIL_SENDER",
                    )})
                else:
                    mandatory.update({name: "" for name in (
                        "LIBRARY_GRAPH_TENANT_ID", "LIBRARY_GRAPH_CLIENT_ID",
                        "LIBRARY_GRAPH_CLIENT_SECRET", "LIBRARY_GRAPH_SENDER",
                    )})
                for name, value in mandatory.items():
                    with self.subTest(setting=name), override_settings(**{name: value}):
                        with self.assertRaises(ImproperlyConfigured):
                            require_live_delivery()
                        self.assertFalse(routes_to_django("loan_submitted"))
                with override_settings(LIBRARY_EMAIL_OWNED_EVENTS=()):
                    self.assertFalse(routes_to_django("loan_submitted"))
                for mode in ("allowlist", "unknown"):
                    with self.subTest(mode=mode), override_settings(LIBRARY_EMAIL_RECIPIENT_MODE=mode):
                        with self.assertRaises(ImproperlyConfigured):
                            require_live_delivery()


class SourceScopedRecipientTests(TestCase):
    new_loan = fixtures.EmailSystemTests.new_loan

    def setUp(self):
        fixtures.EmailSystemTests.setUp(self)
        config = override_settings(LIBRARY_EMAIL_RECIPIENT_MODE="source_scoped",
                                   LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=())
        config.enable()
        self.addCleanup(config.disable)
        self.request = BookRequest.objects.create(
            id="recipient-book-request", requester=self.student, student_name="Synthetic Student",
            student_email=self.student.email, book_title="Synthetic Book", category="Business",
        )

    def message(self, event="loan_submitted", role="student"):
        source = self.request if event == "book_request_submitted" else self.loan
        message = source.email_messages.get(recipient_role=role)
        message.event_type = event
        message.template_key = f"{event}.{role}"
        message.message_kind = "reminder" if event in ("due_today", "overdue") else "event"
        return message

    def allowed(self, message):
        return recipient_allowed(message.recipient_email, message=message)

    def test_all_thirteen_student_events_allow_their_current_source_recipient(self):
        self.assertEqual(len(EVENTS), 13)
        for event in EVENTS:
            with self.subTest(event=event):
                message = self.message(event)
                self.assertTrue(self.allowed(message))
                self.assertEqual(recipient_rejection(message.recipient_email, message=message), "")

    def test_administration_is_limited_to_the_two_submission_events(self):
        for event in EVENTS:
            with self.subTest(event=event):
                self.assertEqual(self.allowed(self.message(event, "admin")),
                                 event in ("loan_submitted", "book_request_submitted"))

    def test_message_metadata_cannot_substitute_another_source_or_recipient(self):
        for event in ("loan_submitted", "book_request_submitted"):
            changes = {
                "source_id": "another-source", "source_type": "unknown",
                "recipient_id": self.admin.pk, "recipient_key": f"user:{self.admin.pk}",
                "recipient_role": "external", "recipient_email": self.admin.email,
                "template_key": "manual_email.admin", "message_kind": "reminder",
                "event_type": "not_an_email_event",
            }
            for name, value in changes.items():
                with self.subTest(event=event, field=name):
                    message = self.message(event)
                    setattr(message, name, value)
                    self.assertFalse(self.allowed(message))
            message = self.message(event)
            self.assertFalse(recipient_allowed(self.admin.email, message=message))
            for role in ("librarian", "", "admin"):
                with self.subTest(event=event, role=role):
                    message = self.message(event)
                    message.recipient_role = role
                    message.template_key = f"{event}.{role}"
                    self.assertFalse(self.allowed(message))

    def test_source_foreign_keys_and_event_family_must_agree(self):
        for event in ("loan_submitted", "book_request_submitted"):
            with self.subTest(event=event):
                message = self.message(event)
                message.loan_id = self.loan.pk
                message.book_request_id = self.request.pk
                self.assertFalse(self.allowed(message))
                message.loan_id = message.book_request_id = None
                self.assertFalse(self.allowed(message))
        message = self.message("book_request_submitted")
        message.event_type = "manual_email"
        message.template_key = "manual_email.student"
        self.assertFalse(self.allowed(message))
        message = self.message()
        message.event_type = "book_request_submitted"
        message.template_key = "book_request_submitted.student"
        self.assertFalse(self.allowed(message))

    def test_reminder_and_immediate_message_kinds_cannot_be_interchanged(self):
        for event in EVENTS:
            with self.subTest(event=event):
                message = self.message(event)
                message.message_kind = "event" if message.message_kind == "reminder" else "reminder"
                self.assertFalse(self.allowed(message))

    def test_current_source_email_is_rechecked_despite_cached_related_objects(self):
        for event, model, field in (("loan_submitted", Loan, "borrower_email"),
                                    ("book_request_submitted", BookRequest, "student_email")):
            with self.subTest(event=event):
                message = self.message(event)
                source = message.loan if event == "loan_submitted" else message.book_request
                self.assertTrue(self.allowed(message))
                model._base_manager.filter(pk=source.pk).update(**{field: "updated@example.test"})
                self.assertFalse(self.allowed(message))
                message.recipient_email = "updated@example.test"
                # A caller-controlled source email is insufficient: it must
                # still belong to the source's current authenticated account.
                self.assertFalse(self.allowed(message))
                get_user_model().objects.filter(pk=self.student.pk).update(email="updated@example.test")
                self.assertTrue(self.allowed(message))
                get_user_model().objects.filter(pk=self.student.pk).update(email=self.student.email)

    def test_empty_loan_snapshot_email_uses_current_borrower_email(self):
        Loan._base_manager.filter(pk=self.loan.pk).update(borrower_email="")
        message = self.message()
        self.assertTrue(self.allowed(message))
        get_user_model().objects.filter(pk=self.student.pk).update(email="updated@example.test")
        self.assertFalse(self.allowed(message))
        message.recipient_email = "updated@example.test"
        self.assertTrue(self.allowed(message))

    def test_changed_account_email_invalidates_old_source_and_recipient_snapshots(self):
        messages = [self.message(event) for event in ("loan_submitted", "book_request_submitted")]
        for message in messages:
            message.recipient
        get_user_model().objects.filter(pk=self.student.pk).update(email="new-account@example.test")
        for message in messages:
            with self.subTest(event=message.event_type):
                self.assertFalse(self.allowed(message))

    def test_source_mode_rejects_invalid_recipient_syntax(self):
        for address in (None, "", " student@example.test", "student@example.test\n", "*@example.test"):
            with self.subTest(address=address):
                message = self.message()
                message.recipient_email = address
                self.assertFalse(self.allowed(message))

    def test_reassigned_or_missing_source_owner_does_not_authorize_the_old_recipient(self):
        for event, model, field in (("loan_submitted", Loan, "borrower_id"),
                                    ("book_request_submitted", BookRequest, "requester_id")):
            with self.subTest(event=event):
                message = self.message(event)
                model._base_manager.filter(pk=message.source_id).update(**{field: self.admin.pk})
                self.assertFalse(self.allowed(message))
                model._base_manager.filter(pk=message.source_id).update(**{field: None})
                self.assertFalse(self.allowed(message))

    def test_inactive_or_deleted_source_account_blocks_students_but_preserves_admin_notices(self):
        messages = [self.message(event, role) for event in ("loan_submitted", "book_request_submitted")
                    for role in ("student", "admin")]
        for message in messages:
            message.recipient  # Populate the relation cache before the database changes.
        get_user_model().objects.filter(pk=self.student.pk).update(is_active=False)
        for message in messages:
            with self.subTest(event=message.event_type, role=message.recipient_role, state="inactive"):
                self.assertEqual(self.allowed(message), message.recipient_role == "admin")
        # Loan.borrower cascades on deletion; detach it to model an existing
        # guest/legacy source. BookRequest.requester already uses SET_NULL.
        Loan._base_manager.filter(pk=self.loan.pk).update(borrower_id=None)
        get_user_model().objects.filter(pk=self.student.pk).delete()
        for message in messages:
            with self.subTest(event=message.event_type, role=message.recipient_role, state="deleted"):
                self.assertEqual(self.allowed(message), message.recipient_role == "admin")

    def test_deleted_source_is_rejected_even_when_the_outbox_object_has_cached_relations(self):
        messages = [self.message(event) for event in ("loan_submitted", "book_request_submitted")]
        messages[0].loan
        messages[1].book_request
        Loan._base_manager.filter(pk=self.loan.pk).delete()
        BookRequest.objects.filter(pk=self.request.pk).delete()
        for message in messages:
            with self.subTest(event=message.event_type):
                self.assertFalse(self.allowed(message))

    def test_administrator_requires_current_configuration_email_and_staff_status(self):
        message = self.message(role="admin")
        message.recipient
        self.assertTrue(self.allowed(message))
        with override_settings(LIBRARY_EMAIL_ADMIN_USER_IDS=()):
            self.assertFalse(self.allowed(message))
        with override_settings(LIBRARY_EMAIL_ADMIN_USER_IDS=(self.student.pk,)):
            self.assertFalse(self.allowed(message))
        get_user_model().objects.filter(pk=self.admin.pk).update(email="new-admin@example.test")
        self.assertFalse(self.allowed(message))
        message.recipient_email = "new-admin@example.test"
        self.assertTrue(self.allowed(message))
        get_user_model().objects.filter(pk=self.admin.pk).update(is_staff=False)
        UserProfile.objects.filter(user=self.admin).update(role="student")
        self.assertFalse(self.allowed(message))

    def test_inactive_or_deleted_administrator_cannot_receive(self):
        message = self.message(role="admin")
        get_user_model().objects.filter(pk=self.admin.pk).update(is_active=False)
        self.assertFalse(self.allowed(message))
        get_user_model().objects.filter(pk=self.admin.pk).delete()
        self.assertFalse(self.allowed(message))

    def test_stored_n8n_admin_template_keeps_original_recipient_after_mode_flag_changes(self):
        message = self.message(role="admin")
        message.template_version = 2
        with override_settings(LIBRARY_EMAIL_N8N_COMPAT_ENABLED=False):
            self.assertFalse(self.allowed(message))
            get_user_model().objects.filter(pk=self.admin.pk).update(email=ADMIN_RECIPIENT.lower())
            message.recipient_email = ADMIN_RECIPIENT
            self.assertTrue(self.allowed(message))
            with override_settings(LIBRARY_EMAIL_ADMIN_USER_IDS=(self.admin.pk, self.student.pk)):
                self.assertFalse(self.allowed(message))

    def test_provider_guards_reject_invalid_context_before_oauth_or_send_even_with_cached_token(self):
        for provider, credentials in ((GmailClient, GMAIL), (GraphClient, GRAPH)):
            with self.subTest(provider=provider.__name__), override_settings(**credentials):
                for cached in (False, True):
                    transport = Mock(side_effect=AssertionError("No external request is authorized"))
                    client = provider(transport)
                    if cached:
                        client._token, client._expires = "synthetic-token", float("inf")
                    message = self.message()
                    message.source_id = "forged-source"
                    result = client.send(message, "Synthetic", "<p>Synthetic</p>")
                    self.assertEqual((result.outcome, result.code),
                                     ("permanent_failure", "recipient_source_mismatch"))
                    transport.assert_not_called()

    def test_valid_source_scoped_recipient_reaches_only_the_fake_provider_without_allowlisting(self):
        for provider, credentials in ((GmailClient, GMAIL), (GraphClient, GRAPH)):
            calls = []

            def transport(request):
                calls.append(request)
                if request.full_url.endswith("/token"):
                    return 200, {}, TOKEN
                if provider is GmailClient:
                    return 200, {}, json.dumps({"id": "synthetic-message"}).encode()
                return 202, {}, b""

            with self.subTest(provider=provider.__name__), override_settings(**credentials):
                result = provider(transport).send(self.message(), "Synthetic", "<p>Synthetic</p>")
                self.assertEqual(result.outcome, "accepted")
                self.assertEqual(len(calls), 2)

    @override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE="Europe/London")
    def test_worker_combines_source_policy_and_optional_timezone_without_allowlisting(self):
        fixtures.EmailSystemTests.set_zone(self, None)
        message = fixtures.EmailSystemTests.one_message(self)
        worker, fake = fixtures.EmailSystemTests.worker(self)
        self.assertEqual(worker.run_once(now=fixtures.NOW), ["accepted"])
        message.refresh_from_db()
        self.assertEqual(message.recipient_timezone, "Europe/London")
        self.assertEqual(message.attempts.count(), 1)
        self.assertEqual(len(fake.sent), 1)
        self.assertIsNone(UserProfile.objects.get(user=self.student).time_zone)

    def test_worker_blocks_a_redirected_source_before_creating_an_attempt(self):
        message = fixtures.EmailSystemTests.one_message(self)
        Loan._base_manager.filter(pk=self.loan.pk).update(borrower_email="unrelated@example.test")
        EmailOutbox.objects.filter(pk=message.pk).update(recipient_email="unrelated@example.test")
        worker, fake = fixtures.EmailSystemTests.worker(self)
        self.assertEqual(worker.run_once(now=fixtures.NOW), ["blocked"])
        message.refresh_from_db()
        self.assertEqual(message.error_code, "recipient_source_mismatch")
        self.assertFalse(message.attempts.exists())
        self.assertFalse(fake.sent)
