"""Notify -> Borrow races, using synthetic PostgreSQL and fake Gmail only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from . import test_email_system as fixtures
from .email_events import emit_loan
from .email_models import EmailOutbox
from .email_transport import DeliveryResult
from .email_worker import EmailWorker, retry_message
from .models import Loan

NOW = fixtures.NOW


class FakeGmail:
    provider = "gmail"

    def __init__(self, result=None, entered=None, release=None):
        self.result = result or DeliveryResult("accepted", 200, request_id="gmail:synthetic")
        self.entered, self.release = entered, release
        self.sent = []

    def send(self, row, subject, html):
        self.sent.append(row.pk)
        if self.entered is not None:
            self.entered.set()
            if not self.release.wait(timeout=15):
                raise TimeoutError("Synthetic test did not release the provider")
        return self.result


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL locks and committed transactions.")
class NotifyConversionTests(TransactionTestCase):
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm

    def setUp(self):
        fixtures.EmailSystemTests.setUp(self)
        self.confirm()
        self.watcher = self.new_loan("notify-accept", loan_type="notify")
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        self.row = self.watcher.email_messages.get(event_type="notify_available")
        EmailOutbox.objects.exclude(pk=self.row.pk).update(status="cancelled")
        EmailOutbox.objects.filter(pk=self.row.pk).update(available_at=NOW)
        self.row.refresh_from_db()

    def convert_api(self, expected=200):
        response = self.client.patch(f"/api/loans/{self.watcher.pk}/", {"loanType": "borrow"}, format="json")
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def assert_borrow_queue(self):
        self.watcher.refresh_from_db()
        self.assertEqual((self.watcher.loan_type, self.watcher.status), ("borrow", "requested"))

    def assert_cancelled(self):
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.error_code), ("cancelled", "notify_request_converted"))
        self.assertIsNone(self.row.lease_token)
        self.assertIsNone(self.row.lease_expires_at)
        self.assertEqual(self.row.worker_id, "")

    def test_move_to_queue_cancels_pending_notify_events_without_touching_identity(self):
        registered = self.watcher.email_messages.get(event_type="notify_registered")
        EmailOutbox.objects.filter(pk=registered.pk).update(status="pending", available_at=NOW)
        original = (self.row.pk, self.row.event_id, self.row.idempotency_key)
        self.convert_api()
        self.assert_borrow_queue()
        self.assert_cancelled()
        registered.refresh_from_db()
        self.assertEqual(registered.status, "cancelled")
        self.assertEqual((self.row.pk, self.row.event_id, self.row.idempotency_key), original)
        fake = FakeGmail()
        self.assertEqual(EmailWorker(client=fake).run_once(now=NOW), [])
        self.assertEqual(fake.sent, [])
        self.assertFalse(self.row.attempts.exists())

    def test_conversion_after_claim_fences_old_worker(self):
        fake = FakeGmail()
        worker = EmailWorker(client=fake)
        claim = worker.claim(now=NOW)
        self.convert_api()
        self.assert_cancelled()
        self.assertEqual(worker.process(claim, now=NOW), "fenced")
        self.assertEqual(fake.sent, [])
        self.assertFalse(self.row.attempts.exists())
        self.assert_borrow_queue()

    def test_old_outbox_rows_are_rejected_before_provider_and_manual_retry(self):
        self.convert_api()
        # Simulate a persisted pre-fix row, bypassing only the producer cleanup.
        for event in ("notify_available", "notify_registered"):
            for state in ("pending", "retry_wait"):
                with self.subTest(event=event, state=state):
                    EmailOutbox.objects.filter(pk=self.row.pk).update(
                        event_type=event, status=state, error_code="", available_at=NOW)
                    fake = FakeGmail()
                    self.assertEqual(EmailWorker(client=fake).run_once(now=NOW), ["cancelled"])
                    self.assert_cancelled()
                    self.assertEqual(fake.sent, [])
        EmailOutbox.objects.filter(pk=self.row.pk).update(status="failed", error_code="gmail_permanent_rejection")
        with self.assertRaises(ValidationError):
            retry_message(self.row.pk, actor=self.admin)
        self.assertFalse(self.row.attempts.exists())
        self.assert_borrow_queue()

    def test_cancelled_notice_cannot_be_revived_by_stale_notify_object(self):
        self.convert_api()
        with transaction.atomic():
            row = emit_loan(self.watcher, "notify_available")[0]
        self.assertEqual(row.pk, self.row.pk)
        self.assert_cancelled()
        self.assertEqual(self.watcher.email_messages.filter(event_type="notify_available").count(), 1)
        self.assert_borrow_queue()

    def test_conversion_cleanup_also_runs_with_enqueue_disabled(self):
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=False):
            self.convert_api()
        self.assert_cancelled()
        self.assert_borrow_queue()

    def test_conversion_and_cancellation_rollback_together(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.watcher.loan_type = "borrow"
                self.watcher.save(update_fields={"loan_type"})
                self.assert_cancelled()
                raise RuntimeError("Synthetic rollback")
        self.watcher.refresh_from_db()
        self.row.refresh_from_db()
        self.assertEqual((self.watcher.loan_type, self.row.status), ("notify", "pending"))

    def test_unsaved_type_change_does_not_cancel_notice(self):
        self.watcher.loan_type = "borrow"
        self.watcher.notes = "Synthetic note"
        self.watcher.save(update_fields={"notes"})
        self.watcher.refresh_from_db()
        self.row.refresh_from_db()
        self.assertEqual((self.watcher.loan_type, self.row.status), ("notify", "pending"))

    def process_in_thread(self, fake):
        try:
            return EmailWorker(client=fake).run_once(now=NOW)
        finally:
            connections.close_all()

    def during_send(self, result):
        entered, release = Event(), Event()
        fake = FakeGmail(result, entered, release)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.process_in_thread, fake)
            try:
                self.assertTrue(entered.wait(timeout=15))
                self.row.refresh_from_db()
                self.assertEqual(self.row.status, "submitting")
                # A separate PostgreSQL connection commits conversion while
                # the fake provider is paused outside the worker transaction.
                self.convert_api()
                self.assert_borrow_queue()
                self.row.refresh_from_db()
                self.assertEqual(self.row.status, "submitting")
            finally:
                release.set()
            outcome = future.result(timeout=15)
        self.assert_borrow_queue()
        self.assertEqual(fake.sent, [self.row.pk])
        self.row.refresh_from_db()
        self.assertEqual(self.row.attempts.count(), 1)
        return outcome, fake

    def test_conversion_during_gmail_acceptance_keeps_borrow_request_active(self):
        outcome, fake = self.during_send(DeliveryResult("accepted", 200, request_id="gmail:synthetic"))
        self.assertEqual(outcome, ["accepted"])
        self.assertEqual(self.row.attempts.get().result, "accepted")
        self.assertEqual(EmailWorker(client=fake).run_once(now=NOW + timedelta(days=1)), [])
        self.assertEqual(len(fake.sent), 1)

    def test_conversion_during_uncertain_send_preserves_history_without_retry(self):
        outcome, fake = self.during_send(DeliveryResult("uncertain", code="gmail_submission_unknown"))
        self.assertEqual(outcome, ["uncertain"])
        self.assertEqual(self.row.attempts.get().result, "uncertain")
        self.assertEqual(EmailWorker(client=fake).run_once(now=NOW + timedelta(days=1)), [])
        with self.assertRaises(ValidationError):
            retry_message(self.row.pk, actor=self.admin)
        self.assertEqual(len(fake.sent), 1)

    def test_conversion_during_definite_rejection_prevents_retry_submission(self):
        outcome, fake = self.during_send(DeliveryResult("retryable_failure", 503, "gmail_temporary_rejection", 60))
        self.assertEqual(outcome, ["retry_wait"])
        self.assertEqual(self.row.attempts.get().result, "retryable_failure")
        self.assertEqual(EmailWorker(client=fake).run_once(now=NOW + timedelta(hours=1)), ["cancelled"])
        self.assert_cancelled()
        self.assertEqual((len(fake.sent), self.row.attempts.count()), (1, 1))

    def test_conversion_after_retryable_attempt_retains_attempt_and_cancels_retry(self):
        fake = FakeGmail(DeliveryResult("retryable_failure", 503, "gmail_temporary_rejection", 60))
        worker = EmailWorker(client=fake)
        self.assertEqual(worker.run_once(now=NOW), ["retry_wait"])
        self.convert_api()
        self.assert_cancelled()
        self.assertEqual(self.row.attempts.get().result, "retryable_failure")
        self.assertEqual(worker.run_once(now=NOW + timedelta(hours=1)), [])
        self.assertEqual(len(fake.sent), 1)
        self.assert_borrow_queue()

    def test_completed_notification_rejects_late_move_instead_of_false_success(self):
        fake = FakeGmail()
        self.assertEqual(EmailWorker(client=fake).run_once(now=NOW), ["accepted"])
        self.watcher.refresh_from_db()
        self.assertEqual((self.watcher.loan_type, self.watcher.status), ("notify", "notify"))
        self.convert_api(expected=400)
        self.watcher.refresh_from_db()
        self.assertEqual((self.watcher.loan_type, self.watcher.status), ("notify", "notify"))
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "accepted")
        self.assertEqual(len(fake.sent), 1)

    def test_unchanged_notify_retry_still_succeeds_and_completes_registration(self):
        fake = FakeGmail(DeliveryResult("retryable_failure", 503, "gmail_temporary_rejection", 60))
        worker = EmailWorker(client=fake)
        self.assertEqual(worker.run_once(now=NOW), ["retry_wait"])
        fake.result = DeliveryResult("accepted", 200, request_id="gmail:synthetic")
        self.assertEqual(worker.run_once(now=NOW + timedelta(hours=1)), ["accepted"])
        self.watcher.refresh_from_db()
        self.assertEqual((self.watcher.loan_type, self.watcher.status), ("notify", "notify"))
        self.assertEqual(self.row.attempts.count(), 2)
