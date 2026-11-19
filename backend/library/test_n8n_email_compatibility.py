"""Synthetic n8n parity checks; no provider connection or credential loading."""
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.test import TestCase, override_settings

from . import test_email_system as fixtures
from .email_events import emit_loan
from .email_models import EmailOutbox
from .email_scheduler import schedule_reminders
from .email_templates import render_email
from .email_worker import EmailWorker
from .models import Loan
from .n8n_email_templates import ADMIN_RECIPIENT, TEMPLATES


class N8nCompatibilityTests(TestCase):
    setUp = fixtures.EmailSystemTests.setUp
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm
    reminder_loan = fixtures.EmailSystemTests.reminder_loan
    set_zone = fixtures.EmailSystemTests.set_zone

    def enable_compatibility(self):
        # Synthetic account only. The isolated runner forbids all external IO.
        self.admin.email = ADMIN_RECIPIENT.lower()
        self.admin.save(update_fields={"email"})
        config = override_settings(LIBRARY_EMAIL_N8N_COMPAT_ENABLED=True)
        config.enable()
        self.addCleanup(config.disable)

    def test_default_mode_and_all_delivery_flags_remain_off(self):
        self.assertFalse(settings.LIBRARY_EMAIL_N8N_COMPAT_ENABLED)
        self.assertFalse(settings.LIBRARY_GRAPH_SEND_ENABLED)
        self.assertFalse(settings.LIBRARY_GRAPH_CREDENTIALS_APPROVED)
        # The fixture enables enqueue/worker/scheduler locally; base defaults
        # are checked by the existing readiness suite.

    def test_new_submission_preserves_single_admin_and_student_addresses(self):
        self.enable_compatibility()
        loan = self.new_loan("compat-submission")
        rows = list(loan.email_messages.order_by("recipient_role"))
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.template_version for row in rows}, {2})
        student = next(row for row in rows if row.recipient_role == "student")
        admin = next(row for row in rows if row.recipient_role == "admin")
        self.assertEqual(student.recipient_email, loan.borrower_email)
        self.assertEqual(admin.recipient_email, ADMIN_RECIPIENT)
        self.assertEqual(admin.recipient_id, self.admin.pk)
        subject, html = render_email(admin)
        self.assertEqual(subject, "New Borrow Request: " + self.resource.title)
        self.assertIn(loan.borrower_email, html)
        self.assertIn(loan.borrower_phone, html)
        self.assertIn(self.copy.accession_number, html)
        self.assertNotIn("borrower_phone", student.payload)
        with transaction.atomic():
            emit_loan(loan, "loan_submitted", admin=True)
        self.assertEqual(loan.email_messages.count(), 2)

    def test_original_html_and_subjects_render_without_n8n_expressions(self):
        self.enable_compatibility()
        row = self.loan.email_messages.filter(recipient_role="student").get()
        row.template_version = 2
        row.payload.update(due_date="1999-12-31", feedback_url="https://library.example.test/feedback?token=synthetic&other=1",
                           borrower_email="synthetic@example.test", borrower_phone="00000000000")
        for key in TEMPLATES:
            with self.subTest(key=key):
                row.template_key = key
                row.event_type, row.recipient_role = key.split(".")
                subject, html = render_email(row)
                self.assertNotIn("<script>", html)
                self.assertNotIn("$json", html + subject)
                self.assertNotIn("{{", html + subject)
                self.assertNotIn("\n", subject)
                self.assertNotIn("\r", subject)
                self.assertFalse(subject.startswith("="))
                if key in ("overdue.student", "due_today.student"):
                    self.assertIn("31 Dec 1999", html)
                if key == "borrow_confirmed.student":
                    self.assertEqual(subject, 'Borrow approved: ' + self.resource.title + ' — KBC Library')
                    self.assertIn("1999-12-31", html)
                if key == "due_today.student":
                    self.assertIn("due today", html)
                    self.assertNotIn("due soon", html)
                if key == "loan_returned.student":
                    self.assertIn("token=synthetic&amp;other=1", html)
                    self.assertIn("Send Feedback", html)

    def test_existing_version_one_is_unchanged_when_compatibility_is_enabled(self):
        row = self.loan.email_messages.filter(recipient_role="student").get()
        before = render_email(row)
        self.enable_compatibility()
        self.assertEqual(render_email(row), before)
        self.assertEqual(row.template_version, 1)

    def test_version_two_remains_renderable_if_configuration_is_disabled(self):
        self.enable_compatibility()
        loan = self.new_loan("compat-durable")
        row = loan.email_messages.get(recipient_role="student")
        before = render_email(row)
        with override_settings(LIBRARY_EMAIL_N8N_COMPAT_ENABLED=False):
            self.assertEqual(render_email(row), before)

    def test_version_two_passes_through_worker_once_using_only_a_fake_client(self):
        self.enable_compatibility()
        loan = self.new_loan("compat-worker")
        row = loan.email_messages.get(recipient_role="student")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        row.available_at = fixtures.NOW
        row.save(update_fields={"available_at"})
        fake = fixtures.FakeGraph()
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=(row.recipient_email,)):
            worker = EmailWorker(client=fake)
            self.assertEqual(worker.run_once(now=fixtures.NOW), ["accepted"])
            self.assertEqual(worker.run_once(now=fixtures.NOW), [])
        row.refresh_from_db()
        self.assertEqual(row.attempts_count, 1)
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(fake.sent[0][1], "Your borrow request has been received — KBC Library")
        self.assertIn("Borrow Request Received", fake.sent[0][2])

    def test_unmatched_administrator_fails_without_rerouting_or_partial_source(self):
        with override_settings(LIBRARY_EMAIL_N8N_COMPAT_ENABLED=True):
            with self.assertRaises(ImproperlyConfigured), transaction.atomic():
                self.new_loan("compat-wrong-admin")
        self.assertFalse(Loan.objects.filter(pk="compat-wrong-admin").exists())
        self.assertFalse(EmailOutbox.objects.filter(source_id="compat-wrong-admin").exists())

    def test_two_configured_accounts_cannot_duplicate_the_original_recipient(self):
        self.enable_compatibility()
        duplicate = get_user_model().objects.create_user("duplicate-admin", email=ADMIN_RECIPIENT, is_staff=True)
        with override_settings(LIBRARY_EMAIL_ADMIN_USER_IDS=(self.admin.pk, duplicate.pk)):
            with self.assertRaises(ImproperlyConfigured), transaction.atomic():
                self.new_loan("compat-two-admins")
        self.assertFalse(Loan.objects.filter(pk="compat-two-admins").exists())

    def test_header_injection_and_unsafe_feedback_url_are_rejected(self):
        row = self.loan.email_messages.get(recipient_role="student")
        row.template_version, row.template_key = 2, "borrow_confirmed.student"
        row.payload["book_title"] = "Synthetic\r\nBcc: invalid@example.test"
        with self.assertRaises(ValidationError):
            render_email(row)
        row.template_key = "loan_returned.student"
        row.payload["book_title"] = "Synthetic"
        for url in ("javascript:alert(1)", "https://user:password@example.test/feedback", ""):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                row.payload["feedback_url"] = url
                render_email(row)

    def test_added_phase_three_events_keep_their_existing_templates(self):
        self.enable_compatibility()
        target = self.new_loan("compat-notify", loan_type="notify")
        row = target.email_messages.get()
        self.assertEqual(row.event_type, "notify_registered")
        self.assertEqual(row.template_version, 1)

    def test_scheduled_templates_preserve_approved_nine_am_and_odd_day_policy(self):
        self.enable_compatibility()
        self.set_zone("Europe/London")
        self.reminder_loan(due=date(2028, 7, 15))
        at = datetime(2028, 7, 15, 8, tzinfo=timezone.utc)  # 09:00 BST.
        self.assertEqual(schedule_reminders(now=at - timedelta(seconds=1))["queued"], 0)
        for day, expected in ((0, 1), (1, 1), (2, 0), (3, 1), (4, 0), (5, 1)):
            self.assertEqual(schedule_reminders(now=at + timedelta(days=day))["queued"], expected)
            self.assertEqual(schedule_reminders(now=at + timedelta(days=day))["queued"], 0)
        rows = self.loan.email_messages.filter(message_kind="reminder")
        self.assertEqual(set(rows.values_list("payload__days_overdue", flat=True)), {0, 1, 3, 5})
        self.assertEqual(set(rows.values_list("template_version", flat=True)), {2})
        for row in rows:
            subject, html = render_email(row)
            self.assertEqual(subject, "KBC Library Reminder" if row.event_type == "due_today" else "Overdue Notice")
            self.assertIn("15 Jul 2028", html)
            if row.event_type == "overdue":
                self.assertIn(self.copy.accession_number, html)
