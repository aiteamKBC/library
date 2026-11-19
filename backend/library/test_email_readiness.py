"""Phase 4A synthetic tests. No live transport, production data or cutover."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
import json
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.db import connection, connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings

from .email_models import EmailOutbox, EmailAttempt
from .email_policy import recipient_allowed, require_live_graph
from .email_scheduler import schedule_reminders
from .email_worker import EmailWorker, retry_message
from .graph_client import GraphClient
from .models import Loan, UserProfile
from .notification_timing import local_reminder_window
from .test_email_system import EmailSystemTests, FakeGraph, NOW
from .tests import LoanDeliveryPeriodTests

UTC = timezone.utc


class ReadinessFixture:
    setUp = EmailSystemTests.setUp
    new_loan = EmailSystemTests.new_loan
    confirm = EmailSystemTests.confirm
    reminder_loan = EmailSystemTests.reminder_loan
    one_message = EmailSystemTests.one_message
    set_zone = EmailSystemTests.set_zone
    worker = EmailSystemTests.worker

    def cancelled_for_timezone(self, *, day=None, destination="America/New_York"):
        self.confirm()
        day = day or self.loan.due_date
        if day != self.loan.due_date:
            Loan._base_manager.filter(pk=self.loan.pk).update(due_date=day)
            self.loan.refresh_from_db()
        self.set_zone("Pacific/Auckland")
        early, _ = local_reminder_window(day, "Pacific/Auckland")
        self.assertEqual(schedule_reminders(now=early)["queued"], 1)
        row = self.loan.email_messages.get(message_kind="reminder", deadline_revision=self.loan.email_deadline_revision)
        EmailOutbox.objects.exclude(pk=row.pk).filter(status__in=("blocked", "pending", "retry_wait")).update(status="cancelled")
        self.set_zone(destination)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=early), ["cancelled"])
        row.refresh_from_db()
        self.assertEqual(row.error_code, "reminder_day_expired")
        self.assertEqual(row.attempts_count, 0)
        self.assertFalse(row.attempts.exists())
        self.assertFalse(fake.sent)
        eligible, _ = local_reminder_window(day, destination)
        return row, eligible


class SchedulerReadinessTests(ReadinessFixture, TestCase):
    def test_travel_reactivates_same_unattempted_row_and_sends_once(self):
        row, at = self.cancelled_for_timezone()
        key, pk, event_id = row.idempotency_key, row.pk, row.event_id
        self.assertEqual(schedule_reminders(now=at)["queued"], 1)
        row.refresh_from_db()
        self.assertEqual((row.pk, row.idempotency_key, row.event_id), (pk, key, event_id))
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.recipient_timezone, "America/New_York")
        self.assertEqual(row.available_at, at)
        self.assertEqual(schedule_reminders(now=at)["queued"], 0)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=at), ["accepted"])
        self.assertEqual(schedule_reminders(now=at + timedelta(minutes=1))["queued"], 0)
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(EmailOutbox.objects.filter(idempotency_key=key).count(), 1)

    def test_reactivation_uses_dst_on_the_new_local_day(self):
        # Real transition dates, including countries changing clocks on different days.
        cases = ((date(2028, 3, 12), "America/New_York", 13),
                 (date(2028, 3, 26), "Europe/London", 8),
                 (date(2028, 4, 28), "Africa/Cairo", 6),
                 (date(2028, 10, 29), "Europe/London", 9),
                 (date(2028, 11, 5), "America/New_York", 14))
        # One loan per case, so an accepted earlier revision cannot mask a result.
        for index, (day, zone, hour) in enumerate(cases):
            with self.subTest(day=day, zone=zone):
                if index:
                    self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
                    self.loan.save()
                    self.loan = self.new_loan(f"dst-{index}")
                row, at = self.cancelled_for_timezone(day=day, destination=zone)
                self.assertEqual(at.hour, hour)
                self.assertEqual(schedule_reminders(now=at - timedelta(seconds=1))["queued"], 0)
                self.assertEqual(schedule_reminders(now=at)["queued"], 1)
                row.refresh_from_db()
                self.assertEqual(row.available_at, at)
                self.assertEqual(row.due_date_snapshot, day)
                self.assertEqual(row.attempts_count, 0)

    def test_deadline_change_gets_a_new_revision_and_never_revives_the_old_one(self):
        row, at = self.cancelled_for_timezone()
        old_due, revision = self.loan.due_date, self.loan.email_deadline_revision
        self.loan.delivery_days = 1
        self.loan.save()
        self.assertEqual(self.loan.due_date, old_due + timedelta(days=1))
        self.assertEqual(self.loan.email_deadline_revision, revision + 1)
        self.assertEqual(schedule_reminders(now=at)["queued"], 0)
        later, _ = local_reminder_window(self.loan.due_date, "America/New_York")
        self.assertEqual(schedule_reminders(now=later)["queued"], 1)
        new = self.loan.email_messages.get(message_kind="reminder", deadline_revision=revision + 1)
        row.refresh_from_db()
        self.assertEqual(row.status, "cancelled")
        self.assertNotEqual(new.idempotency_key, row.idempotency_key)
        # Restoring the old calendar date still has a NEW revision and key.
        self.loan.delivery_days = 0
        self.loan.save()
        self.assertEqual(self.loan.email_deadline_revision, revision + 2)
        self.assertEqual(self.loan.due_date, old_due)
        self.assertEqual(schedule_reminders(now=at)["queued"], 1)
        self.assertEqual(self.loan.email_messages.filter(message_kind="reminder").count(), 3)

    def test_return_prevents_reactivation(self):
        row, at = self.cancelled_for_timezone()
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        self.assertEqual(schedule_reminders(now=at)["queued"], 0)
        row.refresh_from_db()
        self.assertEqual(row.status, "cancelled")

    def test_no_reactivation_after_any_attempt_even_if_counter_was_zero(self):
        row, at = self.cancelled_for_timezone()
        for index, result in enumerate(("started", "accepted", "uncertain", "retryable_failure", "permanent_failure"), 1):
            with self.subTest(result=result):
                EmailAttempt.objects.create(message=row, attempt_number=index, result=result,
                    started_at=at - timedelta(hours=1), finished_at=None if result == "started" else at)
                self.assertEqual(schedule_reminders(now=at)["queued"], 0)
                row.refresh_from_db()
                self.assertEqual(row.status, "cancelled")

    def test_only_timezone_cancellation_can_be_revived(self):
        row, at = self.cancelled_for_timezone()
        for code in ("loan_changed", "stale_reminder", "source_deleted", "manual_cancel"):
            row.error_code = code
            row.save()
            self.assertEqual(schedule_reminders(now=at)["queued"], 0)
            row.refresh_from_db()
            self.assertEqual(row.status, "cancelled")

    def test_accepted_uncertain_inflight_failed_and_shadow_rows_are_not_reopened(self):
        row, at = self.cancelled_for_timezone()
        for state in ("accepted", "uncertain", "claimed", "submitting", "failed", "blocked"):
            with self.subTest(state=state):
                row.status = state
                row.accepted_at = at if state == "accepted" else None
                row.lease_token = uuid.uuid4() if state in ("claimed", "submitting") else None
                row.lease_expires_at = at + timedelta(minutes=3) if row.lease_token else None
                row.worker_id = "other-worker" if row.lease_token else ""
                row.save()
                self.assertEqual(schedule_reminders(now=at)["queued"], 0)
                row.refresh_from_db()
                self.assertEqual(row.status, state)

    def test_revoked_ownership_cannot_reactivate_a_cancelled_message(self):
        row, at = self.cancelled_for_timezone()
        with override_settings(LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=False):
            self.assertEqual(schedule_reminders(now=at)["queued"], 0)
        row.refresh_from_db()
        self.assertEqual(row.status, "cancelled")


class AllowlistWorkerTests(ReadinessFixture, TestCase):
    def test_empty_allowlist_blocks_before_fake_client_and_before_attempt(self):
        row = self.one_message()
        worker, fake = self.worker()
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            self.assertEqual(worker.run_once(now=NOW), ["blocked"])
        row.refresh_from_db()
        self.assertEqual(row.error_code, "recipient_not_allowlisted")
        self.assertEqual(row.recipient_email, self.student.email)
        self.assertFalse(row.attempts.exists())
        self.assertFalse(fake.sent)

    def test_address_must_match_it_cannot_be_redirected_to_a_test_mailbox(self):
        row = self.one_message()
        worker, fake = self.worker()
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("test-inbox@example.test",)):
            self.assertEqual(worker.run_once(now=NOW), ["blocked"])
        row.refresh_from_db()
        self.assertEqual(row.recipient_email, "student@example.test")
        self.assertFalse(fake.sent)

    def test_revocation_between_claim_and_submit_is_checked(self):
        row = self.one_message()
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            self.assertEqual(worker.process(claim, now=NOW), "blocked")
        self.assertFalse(fake.sent)
        self.assertFalse(row.attempts.exists())

    def test_explicit_staff_retry_after_authorization_sends_exactly_once(self):
        row = self.one_message()
        worker, fake = self.worker()
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            worker.run_once(now=NOW)
            with self.assertRaises(ValidationError):
                retry_message(row.pk, actor=self.admin)
        retry_message(row.pk, actor=self.admin)
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(worker.run_once(now=NOW), [])
        self.assertEqual(len(fake.sent), 1)


@override_settings(LIBRARY_GRAPH_TENANT_ID="synthetic", LIBRARY_GRAPH_CLIENT_ID="synthetic",
    LIBRARY_GRAPH_CLIENT_SECRET="synthetic", LIBRARY_GRAPH_SENDER="sender@example.test", LIBRARY_GRAPH_REPLY_TO="")
class AllowlistTransportTests(SimpleTestCase):
    def message(self, address="student@example.test"):
        return EmailOutbox(id=uuid.uuid4(), event_type="loan_submitted", recipient_email=address)

    def test_empty_allowlist_rejects_before_even_token_acquisition(self):
        calls = []
        client = GraphClient(lambda request: calls.append(request))
        self.assertEqual(client.send(self.message(), "Subject", "Body").code, "recipient_not_allowlisted")
        self.assertEqual(calls, [])

    def test_no_wildcards_domains_display_names_or_malformed_configuration(self):
        for value in ((), ("*@example.test",), ("example.test",), ("Name <student@example.test>",),
                      ("student@example.test\nBcc:other@example.test",), "student@example.test",
                      ("student@example.test", "not-an-email")):
            with self.subTest(value=value), override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=value):
                self.assertFalse(recipient_allowed("student@example.test"))

    def test_exact_case_insensitive_match_preserves_original_recipient(self):
        seen = []
        def transport(request):
            seen.append(request)
            if "/token" in request.full_url:
                return 200, {}, b'{"access_token":"synthetic","expires_in":3600}'
            return 202, {}, b""
        original = "Student@Example.Test"
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=("student@example.test",)):
            client = GraphClient(transport)
            self.assertEqual(client.send(self.message(original), "Subject", "Body").outcome, "accepted")
            body = json.loads(seen[-1].data)
            self.assertEqual(body["message"]["toRecipients"][0]["emailAddress"]["address"], original)
            count = len(seen)
            self.assertEqual(client.send(self.message("other@example.test"), "Subject", "Body").code, "recipient_not_allowlisted")
            self.assertEqual(len(seen), count)  # Cached token does not bypass guard.

    def test_all_live_flags_still_need_nonempty_allowlist(self):
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=True, LIBRARY_EMAIL_WORKER_ENABLED=True,
            LIBRARY_GRAPH_SEND_ENABLED=True, LIBRARY_GRAPH_CREDENTIALS_APPROVED=True,
            LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=True, LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            with self.assertRaises(ImproperlyConfigured):
                require_live_graph()

    def test_flags_and_allowlist_are_closed_by_default(self):
        for name in ("LIBRARY_EMAIL_ENQUEUE_ENABLED", "LIBRARY_EMAIL_WORKER_ENABLED",
                     "LIBRARY_EMAIL_SCHEDULER_ENABLED", "LIBRARY_GRAPH_SEND_ENABLED",
                     "LIBRARY_GRAPH_CREDENTIALS_APPROVED", "LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED"):
            self.assertFalse(getattr(settings, name))
        self.assertEqual(settings.LIBRARY_EMAIL_RECIPIENT_ALLOWLIST, ())


@override_settings(LIBRARY_LONDON_CUTOVER_AT="", LIBRARY_USER_LOCAL_POLICY_ENABLED=False)
class CutoverReadinessTests(TestCase):
    setUp = LoanDeliveryPeriodTests.setUp
    approve = LoanDeliveryPeriodTests.approve
    confirmed_at = NOW

    def test_disabled_user_local_keeps_cairo_without_inventing_a_london_cutover(self):
        result = self.approve(0)
        self.assertEqual(result.status_code, 200, result.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.calculation_policy, "cairo_v1")
        self.assertEqual(self.loan.calculation_timezone, "Africa/Cairo")
        self.assertEqual(self.loan.due_date, date(2028, 8, 14))
        self.assertEqual(self.loan.approved_at, NOW)

    def test_existing_snapshot_and_due_date_survive_notes_same_delivery_and_checkout(self):
        anchor = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)
        Loan._base_manager.filter(pk=self.loan.pk).update(status="approved", approved_at=anchor,
            calculation_policy="cairo_v1", calculation_timezone="Africa/Cairo", operational_timezone="Europe/London",
            confirmation_local_date=date(2026, 7, 16), due_date=date(2026, 9, 1), delivery_days=2)
        self.loan.refresh_from_db()
        self.loan.notes = "Synthetic note"
        self.loan.save(update_fields={"notes"})
        self.loan.save(update_fields={"delivery_days"})
        self.loan.status = "borrowed"
        self.loan.save(update_fields={"status"})
        self.assertEqual(self.loan.due_date, date(2026, 9, 1))
        self.assertEqual(self.loan.approved_at, anchor)
        self.assertEqual(self.loan.email_deadline_revision, 0)

    def test_frozen_snapshot_delivery_edit_needs_no_cutover_and_keeps_original_basis(self):
        anchor = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)
        Loan._base_manager.filter(pk=self.loan.pk).update(status="borrowed", approved_at=anchor, borrowed_at=anchor,
            calculation_policy="cairo_v1", calculation_timezone="Africa/Cairo", operational_timezone="Europe/London",
            confirmation_local_date=date(2026, 7, 16), due_date=date(2026, 8, 17), delivery_days=2)
        self.loan.refresh_from_db()
        self.loan.delivery_days = 5
        self.loan.save(update_fields={"delivery_days"})
        self.assertEqual(self.loan.due_date, date(2026, 8, 20))
        self.assertEqual(self.loan.approved_at, anchor)
        self.assertEqual(self.loan.email_deadline_revision, 1)

    def test_user_local_after_an_explicit_test_cutover_does_not_require_london_cutover(self):
        UserProfile.objects.create(user=self.student, time_zone="Asia/Dubai", time_zone_source="manual", time_zone_updated_at=NOW)
        with override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=True, LIBRARY_USER_LOCAL_CUTOVER_AT="2028-01-01T00:00:00Z"):
            self.assertEqual(self.approve(0).status_code, 200)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.calculation_policy, "user_local_v1")
        self.assertEqual(self.loan.calculation_timezone, "Asia/Dubai")

    def test_first_policy_rejects_naive_or_missing_confirmation_as_validation_error(self):
        with override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=True, LIBRARY_USER_LOCAL_CUTOVER_AT="2028-01-01T00:00:00Z"):
            for stamp in (None, "2028-01-01", datetime(2028, 1, 1)):
                with self.assertRaises(ValidationError):
                    self.loan.first_confirmation_policy(stamp)


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL row locking.")
class ConcurrentReminderReadinessTests(ReadinessFixture, TransactionTestCase):
    def test_two_schedulers_reactivate_one_row_then_only_one_worker_can_claim_it(self):
        row, at = self.cancelled_for_timezone()
        barrier = Barrier(2)
        def schedule():
            try:
                barrier.wait(timeout=10)
                return schedule_reminders(now=at)["queued"]
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: schedule(), range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(EmailOutbox.objects.filter(idempotency_key=row.idempotency_key).count(), 1)
        barrier = Barrier(2)
        def claim():
            try:
                barrier.wait(timeout=10)
                return EmailWorker(client=FakeGraph()).claim(now=at)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(item is not None for item in claims), 1)
