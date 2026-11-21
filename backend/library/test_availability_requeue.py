"""Availability cancellation recovery; synthetic data and fake delivery only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings

from .email_events import emit_loan
from .email_models import EmailAttempt, EmailOutbox
from .models import BookCopy, Loan
from . import test_email_system as fixtures

NOW = fixtures.NOW


class AvailabilityFixture:
    setUp = fixtures.EmailSystemTests.setUp
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm
    worker = fixtures.EmailSystemTests.worker
    set_zone = fixtures.EmailSystemTests.set_zone

    def cancelled_notice(self):
        self.confirm()
        watcher = self.new_loan("notify-accept", loan_type="notify")
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        row = watcher.email_messages.get(event_type="notify_available")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=NOW)
        BookCopy.objects.filter(pk=self.copy.pk).update(status="borrowed")
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["cancelled"])
        row.refresh_from_db()
        self.assertEqual(row.error_code, "availability_changed")
        self.assertFalse(row.attempts.exists())
        self.assertEqual(fake.sent, [])
        BookCopy.objects.filter(pk=self.copy.pk).update(status="available")
        return watcher, row

    def replay(self, watcher):
        with transaction.atomic(), patch("library.email_events.timezone.now", return_value=NOW):
            return emit_loan(watcher, "notify_available")[0]


class AvailabilityRequeueTests(AvailabilityFixture, TestCase):
    def test_next_return_revives_same_notice_and_worker_sends_only_once(self):
        watcher, row = self.cancelled_notice()
        original = (row.pk, row.event_id, row.idempotency_key, row.created_at, row.template_version)
        # A different real loan return, rather than a direct helper invocation.
        second = self.new_loan("second-borrow")
        second.status = "borrowed"
        with patch("library.models.timezone.now", return_value=NOW):
            second.save()
            second.status, second.returned_at, second.return_condition = "returned", NOW, "good"
            second.save()
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.assertEqual((row.pk, row.event_id, row.idempotency_key, row.created_at, row.template_version), original)
        self.assertEqual((row.error_code, row.error_summary, row.attempts_count), ("", "", 0))
        self.assertEqual(watcher.email_messages.filter(event_type="notify_available").count(), 1)
        self.assertEqual(self.replay(watcher).pk, row.pk)
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.replay(watcher)  # Stale caller object cannot revive an accepted notice.
        self.assertEqual(worker.run_once(now=NOW), [])
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(row.attempts.count(), 1)
        watcher.refresh_from_db()
        self.assertEqual(watcher.status, "notify")

    def test_no_revival_if_book_unavailable_or_request_no_longer_waiting(self):
        watcher, row = self.cancelled_notice()
        BookCopy.objects.filter(pk=self.copy.pk).update(status="borrowed")
        self.assertEqual(self.replay(watcher).status, "cancelled")
        BookCopy.objects.filter(pk=self.copy.pk).update(status="available")
        cancelled = Loan.objects.get(pk=watcher.pk)
        cancelled.status = "cancelled"
        cancelled.save()
        self.assertEqual(self.replay(watcher).status, "cancelled")

    def test_revival_rolls_back_with_source_transaction(self):
        watcher, row = self.cancelled_notice()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.assertEqual(self.replay(watcher).status, "pending")
                raise RuntimeError("Synthetic source rollback")
        row.refresh_from_db()
        self.assertEqual((row.status, row.error_code), ("cancelled", "availability_changed"))
        self.assertFalse(row.attempts.exists())

    def test_worker_rechecks_availability_after_revival_before_sending(self):
        watcher, row = self.cancelled_notice()
        self.assertEqual(self.replay(watcher).status, "pending")
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        BookCopy.objects.filter(pk=self.copy.pk).update(status="borrowed")
        self.assertEqual(worker.process(claim, now=NOW), "cancelled")
        self.assertEqual(fake.sent, [])
        self.assertFalse(row.attempts.exists())
        BookCopy.objects.filter(pk=self.copy.pk).update(status="available")
        self.assertEqual(self.replay(watcher).status, "pending")
        self.assertEqual(worker.process(claim, now=NOW), "fenced")
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(len(fake.sent), 1)

    def test_only_availability_cancellation_can_revive(self):
        watcher, row = self.cancelled_notice()
        for code in ("source_deleted", "message_expired", "loan_changed", ""):
            with self.subTest(code=code):
                EmailOutbox.objects.filter(pk=row.pk).update(error_code=code)
                self.assertEqual(self.replay(watcher).status, "cancelled")

    def test_any_submission_evidence_prevents_revival(self):
        watcher, row = self.cancelled_notice()
        for evidence in ({"attempts_count": 1}, {"accepted_at": NOW}, {"provider_request_id": "synthetic"}):
            with self.subTest(evidence=evidence):
                EmailOutbox.objects.filter(pk=row.pk).update(**evidence)
                self.assertEqual(self.replay(watcher).status, "cancelled")
                EmailOutbox.objects.filter(pk=row.pk).update(attempts_count=0, accepted_at=None, provider_request_id="")
        EmailAttempt.objects.create(message=row, attempt_number=1, result="started", started_at=NOW)
        self.assertEqual(self.replay(watcher).status, "cancelled")
        self.assertEqual(row.attempts.count(), 1)

    def test_accepted_uncertain_and_in_progress_states_are_never_reset(self):
        watcher, row = self.cancelled_notice()
        for state in ("accepted", "uncertain", "pending", "failed", "blocked"):
            with self.subTest(state=state):
                EmailOutbox.objects.filter(pk=row.pk).update(status=state, accepted_at=NOW if state == "accepted" else None)
                self.assertEqual(self.replay(watcher).status, state)
        EmailOutbox.objects.filter(pk=row.pk).update(status="pending", accepted_at=None)
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        self.assertEqual(self.replay(watcher).status, "claimed")
        EmailOutbox.objects.filter(pk=row.pk).update(status="submitting")
        self.assertEqual(self.replay(watcher).status, "submitting")
        self.assertEqual(fake.sent, [])
        self.assertIsNotNone(claim)

    def test_revival_preserves_ownership_timezone_and_recipient_safeguards(self):
        watcher, row = self.cancelled_notice()
        for flags in ({"LIBRARY_EMAIL_ENQUEUE_ENABLED": False},
                      {"LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED": False},
                      {"LIBRARY_EMAIL_OWNED_EVENTS": ()},
                      {"LIBRARY_ISOLATED_TESTS": False, "LIBRARY_GMAIL_SEND_ENABLED": False,
                       "LIBRARY_GRAPH_SEND_ENABLED": False}):
            with self.subTest(flags=flags), override_settings(**flags):
                self.assertEqual(self.replay(watcher).status, "cancelled")
        self.set_zone(None, watcher.borrower)
        self.assertEqual(self.replay(watcher).status, "cancelled")
        self.set_zone("Asia/Dubai", watcher.borrower)
        Loan.objects.filter(pk=watcher.pk).update(borrower_email="changed@example.test")
        self.assertEqual(self.replay(watcher).status, "cancelled")
        Loan.objects.filter(pk=watcher.pk).update(borrower_email=row.recipient_email)
        revived = self.replay(watcher)
        self.assertEqual((revived.status, revived.recipient_timezone), ("pending", "Asia/Dubai"))
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=()):
            worker, fake = self.worker()
            self.assertEqual(worker.run_once(now=NOW), ["blocked"])
            self.assertEqual(fake.sent, [])


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL locking.")
class AvailabilityConcurrencyTests(AvailabilityFixture, TransactionTestCase):
    def test_concurrent_revival_queues_one_message_and_sends_once(self):
        watcher, row = self.cancelled_notice()
        barrier = Barrier(2)

        def replay():
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    return emit_loan(Loan.objects.get(pk=watcher.pk), "notify_available")[0].pk
            finally:
                connections.close_all()

        with patch("library.email_events.timezone.now", return_value=NOW), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: replay(), range(2)))
        self.assertEqual(results, [row.pk, row.pk])
        self.assertEqual(watcher.email_messages.filter(event_type="notify_available").count(), 1)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(worker.run_once(now=NOW), [])
        self.assertEqual((len(fake.sent), row.attempts.count()), (1, 1))
