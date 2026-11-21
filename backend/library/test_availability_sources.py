"""Availability producers, queue eligibility and races; synthetic PostgreSQL only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest import skipUnless
from unittest.mock import patch
import uuid

from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from . import test_email_system as fixtures
from .email_events import record_book_availability
from .email_models import EmailOutbox
from .email_transport import DeliveryResult
from .email_worker import EmailWorker
from .models import BookCopy, Loan, Resource
from .test_notify_conversion import FakeGmail

NOW = fixtures.NOW


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL transactions.")
class AvailabilitySourcesTests(TransactionTestCase):
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm
    worker = fixtures.EmailSystemTests.worker

    def setUp(self):
        fixtures.EmailSystemTests.setUp(self)
        self.confirm()
        self.watcher = self.new_loan("notify-accept", loan_type="notify")

    def notices(self, loan=None):
        return (loan or self.watcher).email_messages.filter(event_type="notify_available")

    def return_book(self):
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()

    def add_copy(self, number="EXTRA"):
        return BookCopy.objects.create(resource=self.resource, accession_number=number)

    def test_new_copy_queues_availability_in_same_transaction(self):
        self.add_copy()
        self.assertEqual(self.notices().count(), 1)

    def test_cancelled_reservation_queues_availability(self):
        reservation = self.new_loan("reservation", status="reserved")
        self.return_book()
        self.assertFalse(self.notices().exists())
        reservation.status = "cancelled"
        reservation.save(update_fields={"status"})
        self.assertEqual(self.notices().count(), 1)

    def test_return_queues_once_and_notes_do_not_repeat(self):
        self.return_book()
        self.loan.notes = "Only a note"
        self.loan.save(update_fields={"notes"})
        self.loan.save()
        self.assertEqual(self.notices().count(), 1)

    def test_inventory_api_bulk_addition_uses_same_producer(self):
        response = self.client.patch(f"/api/resources/{self.resource.pk}/", {"inventoryCount": 3}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.notices().count(), 1)
        self.resource.ensure_copy_inventory(3)
        self.assertEqual(self.notices().count(), 1)

    def test_restore_maintenance_and_lost_only_when_unoccupied(self):
        for hold in ("maintenance", "lost"):
            with self.subTest(hold=hold):
                copy = BookCopy.objects.create(resource=self.resource, accession_number=hold, status=hold)
                self.assertFalse(self.notices().exists())
                response = self.client.patch(f"/api/copies/{copy.pk}/", {"status": "available"}, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self.notices().count(), 1)
                # Reset only synthetic unsent rows between independent sources.
                self.notices().delete()
                copy.status = hold
                copy.save()
        self.copy.status = "maintenance"
        self.copy.save()
        self.copy.status = "available"
        self.copy.save()
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")
        self.assertFalse(self.notices().exists())

    def test_return_of_held_copy_recalculates_without_notice_until_real_availability_event(self):
        self.copy.status = "lost"
        self.copy.save()
        self.return_book()
        self.assertFalse(self.notices().exists())
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")
        self.add_copy()
        self.assertEqual(self.notices().count(), 1)

    def test_cancel_reservation_does_not_free_a_borrowed_copy(self):
        reservation = self.new_loan("reserved", status="reserved")
        reservation.status = "cancelled"
        reservation.save()
        self.assertFalse(self.notices().exists())
        self.return_book()
        self.assertEqual(self.notices().count(), 1)

    def test_approved_cancellation_discovers_availability(self):
        # Separate synthetic approved loan, not an invalid backwards transition.
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=False):
            self.return_book()
        approved = self.new_loan("approved")
        approved.status = "approved"
        approved.save()
        self.assertFalse(self.notices().exists())
        approved.status = "cancelled"
        approved.save()
        self.assertEqual(self.notices().count(), 1)

    def test_borrow_queue_has_priority_and_is_limited_to_real_capacity(self):
        first = self.new_loan("first", requested_at=NOW - timedelta(days=2))
        second = self.new_loan("second", requested_at=NOW - timedelta(days=1))
        self.add_copy("ONE")
        self.assertEqual(first.email_messages.filter(event_type="book_now_available").count(), 1)
        self.assertFalse(second.email_messages.filter(event_type="book_now_available").exists())
        self.assertFalse(self.notices().exists())
        self.add_copy("TWO")
        self.assertEqual(second.email_messages.filter(event_type="book_now_available").count(), 1)
        self.assertFalse(self.notices().exists())
        self.add_copy("THREE")
        self.assertEqual(self.notices().count(), 1)

    def test_cancelling_pending_borrow_frees_queue_capacity(self):
        pending = self.new_loan("pending")
        self.return_book()
        self.assertFalse(self.notices().exists())
        response = self.client.patch(f"/api/loans/{pending.pk}/", {"status": "cancelled"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.notices().count(), 1)

    def test_stale_available_status_does_not_override_reservation(self):
        self.new_loan("reserved", status="reserved")
        self.return_book()
        BookCopy.objects.filter(pk=self.copy.pk).update(status="available")  # Historical inconsistent row.
        with transaction.atomic():
            record_book_availability(self.resource.pk)
        self.assertFalse(self.notices().exists())

    def only_notice(self):
        row = self.notices().get()
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=NOW)
        return row

    def test_worker_rechecks_queue_after_claim_and_revives_same_unsent_message(self):
        self.return_book()
        row = self.only_notice()
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        pending = self.new_loan("pending")
        self.assertEqual(worker.process(claim, now=NOW), "cancelled")
        self.assertFalse(row.attempts.exists())
        pending.status = "cancelled"
        with patch("library.email_events.timezone.now", return_value=NOW):
            pending.save()
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.assertEqual(self.notices().count(), 1)
        self.only_notice()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(len(fake.sent), 1)

    def test_book_now_available_is_once_per_request_even_across_sources(self):
        pending = self.new_loan("pending")
        self.add_copy()
        row = pending.email_messages.get(event_type="book_now_available")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=NOW)
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=(row.recipient_email,)):
            worker, fake = self.worker()
            self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.return_book()
        self.add_copy("ANOTHER")
        self.assertEqual(pending.email_messages.filter(event_type="book_now_available").count(), 1)
        self.assertEqual(row.attempts.count(), 1)

    def test_accepted_or_uncertain_notify_never_requeues(self):
        self.add_copy()
        row = self.only_notice()
        fake = FakeGmail(DeliveryResult("uncertain", code="gmail_submission_unknown"))
        worker = EmailWorker(client=fake)
        self.assertEqual(worker.run_once(now=NOW), ["uncertain"])
        self.return_book()
        self.add_copy("SECOND")
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts.count()), ("uncertain", 1))
        self.assertEqual(self.notices().count(), 1)
        self.only_notice()
        self.assertEqual(worker.run_once(now=NOW + timedelta(days=1)), [])
        self.assertEqual(len(fake.sent), 1)

    def test_retry_wait_is_not_reset_by_another_availability_source(self):
        self.add_copy()
        row = self.only_notice()
        fake = FakeGmail(DeliveryResult("retryable_failure", 503, "gmail_temporary_rejection", 60))
        worker = EmailWorker(client=fake)
        self.assertEqual(worker.run_once(now=NOW), ["retry_wait"])
        row.refresh_from_db()
        retry_at = row.available_at
        self.return_book()
        row.refresh_from_db()
        self.assertEqual((row.status, row.available_at, row.attempts_count), ("retry_wait", retry_at, 1))
        fake.result = DeliveryResult("accepted", 200, request_id="gmail:synthetic")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        self.assertEqual(worker.run_once(now=NOW + timedelta(hours=1)), ["accepted"])
        self.assertEqual(self.notices().count(), 1)
        self.add_copy("THIRD")
        self.assertEqual(self.notices().count(), 1)

    def test_source_and_outbox_rollback_together(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.add_copy()
            self.assertEqual(self.notices().count(), 1)
            raise RuntimeError("Synthetic rollback")
        self.assertFalse(BookCopy.objects.filter(accession_number="EXTRA").exists())
        self.assertFalse(self.notices().exists())
        with patch("library.email_events.emit_loan", side_effect=RuntimeError("Synthetic enqueue failure")):
            with self.assertRaises(RuntimeError):
                self.add_copy()
        self.assertFalse(BookCopy.objects.filter(accession_number="EXTRA").exists())

    def test_disabled_producer_keeps_inventory_working_without_email(self):
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=False):
            self.add_copy()
            self.return_book()
        self.assertFalse(self.notices().exists())

    def test_parallel_copy_addition_and_return_create_one_notice(self):
        barrier = Barrier(2)

        def change(add):
            try:
                barrier.wait(timeout=15)
                if add:
                    self.add_copy()
                else:
                    self.return_book()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(change, (True, False)))
        self.assertEqual(self.notices().count(), 1)
        row = self.only_notice()
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual((len(fake.sent), row.attempts.count()), (1, 1))

    def test_parallel_cancellations_release_capacity_without_duplicate(self):
        first = self.new_loan("first")
        second = self.new_loan("second")
        self.return_book()
        barrier = Barrier(2)

        def cancel(pk):
            try:
                barrier.wait(timeout=15)
                loan = Loan.objects.get(pk=pk)
                loan.status = "cancelled"
                loan.save()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(cancel, (first.pk, second.pk)))
        self.assertEqual(self.notices().count(), 1)

    def test_producer_is_not_visible_to_worker_until_transaction_commits(self):
        ready, finish = Event(), Event()

        def add_uncommitted():
            try:
                with transaction.atomic():
                    self.add_copy()
                    ready.set()
                    if not finish.wait(timeout=15):
                        raise RuntimeError("Synthetic timeout")
            finally:
                connections.close_all()

        EmailOutbox.objects.all().update(status="cancelled")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(add_uncommitted)
            try:
                self.assertTrue(ready.wait(timeout=15))
                worker, fake = self.worker()
                self.assertIsNone(worker.claim(now=NOW))
                self.assertEqual(fake.sent, [])
            finally:
                finish.set()
            future.result(timeout=15)
        self.assertEqual(self.notices().count(), 1)

    def test_queued_notice_rechecks_copy_hold_and_restoration_revives_it(self):
        spare = self.add_copy()
        row = self.only_notice()
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        spare.status = "maintenance"
        spare.save()
        self.assertEqual(worker.process(claim, now=NOW), "cancelled")
        self.assertFalse(row.attempts.exists())
        spare.status = "available"
        with patch("library.email_events.timezone.now", return_value=NOW):
            spare.save()
        row.refresh_from_db()
        self.assertEqual(row.status, "pending")
        self.assertEqual(self.notices().count(), 1)
        self.assertEqual(worker.process(claim, now=NOW), "fenced")
        self.assertEqual(worker.run_once(now=NOW), ["accepted"])
        self.assertEqual(len(fake.sent), 1)

    def test_reservation_cancellation_and_outbox_rollback_together(self):
        reservation = self.new_loan("reserved", status="reserved")
        self.return_book()
        with self.assertRaises(RuntimeError), transaction.atomic():
            reservation.status = "cancelled"
            reservation.save()
            self.assertEqual(self.notices().count(), 1)
            raise RuntimeError("Synthetic rollback")
        reservation.refresh_from_db()
        self.copy.refresh_from_db()
        self.assertEqual((reservation.status, self.copy.status), ("reserved", "reserved"))
        self.assertFalse(self.notices().exists())

    def test_legacy_return_cycle_keys_cannot_send_twice(self):
        pending = self.new_loan("pending")
        self.add_copy()
        row = pending.email_messages.get(event_type="book_now_available")
        original_id = row.pk
        row.idempotency_key = "synthetic-legacy-return-one"
        row.available_at = NOW
        row.save()
        row.pk, row.event_id = uuid.uuid4(), uuid.uuid4()
        row.idempotency_key = "synthetic-legacy-return-two"
        row.save()
        EmailOutbox.objects.exclude(pk__in=(original_id, row.pk)).update(status="cancelled")
        with override_settings(LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=(row.recipient_email,)):
            worker, fake = self.worker()
            self.assertEqual(worker.run_once(now=NOW), ["accepted", "cancelled"])
            self.assertEqual(len(fake.sent), 1)
        self.return_book()
        self.assertEqual(pending.email_messages.filter(event_type="book_now_available").count(), 2)
        self.assertEqual(pending.email_messages.filter(event_type="book_now_available", status="accepted").count(), 1)

    def test_available_copy_removed_before_submission_cancels_notice(self):
        spare = self.add_copy()
        row = self.only_notice()
        worker, fake = self.worker()
        claim = worker.claim(now=NOW)
        spare.delete()
        self.assertEqual(worker.process(claim, now=NOW), "cancelled")
        self.assertFalse(row.attempts.exists())
        self.assertEqual(fake.sent, [])

    def test_approval_during_fake_provider_does_not_reopen_or_reclassify_request(self):
        spare = self.add_copy()
        row = self.only_notice()
        entered, finish = Event(), Event()
        fake = FakeGmail(entered=entered, release=finish)

        def send():
            try:
                return EmailWorker(client=fake).run_once(limit=1, now=NOW)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(send)
            try:
                self.assertTrue(entered.wait(timeout=15))
                self.watcher.loan_type = "borrow"
                self.watcher.save(update_fields={"loan_type"})
                with patch("library.models.timezone.now", return_value=NOW):
                    response = self.client.post(f"/api/loans/{self.watcher.pk}/approve/", {"deliveryDays": 0}, format="json")
                self.assertEqual(response.status_code, 200, response.data)
            finally:
                finish.set()
            # Newly produced confirmation events are not part of this test send.
            result = future.result(timeout=15)
        self.assertEqual(result, ["accepted"])
        self.watcher.refresh_from_db()
        self.assertEqual((self.watcher.loan_type, self.watcher.status, self.watcher.book_copy_id),
                         ("borrow", "borrowed", spare.pk))
        row.refresh_from_db()
        self.assertEqual((row.status, row.attempts.count()), ("accepted", 1))
        self.assertEqual(fake.sent, [row.pk])
