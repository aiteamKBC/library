"""Legacy copy status calculation and availability suppression on PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.contrib import admin
from django.core.cache import cache
from django.db import connection, connections, transaction
from django.test import RequestFactory, TransactionTestCase, override_settings

from . import test_email_system as fixtures
from .admin import BookCopyAdmin
from .email_models import EmailOutbox
from .models import BookCopy, Loan, Resource

NOW = fixtures.NOW
HOLDS = ("maintenance", "lost")


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL transactions.")
class CopyStatusIntegrityTests(TransactionTestCase):
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm
    worker = fixtures.EmailSystemTests.worker

    def setUp(self):
        fixtures.EmailSystemTests.setUp(self)
        cache.clear()
        self.addCleanup(cache.clear)

    def staff_status(self, status, expected=200):
        response = self.client.patch(f"/api/copies/{self.copy.pk}/", {"status": status}, format="json")
        self.assertEqual(response.status_code, expected, response.data)
        return response

    def assert_hold(self, hold):
        self.copy.refresh_from_db()
        resource = Resource.objects.get(pk=self.resource.pk)
        self.assertEqual(self.copy.status, hold)
        self.assertEqual(resource.available_copies, 0)
        self.assertFalse(resource.can_borrow)
        self.assertIsNone(resource.first_available_copy())
        self.assertIsNone(resource.first_usable_copy())

    def test_loan_notes_and_cancellation_restore_legacy_available_status(self):
        for hold in HOLDS:
            with self.subTest(hold=hold):
                self.staff_status(hold)
                self.loan.notes = "Synthetic note"
                self.loan.save(update_fields={"notes"})
                self.copy.refresh_from_db()
                self.assertEqual(self.copy.status, "available")
        self.staff_status("lost")
        self.loan.status = "cancelled"
        self.loan.save(update_fields={"status"})
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")

    def test_return_recalculates_held_copy_without_creating_availability_notice(self):
        self.confirm()
        watcher = self.new_loan("notify-accept", loan_type="notify")
        self.staff_status("maintenance")
        self.loan.notes = "Borrowed copy under administrative review"
        self.loan.save(update_fields={"notes"})
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "borrowed")
        self.staff_status("lost")
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")
        self.assertFalse(watcher.email_messages.filter(event_type="notify_available").exists())
        # A queued notice must still be rejected while the persisted copy is lost.
        self.staff_status("lost")
        row = watcher.email_messages.get(event_type="notify_registered")
        row.pk = None
        row.event_type, row.template_key = "notify_available", "notify_available.student"
        row.idempotency_key = "synthetic-pre-fix-held-notice"
        row.save()
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=NOW)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["cancelled"])
        self.assertEqual(fake.sent, [])
        self.assertFalse(row.attempts.exists())
        self.assert_hold("lost")

    def test_existing_borrowing_can_be_marked_overdue_while_copy_is_lost(self):
        self.confirm()
        self.staff_status("lost")
        self.loan.status = "overdue"
        self.loan.save(update_fields={"status"})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, "overdue")
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "borrowed")

    def test_cancelling_approved_loan_restores_legacy_available_status(self):
        self.confirm("approved")
        self.staff_status("maintenance")
        self.loan.status = "cancelled"
        self.loan.save(update_fields={"status"})
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")

    def test_explicit_copy_id_uses_legacy_model_validation(self):
        for state, expected in (("requested", "available"), ("reserved", "reserved")):
            with self.subTest(state=state):
                self.staff_status("maintenance")
                self.new_loan(f"held-{state}", status=state)
                self.copy.refresh_from_db()
                self.assertEqual(self.copy.status, expected)

    def test_deleting_loan_and_syncing_stale_copy_restore_legacy_status(self):
        stale = BookCopy.objects.get(pk=self.copy.pk)
        self.staff_status("maintenance")
        self.assertEqual(Loan.next_copy_status(stale), "available")
        Loan.sync_book_copy_status(stale)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")
        self.staff_status("lost")
        with patch("library.email_events.enqueue_enabled", return_value=False):
            # Synthetic loan without protected attempt history.
            EmailOutbox.objects.filter(loan=self.loan).delete()
            self.loan.delete()
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")

    def test_staff_status_edits_are_saved_as_entered(self):
        for hold in HOLDS:
            with self.subTest(hold=hold, state="requested"):
                self.staff_status(hold)
                self.assertEqual(self.staff_status("available").data["status"], "available")
        self.confirm("approved")
        self.staff_status("maintenance")
        self.assertEqual(self.staff_status("available").data["status"], "available")
        self.loan.status = "borrowed"
        self.loan.save()
        self.staff_status("lost")
        self.assertEqual(self.staff_status("available").data["status"], "available")
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        self.staff_status("maintenance")
        self.assertEqual(self.staff_status("available").data["status"], "available")

    def test_admin_form_uses_standard_save_without_special_release_action(self):
        stale = BookCopy.objects.get(pk=self.copy.pk)
        self.staff_status("lost")
        model_admin = BookCopyAdmin(BookCopy, admin.site)
        request = RequestFactory().post("/admin/library/bookcopy/")
        request.user = self.admin
        stale.notes = "Only notes were edited"
        model_admin.save_model(request, stale, SimpleNamespace(changed_data=["notes"]), True)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")
        current = BookCopy.objects.get(pk=self.copy.pk)
        current.status = "available"
        model_admin.save_model(request, current, SimpleNamespace(changed_data=["status"]), True)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")

    def test_student_cannot_release_hold(self):
        self.staff_status("maintenance")
        self.client.force_authenticate(self.student)
        self.staff_status("available", expected=403)
        self.assert_hold("maintenance")

    def test_approve_api_keeps_availability_guard_and_direct_save_uses_legacy_rules(self):
        self.staff_status("lost")
        response = self.client.post(f"/api/loans/{self.loan.pk}/approve/", {"deliveryDays": 0}, format="json")
        self.assertEqual(response.status_code, 400)
        self.loan.refresh_from_db()
        self.confirm()
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "borrowed")

    def test_status_change_invalidates_resource_list_cache_after_commit(self):
        response = self.client.get("/api/resources/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(cache.get("api:resources:list"))
        self.staff_status("maintenance")
        self.assertIsNone(cache.get("api:resources:list"))
        response = self.client.get("/api/resources/")
        self.assertEqual(response.status_code, 200)
        rows = response.data.get("results", []) if isinstance(response.data, dict) else response.data
        resource = next(row for row in rows if row["id"] == self.resource.pk)
        self.assertEqual(resource["availableCopies"], 0)

    def test_admin_release_rollback_preserves_hold(self):
        self.staff_status("lost")
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.staff_status("available")
                raise RuntimeError("Synthetic rollback")
        self.assert_hold("lost")

    def test_admin_hold_wins_against_in_flight_loan_synchronization(self):
        calculated, resume, admin_started = Event(), Event(), Event()
        original = Loan.sync_book_copy_status

        def paused_calculation(copy):
            calculated.set()
            if not resume.wait(timeout=15):
                raise RuntimeError("Synthetic synchronization timeout")
            return original(copy)

        def save_notes():
            try:
                loan = Loan.objects.get(pk=self.loan.pk)
                loan.notes = "Concurrent note"
                loan.save(update_fields={"notes"})
            finally:
                connections.close_all()

        def admin_hold():
            try:
                copy = BookCopy.objects.get(pk=self.copy.pk)
                copy.status = "maintenance"
                admin_started.set()
                copy.save()
            finally:
                connections.close_all()

        with patch.object(Loan, "sync_book_copy_status", side_effect=paused_calculation):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(save_notes)
                try:
                    self.assertTrue(calculated.wait(timeout=15))
                    admin_future = pool.submit(admin_hold)
                    self.assertTrue(admin_started.wait(timeout=15))
                    # The shared resource mutex now serializes these writes.
                    self.assertFalse(admin_future.done())
                finally:
                    resume.set()
                future.result(timeout=15)
                admin_future.result(timeout=15)
        self.assert_hold("maintenance")

    def test_explicit_release_and_return_finish_with_correct_occupancy(self):
        self.confirm()
        self.staff_status("lost")
        releasing, finish, returning = Event(), Event(), Event()

        def admin_release():
            try:
                with transaction.atomic():
                    Resource.lock_availability(self.resource.pk)
                    copy = BookCopy.objects.select_for_update().get(pk=self.copy.pk)
                    copy.status = "available"
                    copy.save()
                    self.assertEqual(copy.status, "available")
                    releasing.set()
                    if not finish.wait(timeout=15):
                        raise RuntimeError("Synthetic release timeout")
            finally:
                connections.close_all()

        def return_loan():
            try:
                loan = Loan.objects.get(pk=self.loan.pk)
                loan.status, loan.returned_at, loan.return_condition = "returned", NOW, "good"
                returning.set()
                loan.save()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            release_future = pool.submit(admin_release)
            try:
                self.assertTrue(releasing.wait(timeout=15))
                return_future = pool.submit(return_loan)
                self.assertTrue(returning.wait(timeout=15))
                self.assertFalse(return_future.done())
            finally:
                finish.set()
            release_future.result(timeout=15)
            return_future.result(timeout=15)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")

    def watcher(self):
        return self.new_loan("notify-accept", loan_type="notify")

    def assert_no_availability(self, watcher):
        self.assertFalse(watcher.email_messages.filter(
            event_type__in=("notify_available", "book_now_available")).exists())

    def test_notes_recalculation_alone_never_enqueues_notify(self):
        watcher = self.watcher()
        for status in HOLDS:
            with self.subTest(status=status):
                self.staff_status(status)
                self.loan.notes = status
                self.loan.save(update_fields={"notes"})
                self.copy.refresh_from_db()
                self.assertEqual(self.copy.status, "available")
                self.assert_no_availability(watcher)
                self.loan.save()
                self.assert_no_availability(watcher)

    def test_pending_cancellation_cannot_bypass_suppression(self):
        watcher = self.watcher()
        self.staff_status("lost")
        self.loan.status = "cancelled"
        self.loan.save(update_fields={"status"})
        self.assert_no_availability(watcher)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")

    def test_deletion_cannot_bypass_suppression(self):
        watcher = self.watcher()
        self.staff_status("maintenance")
        self.loan.email_messages.all().delete()
        self.loan.delete()
        self.assert_no_availability(watcher)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.status, "available")

    def test_approved_cancellation_does_not_notify_on_automatic_status_reset(self):
        self.confirm("approved")
        watcher = self.watcher()
        self.staff_status("maintenance")
        self.loan.status = "cancelled"
        self.loan.save()
        self.assert_no_availability(watcher)

    def test_reserved_cancellation_does_not_notify_on_automatic_status_reset(self):
        self.loan.status = "cancelled"
        self.loan.save()
        self.loan = self.new_loan("reserved", status="reserved")
        watcher = self.watcher()
        self.staff_status("lost")
        self.loan.status = "cancelled"
        self.loan.save()
        self.assert_no_availability(watcher)

    def test_pending_cancellation_can_notify_using_a_different_real_copy(self):
        watcher = self.watcher()
        BookCopy.objects.create(resource=self.resource, accession_number="REAL-SPARE")
        # Two pending requests cover the two copies, leaving no surplus.
        other = self.new_loan("other-borrow")
        watcher.email_messages.filter(event_type="notify_available").delete()
        self.staff_status("lost")
        self.loan.status = "cancelled"
        self.loan.save()
        self.assert_no_availability(watcher)  # Real spare is reserved for older borrow queue.
        self.assertTrue(other.email_messages.filter(event_type="book_now_available").exists())

    def test_pending_cancellation_with_real_surplus_still_notifies(self):
        watcher = self.watcher()
        with override_settings(LIBRARY_EMAIL_ENQUEUE_ENABLED=False):
            BookCopy.objects.create(resource=self.resource, accession_number="REAL-SPARE")
        self.staff_status("maintenance")
        self.loan.status = "cancelled"
        self.loan.save()
        self.assertEqual(watcher.email_messages.filter(event_type="notify_available").count(), 1)

    def test_automatic_reset_does_not_revive_cancelled_notice(self):
        self.confirm()
        watcher = self.watcher()
        self.loan.status, self.loan.returned_at, self.loan.return_condition = "returned", NOW, "good"
        self.loan.save()
        row = watcher.email_messages.get(event_type="notify_available")
        self.staff_status("lost")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=NOW)
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=NOW), ["cancelled"])
        self.loan.notes = "No physical availability change"
        self.loan.save(update_fields={"notes"})
        row.refresh_from_db()
        self.assertEqual(row.status, "cancelled")
        self.assertFalse(row.attempts.exists())
        self.assertEqual(fake.sent, [])

    def test_status_edits_and_automatic_reset_never_change_inventory_count(self):
        self.resource.ensure_copy_inventory(3)
        original_ids = set(self.resource.copies.values_list("pk", flat=True))
        for status in HOLDS:
            self.staff_status(status)
            self.loan.save(update_fields={"notes"})
            self.assertEqual(set(self.resource.copies.values_list("pk", flat=True)), original_ids)
        response = self.client.patch(f"/api/resources/{self.resource.pk}/", {"inventoryCount": 2}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.resource.copies.count(), 2)

    def test_automatic_reset_and_new_copy_concurrently_enqueue_only_one_notice(self):
        self.confirm()
        watcher = self.watcher()
        self.staff_status("lost")
        from threading import Barrier
        barrier = Barrier(2)

        def change(add):
            try:
                barrier.wait(timeout=15)
                if add:
                    BookCopy.objects.create(resource=self.resource, accession_number="REAL-SPARE")
                else:
                    loan = Loan.objects.get(pk=self.loan.pk)
                    loan.status, loan.returned_at, loan.return_condition = "returned", NOW, "good"
                    loan.save()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(change, (False, True)))
        self.assertEqual(watcher.email_messages.filter(event_type="notify_available").count(), 1)
