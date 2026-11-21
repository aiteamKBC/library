"""Real overlapping transactions against synthetic PostgreSQL only.

These regressions verify the shared Resource mutex and the independent
PostgreSQL guard, including across different physical copies.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, local
from time import monotonic, sleep
from unittest import skipUnless
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, connections, transaction
from django.test import RequestFactory, TransactionTestCase
from rest_framework.test import APIClient

from . import test_email_system as fixtures
from .admin import LoanAdmin
from .email_models import EmailOutbox, EmailAttempt
from .models import BookCopy, Loan, Resource

NOW = fixtures.NOW


@skipUnless(connection.vendor == "postgresql", "Requires isolated PostgreSQL transactions and row locks.")
class DuplicateBorrowRequestTests(TransactionTestCase):
    new_loan = fixtures.EmailSystemTests.new_loan

    def setUp(self):
        fixtures.EmailSystemTests.setUp(self)
        # Leave a clean, borrowable title with two copies and the same student.
        EmailOutbox.objects.all().delete()
        self.loan.delete()
        self.spare = BookCopy.objects.create(resource=self.resource, accession_number="MAIL-2")

    def make(self, pk, copy_id=None, **extra):
        values = dict(id=pk, borrower=self.student, borrower_name="Synthetic Student",
                      borrower_email=self.student.email, borrower_phone="07123456789",
                      book_copy_id=copy_id or self.copy.pk)
        values.update(extra)
        return Loan.objects.create(**values)

    def active(self):
        return Loan.objects.filter(borrower=self.student, book_copy__resource=self.resource,
                                   status__in=Loan.active_statuses())

    def parallel(self, actions):
        """Both transactions reach the first resource lock before either proceeds."""
        barrier, seen, guard, thread = Barrier(len(actions)), [], Lock(), local()
        original = Resource.lock_availability

        def synchronized_lock(*ids):
            if not getattr(thread, "entered", False):
                thread.entered = True
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid(), txid_current()")
                    identity = cursor.fetchone()
                with guard:
                    seen.append(identity)
                barrier.wait(timeout=15)
            return original(*ids)

        def run(action):
            try:
                with transaction.atomic():
                    return action()
            except ValidationError as exc:
                return "duplicate" if "already have an active" in str(exc) else str(exc)
            finally:
                connections.close_all()

        with patch.object(Resource, "lock_availability", side_effect=synchronized_lock), ThreadPoolExecutor(max_workers=len(actions)) as pool:
            results = list(pool.map(run, actions))
        self.assertEqual(len({pid for pid, _ in seen}), len(actions))
        self.assertEqual(len({txid for _, txid in seen}), len(actions))
        return results

    def assert_single_submission(self, ids):
        self.assertEqual(self.active().count(), 1)
        winner = self.active().get()
        loser_ids = set(ids) - {winner.pk}
        self.assertFalse(Loan.objects.filter(pk__in=loser_ids).exists())
        self.assertFalse(EmailOutbox.objects.filter(source_id__in=loser_ids).exists())
        self.assertEqual(winner.email_messages.filter(event_type="loan_submitted").count(), 2)
        self.assertEqual(EmailOutbox.objects.count(), 2)
        self.assertFalse(EmailAttempt.objects.exists())

    def test_same_student_same_copy_concurrent_creation_has_one_winner(self):
        results = self.parallel([lambda: self.make("first").pk, lambda: self.make("second").pk])
        self.assertEqual(results.count("duplicate"), 1, results)
        self.assert_single_submission(("first", "second"))

    def test_same_student_different_copies_of_same_title_are_serialized(self):
        results = self.parallel([lambda: self.make("first", self.copy.pk).pk,
                                 lambda: self.make("second", self.spare.pk).pk])
        self.assertEqual(results.count("duplicate"), 1, results)
        self.assert_single_submission(("first", "second"))

    def api_create(self, pk, copy_id=None, by_resource=False, loan_type="borrow"):
        client = APIClient()
        client.force_authenticate(self.student)
        data = {"id": pk, "borrowerName": "Synthetic Student", "borrowerEmail": self.student.email,
                "borrowerPhone": "07123456789", "loanType": loan_type}
        data.update({"resourceId": self.resource.pk} if by_resource else {"bookCopyId": copy_id or self.copy.pk})
        response = client.post("/api/loans/", data, format="json")
        if response.status_code == 400:
            self.assertIn("already have an active", str(response.data))
        return response.status_code

    def test_public_resource_api_rejects_one_request_and_only_winner_reaches_webhook_boundary(self):
        with patch("library.views.send_library_webhook", return_value=False) as webhook:
            results = self.parallel([lambda: self.api_create("api-first", by_resource=True),
                                     lambda: self.api_create("api-second", by_resource=True)])
        self.assertCountEqual(results, [201, 400])
        self.assertEqual(webhook.call_count, 1)  # Mock only; no external request.
        self.assert_single_submission(("api-first", "api-second"))

    def test_explicit_copy_api_cannot_bypass_title_level_duplicate_check(self):
        results = self.parallel([lambda: self.api_create("api-first", self.copy.pk),
                                 lambda: self.api_create("api-second", self.spare.pk)])
        self.assertCountEqual(results, [201, 400])
        self.assert_single_submission(("api-first", "api-second"))

    def test_admin_save_and_public_api_share_same_guard(self):
        def admin_save():
            loan = Loan(id="admin-first", borrower=self.student, borrower_name="Synthetic Student",
                        borrower_email=self.student.email, borrower_phone="07123456789", book_copy=self.spare)
            request = RequestFactory().post("/admin/library/loan/add/")
            request.user = self.admin
            LoanAdmin(Loan, admin.site).save_model(request, loan, None, False)
            return 201

        results = self.parallel([admin_save, lambda: self.api_create("api-second")])
        self.assertEqual(results.count(201), 1, results)
        self.assertTrue(400 in results or "duplicate" in results, results)
        self.assert_single_submission(("admin-first", "api-second"))

    def test_notify_and_borrow_cannot_create_two_active_enrollments(self):
        results = self.parallel([lambda: self.make("notify-first", loan_type="notify").pk,
                                 lambda: self.make("borrow-second", self.spare.pk).pk])
        self.assertEqual(results.count("duplicate"), 1, results)
        self.assertEqual(self.active().count(), 1)
        winner = self.active().get()
        self.assertFalse(EmailOutbox.objects.exclude(loan=winner).exists())
        self.assertEqual(winner.email_messages.count(), 1 if winner.loan_type == "notify" else 2)
        self.assertFalse(EmailAttempt.objects.exists())

    def move(self, pk):
        client = APIClient()
        client.force_authenticate(self.admin)
        return client.patch(f"/api/loans/{pk}/", {"loanType": "borrow"}, format="json").status_code

    def test_move_to_queue_and_new_borrow_keep_existing_request_only(self):
        watcher = self.make("watcher", loan_type="notify")
        results = self.parallel([lambda: self.move(watcher.pk), lambda: self.api_create("new-request", self.spare.pk)])
        self.assertCountEqual(results, [200, 400])
        watcher.refresh_from_db()
        self.assertEqual((watcher.loan_type, watcher.status), ("borrow", "requested"))
        self.assertEqual(self.active().get().pk, watcher.pk)
        self.assertFalse(EmailOutbox.objects.filter(source_id="new-request").exists())
        self.assertEqual(watcher.email_messages.count(), 1)
        self.assertEqual(watcher.email_messages.get().status, "cancelled")
        self.assertFalse(EmailAttempt.objects.exists())

    def test_concurrent_move_to_queue_is_idempotent(self):
        watcher = self.make("watcher", loan_type="notify")
        self.assertEqual(self.parallel([lambda: self.move(watcher.pk), lambda: self.move(watcher.pk)]), [200, 200])
        self.assertEqual(self.active().count(), 1)
        self.assertEqual(self.active().get().loan_type, "borrow")
        self.assertEqual(watcher.email_messages.count(), 1)
        self.assertFalse(EmailAttempt.objects.exists())

    def test_guest_email_case_variations_are_serialized(self):
        results = self.parallel([
            lambda: self.make("guest-one", borrower=None, borrower_email="Guest@example.test").pk,
            lambda: self.make("guest-two", self.spare.pk, borrower=None, borrower_email="guest@example.test").pk,
        ])
        self.assertEqual(results.count("duplicate"), 1, results)
        loans = Loan.objects.filter(borrower_email__iexact="guest@example.test", status__in=Loan.active_statuses())
        self.assertEqual(loans.count(), 1)
        self.assertFalse(EmailOutbox.objects.exclude(loan=loans.get()).exists())

    def test_same_account_different_entered_email_still_counts_as_duplicate(self):
        results = self.parallel([
            lambda: self.make("one", borrower_email="one@example.test").pk,
            lambda: self.make("two", self.spare.pk, borrower_email="two@example.test").pk,
        ])
        self.assertEqual(results.count("duplicate"), 1, results)
        self.assert_single_submission(("one", "two"))

    def test_different_students_can_request_same_title(self):
        other = get_user_model().objects.create_user("other-student", email="other@example.test")
        results = self.parallel([
            lambda: self.make("one").pk,
            lambda: self.make("two", self.spare.pk, borrower=other, borrower_email=other.email).pk,
        ])
        self.assertCountEqual(results, ["one", "two"])
        self.assertEqual(Loan.objects.filter(status__in=Loan.active_statuses()).count(), 2)

    def test_same_student_can_request_different_titles(self):
        resource = Resource.objects.create(id="other-title", title="Other", author="Author", category=self.resource.category)
        copy = BookCopy.objects.create(resource=resource, accession_number="OTHER-1")
        self.assertCountEqual(self.parallel([lambda: self.make("one").pk, lambda: self.make("two", copy.pk).pk]), ["one", "two"])

    def test_new_request_allowed_after_each_terminal_status(self):
        for state in ("cancelled", "returned", "notify"):
            with self.subTest(state=state):
                loan = self.make(f"old-{state}", loan_type="notify" if state == "notify" else "borrow")
                if state == "returned":
                    loan.status = "borrowed"
                    with patch("library.models.timezone.now", return_value=NOW):
                        loan.save()
                    loan.returned_at, loan.return_condition = NOW, "good"
                loan.status = state
                loan.save()
                newer = self.make(f"new-{state}")
                self.assertEqual(self.active().get().pk, newer.pk)
                newer.status = "cancelled"
                newer.save()

    def test_all_existing_active_statuses_prevent_another_request(self):
        for state in Loan.active_statuses():
            with self.subTest(state=state), transaction.atomic():
                loan = self.make(f"active-{state}")
                if state == "reserved":
                    # Create reserved directly through the supported model path.
                    loan.status = "cancelled"
                    loan.save()
                    loan = self.make(f"reservation-{state}", status="reserved")
                elif state in ("approved", "borrowed", "overdue"):
                    loan.status = "approved" if state == "approved" else "borrowed"
                    with patch("library.models.timezone.now", return_value=NOW):
                        loan.save()
                    if state == "overdue":
                        loan.status = "overdue"
                        loan.save()
                before = EmailOutbox.objects.count()
                with self.assertRaisesMessage(ValidationError, "already have an active"):
                    self.make(f"duplicate-{state}", self.spare.pk)
                self.assertEqual(EmailOutbox.objects.count(), before)
                transaction.set_rollback(True)

    def test_bulk_create_cannot_bypass_save_guard(self):
        with self.assertRaises(ValidationError):
            Loan.objects.bulk_create([Loan(id="bulk", borrower=self.student, book_copy=self.copy)])
        self.assertFalse(Loan.objects.exists())
        self.assertFalse(EmailOutbox.objects.exists())

    def test_second_transaction_waits_until_first_commit_then_rechecks(self):
        first_validated, release, second_started = Event(), Event(), Event()
        original = Loan.clean
        ids = {}

        def paused_clean(loan):
            original(loan)
            if loan.pk == "first":
                first_validated.set()
                if not release.wait(timeout=15):
                    raise RuntimeError("Synthetic timeout")

        def create(pk, copy_id):
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_backend_pid()")
                        ids[pk] = cursor.fetchone()[0]
                    if pk == "second":
                        second_started.set()
                    return self.make(pk, copy_id).pk
            except ValidationError as exc:
                self.assertIn("already have an active", str(exc))
                return "duplicate"
            finally:
                connections.close_all()

        with patch.object(Loan, "clean", new=paused_clean), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(create, "first", self.copy.pk)
            try:
                self.assertTrue(first_validated.wait(timeout=15))
                second = pool.submit(create, "second", self.spare.pk)
                self.assertTrue(second_started.wait(timeout=15))
                blocked = False
                until = monotonic() + 5
                while monotonic() < until:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [ids["second"]])
                        blocked = ids["first"] in cursor.fetchone()[0]
                    if blocked:
                        break
                    sleep(0.02)
                self.assertTrue(blocked, "Second isolated transaction must wait on the resource mutex")
                self.assertFalse(second.done())
            finally:
                release.set()
            self.assertEqual(first.result(timeout=15), "first")
            self.assertEqual(second.result(timeout=15), "duplicate")
        self.assert_single_submission(("first", "second"))

    def test_database_rejects_race_even_without_resource_lock(self):
        # This formerly reproduced two rows; 0025 must now stop the loser.
        barrier = Barrier(2)
        original = Loan.clean

        def both_validate_before_insert(loan):
            original(loan)
            barrier.wait(timeout=15)

        def create(pair):
            try:
                with transaction.atomic():
                    return self.make(*pair).pk
            except ValidationError as exc:
                self.assertIn("already have an active", str(exc))
                return "duplicate"
            finally:
                connections.close_all()

        with patch.object(Resource, "lock_availability", return_value=None), \
                patch.object(Loan, "clean", new=both_validate_before_insert), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (("control-one", self.copy.pk), ("control-two", self.spare.pk))))
        self.assertEqual(results.count("duplicate"), 1, results)
        self.assert_single_submission(("control-one", "control-two"))
