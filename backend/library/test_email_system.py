from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone as dt_timezone
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
from io import StringIO
import json
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.core.management import call_command
from django.contrib import admin
from django.test import RequestFactory
from rest_framework.test import APIClient

from .email_events import (emit_loan, enqueue_manual, record_loan_change, record_book_request)
from .email_models import EmailOutbox, EmailAttempt
from .email_policy import EVENTS, routes_to_django
from .email_scheduler import schedule_reminders
from .email_templates import COPY, render_email
from .email_worker import EmailWorker, retry_message
from .graph_client import GraphClient, GraphResult, retry_after_seconds
from .models import BookCopy, BookRequest, Category, Loan, Resource, UserProfile
from .notification_timing import local_reminder_window

UTC = dt_timezone.utc
NOW = datetime(2028, 7, 15, 12, tzinfo=UTC)


class FakeGraph:
    def __init__(self, *results):
        self.results = list(results)
        self.sent = []

    def send(self, row, subject, html):
        self.sent.append((row.pk, subject, html))
        result = self.results.pop(0) if self.results else GraphResult("accepted", 202)
        if isinstance(result, Exception):
            raise result
        return result


class EmailSystemTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.student = User.objects.create_user("mail-student", email="student@example.test")
        self.admin = User.objects.create_user("mail-admin", email="admin@example.test", is_staff=True)
        for user, zone in ((self.student, "Africa/Cairo"), (self.admin, "Europe/London")):
            UserProfile.objects.create(user=user, role="admin" if user == self.admin else "student",
                time_zone=zone, time_zone_source="manual", time_zone_updated_at=NOW)
        category = Category.objects.create(name="Synthetic", slug="synthetic")
        self.resource = Resource.objects.create(id="mail-book", title="Book <script>unsafe</script>", author="Author", category=category)
        self.copy = BookCopy.objects.create(resource=self.resource, accession_number="MAIL-1")
        config = override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=True, LIBRARY_EMAIL_WORKER_ENABLED=True,
            LIBRARY_EMAIL_SCHEDULER_ENABLED=True, LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=True,
            LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=(self.student.email, self.admin.email, "notify-accept@example.test"),
            LIBRARY_EMAIL_OWNED_EVENTS=tuple(EVENTS), LIBRARY_EMAIL_ADMIN_USER_IDS=(self.admin.pk,))
        config.enable()
        self.addCleanup(config.disable)
        self.loan = self.new_loan("mail-loan")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        webhook = patch("library.views.send_library_webhook", return_value=False)
        webhook.start()
        self.addCleanup(webhook.stop)

    def new_loan(self, pk, **extra):
        student = self.student
        if Loan.objects.filter(borrower=student, status__in=Loan.active_statuses()).exists():
            student = get_user_model().objects.create_user(f"student-{pk}", email=f"{pk}@example.test")
            profile = UserProfile.objects.get(user=self.student)
            UserProfile.objects.create(user=student, time_zone=profile.time_zone,
                time_zone_source=profile.time_zone_source, time_zone_updated_at=profile.time_zone_updated_at)
        return Loan.objects.create(id=pk, borrower=student, borrower_name="Student <b>X</b>",
            borrower_email=student.email, borrower_phone="07123456789", book_copy=self.copy, **extra)

    def confirm(self, status="borrowed"):
        self.loan.status = status
        with patch("library.models.timezone.now", return_value=NOW):
            self.loan.save()
        return self.loan

    def reminder_loan(self, due=date(2028, 7, 15), status="borrowed"):
        self.confirm()
        Loan._base_manager.filter(pk=self.loan.pk).update(due_date=due, status=status)
        self.loan.refresh_from_db()
        return self.loan

    def one_message(self, event="loan_submitted"):
        row = EmailOutbox.objects.filter(event_type=event, recipient_role="student").latest("created_at")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        row.available_at = NOW
        row.save()
        return row

    def set_zone(self, zone, user=None):
        UserProfile.objects.filter(user=user or self.student).update(time_zone=zone,
            time_zone_source="manual" if zone else "", time_zone_updated_at=NOW if zone else None)

    def worker(self, *results):
        fake = FakeGraph(*results)
        return EmailWorker(client=fake), fake

    def test_submission_has_two_different_templates_shared_event(self):
        messages = list(EmailOutbox.objects.filter(event_type="loan_submitted"))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].event_id, messages[1].event_id)
        self.assertEqual(len({m.template_key for m in messages}), 2)
        self.assertEqual({m.recipient_timezone for m in messages}, {"Africa/Cairo", "Europe/London"})

    def test_book_suggestion_has_two_recipients_and_no_cancellation_email(self):
        request = BookRequest.objects.create(id="suggestion", requester=self.student, student_name="Student",
            student_email=self.student.email, book_title="Requested Book", category="Business")
        request.status = "cancelled"
        request.save()
        rows = EmailOutbox.objects.filter(book_request=request)
        self.assertEqual(rows.count(), 2)
        self.assertEqual(len({r.event_id for r in rows}), 1)

    def test_notify_enrollment_is_not_a_borrow_submission(self):
        target = self.new_loan("notify", loan_type="notify")
        self.assertEqual(list(target.email_messages.values_list("event_type", flat=True)), ["notify_registered"])

    def test_confirmation_and_approved_to_borrowed_emit_once(self):
        self.confirm("approved")
        approved, due = self.loan.approved_at, self.loan.due_date
        self.loan.status = "borrowed"
        self.loan.save()
        self.assertEqual(self.loan.approved_at, approved)
        self.assertEqual(self.loan.due_date, due)
        self.assertEqual(self.loan.email_messages.filter(event_type="borrow_confirmed").count(), 1)

    def test_reservation_confirmation_does_not_emit_borrow_confirmation(self):
        Loan._base_manager.filter(pk=self.loan.pk).update(status="reserved")
        self.loan.refresh_from_db()
        self.confirm()
        self.assertEqual(self.loan.email_messages.filter(event_type="reservation_confirmed").count(), 1)
        self.assertFalse(self.loan.email_messages.filter(event_type="borrow_confirmed").exists())

    def test_due_change_has_old_new_details_and_does_not_expose_notes(self):
        self.confirm()
        old_due = self.loan.due_date
        self.loan.delivery_days = 3
        self.loan.notes = "INTERNAL SECRET"
        self.loan.return_condition_notes = "PRIVATE CONDITION"
        self.loan.save()
        row = self.loan.email_messages.get(event_type="due_date_changed")
        self.assertEqual(row.payload["old_due_date"], old_due.isoformat())
        self.assertEqual(row.payload["due_date"], (old_due + timedelta(days=3)).isoformat())
        self.assertEqual((row.payload["old_delivery_days"], row.payload["delivery_days"]), (0, 3))
        self.assertNotIn("INTERNAL", json.dumps(row.payload))
        self.assertNotIn("PRIVATE", render_email(row)[1])
        self.loan.save()
        self.assertEqual(self.loan.email_messages.filter(event_type="due_date_changed").count(), 1)

    def test_partial_save_does_not_emit_for_unpersisted_dirty_fields(self):
        self.loan.status = "cancelled"
        self.loan.notes = "Only notes saved"
        self.loan.save(update_fields={"notes"})
        self.assertFalse(self.loan.email_messages.filter(event_type="loan_cancelled").exists())

    def test_admin_and_student_cancel_are_connected(self):
        response = self.client.patch(f"/api/loans/{self.loan.pk}/", {"status": "cancelled"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(self.loan.email_messages.filter(event_type="loan_cancelled").exists())
        other = self.new_loan("student-cancel")
        self.client.force_authenticate(self.student)
        response = self.client.post(f"/api/loans/{other.pk}/student-cancel/", {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(other.email_messages.filter(event_type="loan_cancelled").exists())

    def test_return_feedback_and_two_availability_audiences(self):
        self.confirm()
        waiting = self.new_loan("waiting")
        notify = self.new_loan("watching", loan_type="notify")
        self.loan.status, self.loan.returned_at = "returned", NOW + timedelta(days=1)
        self.loan.return_condition = "good"
        self.loan.save()
        self.assertIn("/feedback?token=", self.loan.email_messages.get(event_type="loan_returned").payload["feedback_url"])
        self.assertEqual(waiting.email_messages.filter(event_type="book_now_available").count(), 1)
        self.assertEqual(notify.email_messages.filter(event_type="notify_available").count(), 1)

    def test_transaction_rollback_removes_source_and_outbox(self):
        before = EmailOutbox.objects.count()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.new_loan("rollback")
                raise RuntimeError("Synthetic rollback")
        self.assertFalse(Loan.objects.filter(pk="rollback").exists())
        self.assertEqual(EmailOutbox.objects.count(), before)

    def test_enqueue_failure_rolls_back_source_mutation(self):
        with patch("library.email_events.emit_loan", side_effect=ValidationError("Synthetic queue failure")):
            with self.assertRaises(ValidationError):
                self.confirm()
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, "requested")
        self.assertIsNone(self.loan.approved_at)

    def test_producer_replay_deduplicates(self):
        with transaction.atomic():
            record_loan_change(self.loan, None)
        self.assertEqual(self.loan.email_messages.count(), 2)

    def test_api_approval_and_admin_save_use_transactional_producer(self):
        with patch("library.models.timezone.now", return_value=NOW):
            response = self.client.post(f"/api/loans/{self.loan.pk}/approve/", {"deliveryDays": 2}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.loan.email_messages.filter(event_type="borrow_confirmed").count(), 1)
        self.loan.refresh_from_db()
        old = self.loan.due_date
        self.loan.delivery_days = 4
        request = RequestFactory().post("/admin/library/loan/")
        request.user = self.admin
        from .admin import LoanAdmin
        LoanAdmin(Loan, admin.site).save_model(request, self.loan, None, True)
        self.assertEqual(self.loan.due_date, old + timedelta(days=2))
        self.assertEqual(self.loan.email_messages.filter(event_type="due_date_changed").count(), 1)

    def test_unknown_administrator_zone_is_held_independently(self):
        self.set_zone(None, self.admin)
        loan = self.new_loan("admin-no-zone")
        self.assertEqual(loan.email_messages.get(recipient_role="admin").status, "blocked")
        self.assertEqual(loan.email_messages.get(recipient_role="student").status, "pending")

    def test_unconfigured_admins_fail_before_committing_the_source(self):
        with override_settings(LIBRARY_EMAIL_ADMIN_USER_IDS=()):
            with self.assertRaises(ImproperlyConfigured):
                self.new_loan("missing-admin")
        self.assertFalse(Loan.objects.filter(pk="missing-admin").exists())

    def test_queue_monitoring_does_not_print_addresses_or_payloads(self):
        self.reminder_loan()
        out = StringIO()
        call_command("email_queue_status", stdout=out)
        self.assertIn("active_loans_without_timezone", out.getvalue())
        self.assertNotIn(self.student.email, out.getvalue())
        self.assertNotIn(self.resource.title, out.getvalue())

    def test_unknown_timezone_blocks_without_fallback(self):
        self.set_zone(None)
        row = self.new_loan("no-zone").email_messages.get(recipient_role="student")
        self.assertEqual(row.status, "blocked")
        self.assertEqual(row.error_code, "recipient_timezone_missing")
        self.assertIsNone(row.recipient_timezone)

    def test_guest_without_profile_is_held(self):
        loan = Loan.objects.create(id="guest", borrower_name="Guest", borrower_email="guest@example.test",
                                   borrower_phone="07123456789", book_copy=self.copy)
        self.assertEqual(loan.email_messages.get(recipient_role="student").status, "blocked")

    def test_shadow_queue_never_replays_automatically(self):
        with override_settings(LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=False):
            row = self.new_loan("shadow").email_messages.get(recipient_role="student")
        self.assertEqual(row.error_code, "n8n_handoff_required")
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)

    def test_manual_is_idempotent_and_staff_only(self):
        request_id = str(uuid.uuid4())
        body = {"requestId": request_id, "subject": "Question", "message": "Hello <script>X</script>"}
        for _ in range(2):
            response = self.client.post(f"/api/loans/{self.loan.pk}/send_email/", body, format="json")
            self.assertEqual(response.status_code, 202, response.data)
        row = self.loan.email_messages.get(event_type="manual_email")
        self.assertIn("&lt;script&gt;", render_email(row)[1])
        self.assertEqual(self.loan.email_messages.filter(event_type="manual_email").count(), 1)
        body["message"] = "Different body"
        self.assertEqual(self.client.post(f"/api/loans/{self.loan.pk}/send_email/", body, format="json").status_code, 400)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post(f"/api/loans/{self.loan.pk}/send_email/", body, format="json").status_code, 403)

    def test_manual_requires_request_id_and_rejects_header_injection(self):
        for body in ({"subject": "Hello", "message": "Hello"},
                     {"requestId": str(uuid.uuid4()), "subject": "Hello\nBcc: bad", "message": "Hello"}):
            self.assertEqual(self.client.post(f"/api/loans/{self.loan.pk}/send_email/", body, format="json").status_code, 400)

    def test_all_templates_render_escaped_with_calendar_dates_unchanged(self):
        row = self.one_message()
        for template in COPY:
            with self.subTest(template=template):
                row.template_key, row.event_type = template, template.split(".")[0]
                row.payload.update(due_date="1999-12-31", manual_subject="Manual", manual_message="<script>X</script>")
                subject, html = render_email(row)
                self.assertNotIn("<script>", html)
                self.assertIn("31 Dec 1999", html)
                self.assertNotIn("{{", html)
                self.assertTrue(subject)

    def test_recipient_zone_uses_event_dst_and_preserves_utc_instant(self):
        row = self.one_message()
        for stamp, expected in (
            ("2026-01-15T22:30:00+00:00", {"Africa/Cairo": "16 Jan 2026 00:30", "Europe/London": "15 Jan 2026 22:30", "America/New_York": "15 Jan 2026 17:30", "Asia/Dubai": "16 Jan 2026 02:30"}),
            ("2026-07-15T22:30:00+00:00", {"Africa/Cairo": "16 Jul 2026 01:30", "Europe/London": "15 Jul 2026 23:30", "America/New_York": "15 Jul 2026 18:30", "Asia/Dubai": "16 Jul 2026 02:30"}),
            ("2026-03-15T12:00:00+00:00", {"Africa/Cairo": "15 Mar 2026 14:00", "Europe/London": "15 Mar 2026 12:00", "America/New_York": "15 Mar 2026 08:00", "Asia/Dubai": "15 Mar 2026 16:00"}),
        ):
            row.payload["requested_at"] = stamp
            for zone, local in expected.items():
                row.recipient_timezone = zone
                self.assertIn(local, render_email(row)[1])
                self.assertEqual(row.payload["requested_at"], stamp)

    def test_scheduler_due_today_then_odd_overdue_and_no_backlog(self):
        self.reminder_loan()
        for offset in range(8):
            counts = schedule_reminders(now=NOW + timedelta(days=offset))
            self.assertEqual(counts["queued"], int(offset in (0, 1, 3, 5, 7)))
        self.assertEqual(self.loan.email_messages.filter(message_kind="reminder").count(), 5)
        # Restarting on day 11 creates only day 11, never missed day 9.
        schedule_reminders(now=NOW + timedelta(days=11))
        self.assertEqual(set(self.loan.email_messages.filter(message_kind="reminder").values_list("payload__days_overdue", flat=True)), {0, 1, 3, 5, 7, 11})

    def test_scheduler_09_local_for_all_zones_and_dst_boundaries(self):
        self.reminder_loan()
        for zone in ("Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"):
            self.set_zone(zone)
            for day in (date(2028, 1, 15), date(2028, 3, 12), date(2028, 3, 26), date(2028, 4, 28),
                        date(2028, 7, 15), date(2028, 10, 29), date(2028, 11, 5)):
                with self.subTest(zone=zone, day=day):
                    Loan._base_manager.filter(pk=self.loan.pk).update(due_date=day, email_deadline_revision=self.loan.email_deadline_revision + 1)
                    self.loan.refresh_from_db()
                    at, _ = local_reminder_window(day, zone)
                    self.assertEqual(schedule_reminders(now=at - timedelta(seconds=1))["queued"], 0)
                    self.assertEqual(schedule_reminders(now=at)["queued"], 1)
                    self.assertEqual(schedule_reminders(now=at + timedelta(minutes=1))["queued"], 0)

    def test_scheduler_includes_overdue_status(self):
        self.reminder_loan(due=date(2028, 7, 14), status="overdue")
        self.assertEqual(schedule_reminders(now=NOW)["queued"], 1)

    def test_scheduler_missing_zone_is_reported_and_does_not_guess(self):
        self.reminder_loan()
        self.set_zone(None)
        counts = schedule_reminders(now=NOW)
        self.assertEqual(counts["missing_timezone"], 1)
        self.assertEqual(counts["queued"], 0)

    def test_due_change_and_return_cancel_pending_reminders(self):
        self.reminder_loan()
        schedule_reminders(now=NOW)
        row = self.loan.email_messages.get(message_kind="reminder")
        self.loan.delivery_days = 2
        self.loan.save()
        row.refresh_from_db()
        self.assertEqual(row.status, "cancelled")
        self.loan.status, self.loan.returned_at = "returned", NOW
        self.loan.return_condition = "good"
        self.loan.save()
        self.assertEqual(schedule_reminders(now=NOW + timedelta(days=1))["queued"], 0)

    def test_timezone_change_replans_before_09_without_duplicate(self):
        self.reminder_loan()
        self.assertEqual(schedule_reminders(now=NOW)["queued"], 1)
        row = self.one_message("due_today")
        self.set_zone("America/New_York")  # 08:00, so wait for 13:00 UTC.
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        self.assertEqual(worker.process(claim, now=NOW), "pending")
        row.refresh_from_db()
        self.assertEqual(row.available_at, NOW + timedelta(hours=1))
        self.assertEqual(len(fake.sent), 0)
        self.assertEqual(schedule_reminders(now=NOW + timedelta(hours=1))["queued"], 0)
        self.assertEqual(worker.run_once(now=NOW + timedelta(hours=1)), ["accepted"])
        self.set_zone("Asia/Dubai")
        self.assertEqual(schedule_reminders(now=NOW + timedelta(hours=2))["queued"], 0)

    def test_worker_acceptance_is_not_retried_and_has_attempt_history(self):
        row = self.one_message()
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(worker.run_once(now=NOW), [])
        row.refresh_from_db()
        self.assertEqual(row.attempts.get().result, "accepted")
        self.assertIsNotNone(row.accepted_at)
        self.assertIsNone(row.lease_token)
        self.assertEqual(len(fake.sent), 1)
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)

    def test_worker_temporary_failure_honors_retry_after_and_max_attempts(self):
        row = self.one_message()
        worker, _ = self.worker(GraphResult("retryable_failure", 429, "graph_temporary_rejection", 600), GraphResult("accepted", 202))
        self.assertEqual(worker.run_once(now=NOW), ["retry_wait"])
        row.refresh_from_db()
        self.assertEqual(row.available_at, NOW + timedelta(seconds=600))
        self.assertEqual(worker.run_once(now=NOW + timedelta(seconds=599)), [])
        self.assertEqual(worker.run_once(now=NOW + timedelta(seconds=600)), ["accepted"])
        self.assertEqual(list(row.attempts.order_by("attempt_number").values_list("attempt_number", flat=True)), [1, 2])

    def test_retry_budget_is_bounded_for_repeated_5xx(self):
        row = self.one_message()
        worker, fake = self.worker(*[GraphResult("retryable_failure", 503, "graph_temporary_rejection")] * 5)
        at = NOW
        for _ in range(5):
            worker.run_once(now=at)
            row.refresh_from_db()
            at = row.available_at
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempts.count(), 5)
        self.assertEqual(len(fake.sent), 5)
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)

    def test_old_day_reminder_is_cancelled_after_downtime(self):
        self.reminder_loan()
        schedule_reminders(now=NOW)
        row = self.one_message("due_today")
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW + timedelta(days=1)), ["cancelled"])
        self.assertFalse(fake.sent)
        row.refresh_from_db()
        self.assertEqual(row.error_code, "reminder_day_expired")

    def test_timezone_travel_cannot_recreate_an_earlier_accepted_day(self):
        self.reminder_loan(due=date(2028, 7, 14))
        schedule_reminders(now=NOW)
        row = self.one_message("overdue")
        worker, _ = self.worker()
        worker.run_once(now=NOW)
        self.set_zone("America/New_York")
        self.assertEqual(schedule_reminders(now=NOW + timedelta(hours=1))["queued"], 0)
        self.assertEqual(row.attempts.count(), 1)

    def test_notify_available_moves_to_history_only_after_acceptance(self):
        self.confirm()
        watcher = self.new_loan("notify-accept", loan_type="notify")
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        row = watcher.email_messages.get(event_type="notify_available")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        row.available_at = NOW
        row.save()
        worker, _ = self.worker()
        worker.run_once(now=NOW)
        row.refresh_from_db()
        watcher.refresh_from_db()
        self.assertEqual(row.status, "accepted")
        self.assertEqual(watcher.status, "notify")

    def test_production_shadow_cannot_become_pending_while_graph_is_off(self):
        with override_settings(LIBRARY_ISOLATED_TESTS=False, LIBRARY_GRAPH_SEND_ENABLED=False):
            row = self.new_loan("shadow-graph-off").email_messages.get(recipient_role="student")
        self.assertEqual(row.status, "blocked")
        self.assertEqual(row.error_code, "n8n_handoff_required")

    def test_worker_uncertain_and_transport_exception_never_retry(self):
        row = self.one_message()
        worker, fake = self.worker(TimeoutError("SECRET RAW PROVIDER RESPONSE"))
        self.assertEqual(worker.run_once(now=NOW), ["uncertain"])
        self.assertEqual(worker.run_once(now=NOW + timedelta(days=1)), [])
        row.refresh_from_db()
        self.assertNotIn("SECRET", row.error_summary)
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)

    def test_expired_claim_is_safe_but_expired_submission_is_uncertain(self):
        row = self.one_message()
        worker, _ = self.worker()
        first = worker.claim(now=NOW)
        worker.recover_expired(now=NOW + timedelta(seconds=181))
        second = worker.claim(now=NOW + timedelta(seconds=182))
        self.assertNotEqual(first[1], second[1])
        self.assertEqual(worker.process(first, now=NOW + timedelta(seconds=183)), "fenced")
        row.refresh_from_db()
        row.status = "submitting"
        row.save()
        EmailAttempt.objects.create(message=row, attempt_number=1, result="started", lease_token=row.lease_token,
                                    started_at=NOW + timedelta(seconds=182))
        worker.recover_expired(now=NOW + timedelta(seconds=400))
        row.refresh_from_db()
        self.assertEqual(row.status, "uncertain")
        self.assertEqual(row.attempts.get().result, "uncertain")

    def test_worker_checks_return_at_submission_boundary(self):
        self.reminder_loan()
        schedule_reminders(now=NOW)
        row = self.one_message("due_today")
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        self.loan.status, self.loan.returned_at = "returned", NOW
        self.loan.return_condition = "good"
        self.loan.save()
        self.assertEqual(worker.process(claim, now=NOW), "fenced")
        self.assertEqual(fake.sent, [])

    def test_worker_definitive_failure_manual_retry_requires_staff(self):
        row = self.one_message()
        worker, _ = self.worker(GraphResult("permanent_failure", 403, "graph_permanent_rejection"))
        self.assertEqual(worker.run_once(now=NOW), ["failed"])
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.student)
        self.assertEqual(retry_message(row.pk, actor=self.admin).status, "pending")

    def test_default_flags_disable_enqueue_worker_scheduler_and_live_graph(self):
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=False, LIBRARY_EMAIL_WORKER_ENABLED=False,
                               LIBRARY_EMAIL_SCHEDULER_ENABLED=False, LIBRARY_GRAPH_SEND_ENABLED=False):
            count = EmailOutbox.objects.count()
            self.new_loan("disabled")
            self.assertEqual(EmailOutbox.objects.count(), count)
            with self.assertRaises(ImproperlyConfigured):
                EmailWorker(client=FakeGraph())
            self.assertTrue(schedule_reminders()["disabled"])
            with self.assertRaises(ImproperlyConfigured):
                GraphClient().send(self.one_message(), "Subject", "<p>Body</p>")

    def test_live_handoff_requires_every_activation_gate(self):
        self.assertFalse(routes_to_django("loan_submitted"))
        with override_settings(LIBRARY_EMAIL_PROVIDER="graph", LIBRARY_GRAPH_SEND_ENABLED=True, LIBRARY_GRAPH_CREDENTIALS_APPROVED=True,
            LIBRARY_GRAPH_TENANT_ID="synthetic", LIBRARY_GRAPH_CLIENT_ID="synthetic",
            LIBRARY_GRAPH_CLIENT_SECRET="synthetic", LIBRARY_GRAPH_SENDER="sender@example.test"):
            self.assertTrue(routes_to_django("loan_submitted"))
            self.assertFalse(routes_to_django("not-owned"))


