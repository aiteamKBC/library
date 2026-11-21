"""Deadline event fencing on isolated PostgreSQL; fake Gmail only."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from . import test_email_system as fixtures
from .email_events import DEADLINE_EVENTS, record_loan_change
from .email_models import EmailOutbox
from .email_transport import DeliveryResult
from .email_worker import EmailWorker, retry_message
from .models import Loan
from .test_notify_conversion import FakeGmail

NOW = fixtures.NOW


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL locks.")
class StaleLoanEmailTests(TransactionTestCase):
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm
    worker = fixtures.EmailSystemTests.worker

    def setUp(self):
        fixtures.EmailSystemTests.setUp(self)
        self.confirm()
        EmailOutbox.objects.exclude(event_type="borrow_confirmed").update(status="cancelled")

    def change_due(self, days):
        self.loan.delivery_days = days
        self.loan.save(update_fields={"delivery_days"})

    def test_confirmation_saves_deadline_snapshot(self):
        row = self.loan.email_messages.get(event_type="borrow_confirmed")
        self.assertEqual(row.due_date_snapshot, self.loan.due_date)
        self.assertEqual(row.deadline_revision, self.loan.email_deadline_revision)

    def test_successive_changes_send_only_latest_deadline(self):
        self.change_due(2)
        self.change_due(5)
        worker, fake = self.worker()
        worker.run_once(now=NOW + timedelta(days=1))
        self.assertEqual(len(fake.sent), 1)
        row = EmailOutbox.objects.get(pk=fake.sent[0][0])
        self.assertEqual(row.event_type, "due_date_changed")
        self.assertEqual(row.payload["due_date"], self.loan.due_date.isoformat())

    def confirmation(self):
        return self.loan.email_messages.get(event_type="borrow_confirmed")

    def newest(self):
        return self.loan.email_messages.get(event_type="due_date_changed", deadline_revision=self.loan.email_deadline_revision)

    def test_reservation_confirmation_has_snapshot_and_is_superseded(self):
        reserved = self.new_loan("reserved", status="reserved")
        # Free this copy before confirming the reservation.
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        reserved.status = "borrowed"
        with patch("library.models.timezone.now", return_value=NOW):
            reserved.save()
        row = reserved.email_messages.get(event_type="reservation_confirmed")
        self.assertEqual((row.due_date_snapshot, row.deadline_revision), (reserved.due_date, reserved.email_deadline_revision))
        reserved.delivery_days = 2
        reserved.save()
        row.refresh_from_db()
        self.assertEqual(row.status, "cancelled")

    def test_date_changed_back_still_fences_old_revision(self):
        row = self.confirmation()
        self.change_due(2)
        self.change_due(0)
        self.assertEqual(self.loan.due_date, row.due_date_snapshot)
        self.assertNotEqual(self.loan.email_deadline_revision, row.deadline_revision)
        # Old claimed/retry rows must also fail the worker's independent check.
        EmailOutbox.objects.filter(pk=row.pk).update(status="pending", available_at=NOW)
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        worker, fake = self.worker()
        self.assertEqual(worker.process(worker.claim(now=NOW), now=NOW), "cancelled")
        self.assertEqual(fake.sent, [])
        self.assertFalse(row.attempts.exists())

    def test_claimed_confirmation_is_fenced_without_attempt(self):
        row = self.confirmation()
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        self.change_due(3)
        row.refresh_from_db()
        self.assertEqual((row.status, row.lease_token), ("cancelled", None))
        self.assertEqual(worker.process(claim, now=NOW), "fenced")
        self.assertFalse(row.attempts.exists())
        self.assertEqual(fake.sent, [])
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(fake.sent[0][0], self.newest().pk)

    def test_sent_confirmation_and_attempt_history_are_immutable(self):
        row = self.confirmation()
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        row.refresh_from_db()
        before = (row.payload, row.due_date_snapshot, row.deadline_revision, row.accepted_at,
                  row.idempotency_key, row.event_id, list(row.attempts.values()))
        self.change_due(1)
        self.change_due(4)
        row.refresh_from_db()
        self.assertEqual(row.status, "accepted")
        self.assertEqual((row.payload, row.due_date_snapshot, row.deadline_revision, row.accepted_at,
                          row.idempotency_key, row.event_id, list(row.attempts.values())), before)
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(len(fake.sent), 2)
        self.assertEqual(fake.sent[-1][0], self.newest().pk)

    def test_partial_save_and_unchanged_deadline_do_not_cancel_valid_confirmation(self):
        row = self.confirmation()
        self.loan.due_date += timedelta(days=9)  # Not included in update_fields.
        self.loan.notes = "Synthetic note"
        self.loan.save(update_fields={"notes"})
        self.loan.refresh_from_db()
        self.loan.save(update_fields={"delivery_days"})
        row.refresh_from_db()
        self.assertEqual((row.status, row.deadline_revision, row.due_date_snapshot),
                         ("pending", self.loan.email_deadline_revision, self.loan.due_date))
        self.assertFalse(self.loan.email_messages.filter(event_type="due_date_changed").exists())

    def test_legacy_payload_is_checked_without_rewriting_it(self):
        row = self.confirmation()
        payload = {**row.payload, "due_date": (self.loan.due_date - timedelta(days=3)).isoformat()}
        EmailOutbox.objects.filter(pk=row.pk).update(payload=payload, due_date_snapshot=None, deadline_revision=None)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["cancelled"])
        row.refresh_from_db()
        self.assertEqual(row.payload, payload)
        self.assertFalse(row.attempts.exists())
        self.assertEqual(fake.sent, [])

    def test_valid_legacy_confirmation_is_not_lost_for_missing_snapshot_columns(self):
        row = self.confirmation()
        EmailOutbox.objects.filter(pk=row.pk).update(due_date_snapshot=None, deadline_revision=None)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(len(fake.sent), 1)

    def test_fixed_historical_deadline_does_not_lose_confirmation_on_delivery_edit(self):
        row = self.confirmation()
        with override_settings(LIBRARY_USER_LOCAL_CUTOVER_AT="2029-01-01T00:00:00Z"), \
                patch("library.models.timezone.now", return_value=NOW.replace(year=2030)):
            self.change_due(5)
        self.assertEqual(self.loan.due_date, row.due_date_snapshot)
        self.assertEqual(self.loan.email_deadline_revision, row.deadline_revision)
        self.assertEqual(self.confirmation().status, "pending")
        self.assertFalse(self.loan.email_messages.filter(event_type="due_date_changed").exists())

    def test_payload_and_snapshot_must_both_match(self):
        row = self.confirmation()
        for changes in (
            {"payload": {**row.payload, "due_date": "2000-01-01"}},
            {"due_date_snapshot": self.loan.due_date + timedelta(days=1)},
            {"deadline_revision": self.loan.email_deadline_revision + 1},
        ):
            with self.subTest(changes=tuple(changes)):
                EmailOutbox.objects.filter(pk=row.pk).update(status="pending", payload=row.payload,
                    due_date_snapshot=self.loan.due_date, deadline_revision=self.loan.email_deadline_revision)
                EmailOutbox.objects.filter(pk=row.pk).update(**changes)
                worker, fake = self.worker()
                self.assertEqual(worker.run_once(now=NOW), ["cancelled"])
                self.assertFalse(row.attempts.exists())
                self.assertEqual(fake.sent, [])

    def test_old_retry_keeps_attempt_but_cannot_resubmit(self):
        row = self.confirmation()
        fake = FakeGmail(DeliveryResult("retryable_failure", 503, "gmail_temporary_rejection", 60))
        worker = EmailWorker(client=fake)
        self.assertEqual(worker.run_once(now=NOW), ["retry_wait"])
        attempt = list(row.attempts.values())
        self.change_due(3)
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts_count), ("cancelled", 1))
        self.assertEqual(list(row.attempts.values()), attempt)
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)
        fake.result = DeliveryResult("accepted", 200, request_id="gmail:synthetic")
        self.assertEqual(worker.run_once(now=NOW + timedelta(hours=1)), ["accepted"])
        self.assertEqual(fake.sent, [row.pk, self.newest().pk])

    def test_unchanged_retry_preserves_idempotency_and_attempt_numbering(self):
        row = self.confirmation()
        fake = FakeGmail(DeliveryResult("retryable_failure", 503, "gmail_temporary_rejection", 60))
        worker = EmailWorker(client=fake)
        self.assertEqual(worker.run_once(now=NOW), ["retry_wait"])
        self.loan.notes = "No deadline change"
        self.loan.save(update_fields={"notes"})
        fake.result = DeliveryResult("accepted", 200, request_id="gmail:synthetic")
        self.assertEqual(worker.run_once(now=NOW + timedelta(hours=1)), ["accepted"])
        self.assertEqual(fake.sent, [row.pk, row.pk])
        self.assertEqual(list(row.attempts.order_by("attempt_number").values_list("attempt_number", flat=True)), [1, 2])

    def test_failed_message_manual_retry_checks_deadline(self):
        row = self.confirmation()
        fake = FakeGmail(DeliveryResult("permanent_failure", 400, "gmail_permanent_rejection"))
        worker = EmailWorker(client=fake)
        self.assertEqual(worker.run_once(now=NOW), ["failed"])
        self.change_due(1)
        # Simulate a pre-fix failed row not cancelled by the producer.
        EmailOutbox.objects.filter(pk=row.pk).update(status="failed")
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)
        self.assertEqual(row.attempts.count(), 1)

    def test_cancellation_runs_with_enqueue_disabled_without_enabling_new_messages(self):
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=False):
            self.change_due(3)
        self.assertEqual(self.confirmation().status, "cancelled")
        self.assertFalse(self.loan.email_messages.filter(event_type="due_date_changed").exists())

    def test_return_cancels_pending_deadline_events(self):
        self.change_due(3)
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        self.assertFalse(self.loan.email_messages.filter(event_type__in=DEADLINE_EVENTS).exclude(status="cancelled").exists())

    def test_change_and_replacement_outbox_rollback_together(self):
        before = self.loan.due_date
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.change_due(3)
            self.assertEqual(self.confirmation().status, "cancelled")
            self.assertEqual(self.newest().status, "pending")
            raise RuntimeError("Synthetic rollback")
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before)
        self.assertEqual(self.confirmation().status, "pending")
        self.assertFalse(self.loan.email_messages.filter(event_type="due_date_changed").exists())

    def test_replayed_change_does_not_duplicate_latest_message(self):
        previous = Loan.objects.get(pk=self.loan.pk)
        self.change_due(3)
        row = self.newest()
        with transaction.atomic():
            record_loan_change(self.loan, previous)
        self.assertEqual(self.newest().pk, row.pk)
        self.assertEqual(self.loan.email_messages.filter(event_type="due_date_changed").count(), 1)

    def during_send(self, result):
        row = self.confirmation()
        entered, finish = Event(), Event()
        fake = FakeGmail(result, entered, finish)

        def send():
            try:
                return EmailWorker(client=fake).run_once(limit=1, now=NOW)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(send)
            try:
                self.assertTrue(entered.wait(timeout=15))
                self.change_due(2)
                self.change_due(5)
                row.refresh_from_db()
                self.assertEqual(row.status, "submitting")
                self.assertEqual(row.due_date_snapshot + timedelta(days=5), self.loan.due_date)
                second_fake = FakeGmail()
                second = EmailWorker(client=second_fake)
                self.assertEqual(second.run_once(now=NOW), ["pending"])
                self.assertEqual(second_fake.sent, [])
                self.assertEqual(self.newest().attempts_count, 0)
            finally:
                finish.set()
            outcome = future.result(timeout=15)
        row.refresh_from_db()
        self.assertEqual(row.attempts.count(), 1)
        self.assertEqual(fake.sent, [row.pk])
        self.assertEqual(second.run_once(now=NOW + timedelta(minutes=1)), ["accepted"])
        self.assertEqual(second_fake.sent, [self.newest().pk])
        self.assertEqual(second.run_once(now=NOW + timedelta(days=1)), [])
        return row, outcome

    def test_change_during_accepted_submission_defers_latest_until_result(self):
        row, outcome = self.during_send(DeliveryResult("accepted", 200, request_id="gmail:synthetic"))
        self.assertEqual(outcome, ["accepted"])
        self.assertEqual(row.status, "accepted")

    def test_change_during_uncertain_submission_keeps_history_and_sends_new_information(self):
        row, outcome = self.during_send(DeliveryResult("uncertain", code="gmail_submission_unknown"))
        self.assertEqual(outcome, ["uncertain"])
        self.assertEqual(row.status, "uncertain")
        with self.assertRaises(ValidationError):
            retry_message(row.pk, actor=self.admin)

    def test_change_during_definite_failure_prevents_retry_of_old_date(self):
        # The late definite failure retains its attempt; the next claim fences
        # that old date and still sends the newest distinct revision.
        entered, finish = Event(), Event()
        fake = FakeGmail(DeliveryResult("retryable_failure", 503, "gmail_temporary_rejection", 60), entered, finish)

        def send():
            try:
                return EmailWorker(client=fake).run_once(limit=1, now=NOW)
            finally:
                connections.close_all()

        row = self.confirmation()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(send)
            try:
                self.assertTrue(entered.wait(timeout=15))
                self.change_due(4)
            finally:
                finish.set()
            self.assertEqual(future.result(timeout=15), ["retry_wait"])
        newer = FakeGmail()
        outcomes = EmailWorker(client=newer).run_once(now=NOW + timedelta(hours=1))
        self.assertCountEqual(outcomes, ["cancelled", "accepted"])
        self.assertEqual(newer.sent, [self.newest().pk])
        self.assertEqual(row.attempts.count(), 1)

    def test_expired_submission_becomes_uncertain_and_does_not_block_latest_forever(self):
        row = self.confirmation()
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        # A synthetic crash after the durable submission fence.
        from .email_models import EmailAttempt
        EmailOutbox.objects.filter(pk=row.pk).update(status="submitting", attempts_count=1)
        EmailAttempt.objects.create(message=row, attempt_number=1, started_at=NOW, result="started", lease_token=claim[1])
        self.change_due(4)
        worker.recover_expired(now=NOW + timedelta(hours=1))
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts.get().result), ("uncertain", "uncertain"))
        self.assertEqual(worker.run_once(now=NOW + timedelta(hours=1)), ["accepted"])
        self.assertEqual(fake.sent[0][0], self.newest().pk)

    def test_concurrent_deadline_edits_keep_only_latest_committed_revision_sendable(self):
        barrier = Barrier(2)

        def edit(days):
            try:
                loan = Loan.objects.get(pk=self.loan.pk)
                barrier.wait(timeout=15)
                loan.delivery_days = days
                try:
                    loan.save(update_fields={"delivery_days"})
                except ValidationError:
                    # Existing optimistic revision check rejects stale editors.
                    loan.refresh_from_db()
                    loan.delivery_days = days
                    loan.save(update_fields={"delivery_days"})
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(edit, (2, 4)))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.email_deadline_revision, self.confirmation().deadline_revision + 2)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(fake.sent[0][0], self.newest().pk)