@override_settings(LIBRARY_GRAPH_TENANT_ID="synthetic-tenant", LIBRARY_GRAPH_CLIENT_ID="synthetic-client",
    LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("student@example.test",),
    LIBRARY_GRAPH_CLIENT_SECRET="synthetic-secret", LIBRARY_GRAPH_SENDER="library@example.test", LIBRARY_GRAPH_REPLY_TO="help@example.test")
class GraphTransportTests(TestCase):
    def message(self):
        return EmailOutbox(id=uuid.uuid4(), event_type="loan_submitted", recipient_email="student@example.test")

    def test_auth_cache_html_sender_reply_to_and_202(self):
        seen = []
        def transport(req):
            seen.append(req)
            if "/token" in req.full_url:
                self.assertIn(b"scope=https%3A%2F%2Fgraph.microsoft.com%2F.default", req.data)
                return 200, {}, b'{"access_token":"synthetic-token","expires_in":3600}'
            payload = json.loads(req.data)
            self.assertEqual(payload["message"]["body"]["contentType"], "HTML")
            self.assertIn("replyTo", payload["message"])
            self.assertIn("/users/library%40example.test/sendMail", req.full_url)
            return 202, {"request-id": "abc-123"}, b""
        client = GraphClient(transport)
        for _ in range(2):
            self.assertEqual(client.send(self.message(), "Hello", "<p>HTML</p>").outcome, "accepted")
        self.assertEqual(len(seen), 3)

    def test_http_results_retry_or_uncertain_without_hidden_resubmission(self):
        for status, outcome in ((429, "retryable_failure"), (500, "retryable_failure"), (503, "retryable_failure"),
                                (400, "permanent_failure"), (403, "permanent_failure"), (408, "uncertain"), (200, "uncertain")):
            calls = []
            def transport(req):
                calls.append(req.full_url)
                if "/token" in req.full_url:
                    return 200, {}, b'{"access_token":"synthetic","expires_in":3600}'
                return status, {"Retry-After": "75"}, b"never store this"
            result = GraphClient(transport).send(self.message(), "Hello", "<p>Body</p>")
            self.assertEqual(result.outcome, outcome)
            self.assertEqual(len(calls), 2)
            if status in (429, 500, 503):
                self.assertEqual(result.retry_after, 75)

    def test_token_renewal_and_submission_timeout(self):
        calls = []
        def transport(req):
            calls.append(req.full_url)
            if "/token" in req.full_url:
                return 200, {}, b'{"access_token":"synthetic","expires_in":3600}'
            raise TimeoutError("raw sensitive error")
        client = GraphClient(transport)
        self.assertEqual(client.send(self.message(), "Hello", "<p>Body</p>").outcome, "uncertain")
        client._expires = 0
        client.send(self.message(), "Hello", "<p>Body</p>")
        self.assertEqual(sum("/token" in url for url in calls), 2)

    def test_auth_failure_is_safe_to_retry_and_retry_after_date_supported(self):
        result = GraphClient(lambda req: (503, {"Retry-After": "30"}, b"secret")).send(self.message(), "Hello", "Body")
        self.assertEqual(result.outcome, "retryable_failure")
        self.assertEqual(result.retry_after, 30)
        self.assertEqual(retry_after_seconds("Sat, 15 Jul 2028 12:01:00 GMT", NOW), 60)


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL; SQLite does not prove locking safety.")
@override_settings(LIBRARY_EMAIL_WORKER_ENABLED=True, LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=True,
                   LIBRARY_EMAIL_OWNED_EVENTS=tuple(EVENTS))
class PostgresEmailConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("concurrent", email="concurrent@example.test")
        UserProfile.objects.create(user=self.user, time_zone="Europe/London", time_zone_source="manual", time_zone_updated_at=NOW)

    def row(self):
        return EmailOutbox.objects.create(event_id=uuid.uuid4(), event_type="loan_submitted", message_kind="event",
            recipient=self.user, recipient_key=f"user:{self.user.pk}", recipient_email=self.user.email,
            recipient_role="student", recipient_timezone="Europe/London", template_key="loan_submitted.student",
            idempotency_key=str(uuid.uuid4()), payload={"student_name": "Synthetic", "book_title": "Synthetic"},
            status="pending", available_at=NOW)

    def test_two_workers_claim_different_messages(self):
        self.row()
        self.row()
        barrier = Barrier(2)
        def claim():
            try:
                barrier.wait(timeout=10)
                return EmailWorker(client=FakeGraph()).claim(now=NOW)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(len({entry[0] for entry in result}), 2)
        self.assertEqual(EmailOutbox.objects.filter(status="claimed").count(), 2)

    def test_skip_locked_does_not_wait_for_another_claim(self):
        first, second = self.row(), self.row()
        held, release = Event(), Event()
        def hold_lock():
            try:
                with transaction.atomic():
                    EmailOutbox.objects.select_for_update().get(pk=first.pk)
                    held.set()
                    release.wait(timeout=10)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(hold_lock)
            self.assertTrue(held.wait(timeout=10))
            try:
                claimed = EmailWorker(client=FakeGraph()).claim(now=NOW)
                self.assertEqual(claimed[0], second.pk)
            finally:
                release.set()
                future.result(timeout=10)

    def test_concurrent_idempotency_has_one_row(self):
        from .email_events import enqueue
        barrier = Barrier(2)
        event_id = uuid.uuid4()
        def insert():
            try:
                with transaction.atomic():
                    barrier.wait(timeout=10)
                    return enqueue(event="loan_submitted", event_id=event_id, user=self.user, email=self.user.email,
                        role="student", payload={"student_name": "Synthetic"}, logical_key="concurrent-same-key").pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: insert(), range(2)))
        self.assertEqual(result[0], result[1])
        self.assertEqual(EmailOutbox.objects.filter(idempotency_key="concurrent-same-key").count(), 1)

    @override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=True, LIBRARY_EMAIL_SCHEDULER_ENABLED=True)
    def test_concurrent_schedulers_create_one_local_day_message(self):
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=False):
            category = Category.objects.create(name="Concurrent", slug="concurrent")
            resource = Resource.objects.create(id="parallel-book", title="Synthetic", author="Synthetic", category=category)
            copy = BookCopy.objects.create(resource=resource, accession_number="PAR-1")
            loan = Loan.objects.create(id="parallel-loan", borrower=self.user, borrower_email=self.user.email,
                                       book_copy=copy, status="borrowed")
            Loan._base_manager.filter(pk=loan.pk).update(due_date=NOW.date())
        barrier = Barrier(2)
        def schedule():
            try:
                barrier.wait(timeout=10)
                return schedule_reminders(now=NOW)["queued"]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: schedule(), range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(loan.email_messages.count(), 1)
