"""0025 regressions: real PostgreSQL, including clients bypassing ALL model hooks."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TransactionTestCase

from . import test_email_system as fixtures
from .admin import BookCopyAdmin, DeviceLocalModelAdmin, LoanAdmin
from .email_models import EmailAttempt, EmailOutbox
from .models import BookCopy, Loan, Resource
from . import test_duplicate_borrow_requests as existing


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL with migration 0025 applied.")
class LoanDatabaseIntegrityTests(TransactionTestCase):
    new_loan = fixtures.EmailSystemTests.new_loan
    make = existing.DuplicateBorrowRequestTests.make
    api_create = existing.DuplicateBorrowRequestTests.api_create

    def setUp(self):
        fixtures.EmailSystemTests.setUp(self)
        self.loan.status = "cancelled"
        self.loan.save()
        EmailOutbox.objects.all().delete()
        self.spare = BookCopy.objects.create(resource=self.resource, accession_number="MAIL-2")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_trigger WHERE tgname='library_loan_derive_resource'")
            self.assertIsNotNone(cursor.fetchone(), "Run with migrations, NOT --schema-only")

    def raw_insert(self, pk, **overrides):
        """Clone a synthetic closed row with SQL; no save/clean/events involved."""
        overrides = {"id": pk, "status": "requested", **overrides}
        columns = [field.column for field in Loan._meta.concrete_fields]
        values, params = [], []
        for column in columns:
            if column in overrides:
                values.append("%s")
                params.append(overrides[column])
            else:
                values.append(connection.ops.quote_name(column))
        sql = "INSERT INTO library_loan ({}) SELECT {} FROM library_loan WHERE id=%s".format(
            ",".join(map(connection.ops.quote_name, columns)), ",".join(values))
        with connection.cursor() as cursor:
            cursor.execute(sql, [*params, self.loan.pk])
        return pk

    def raw_update(self, pk, **values):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE library_loan SET " + ",".join(
                f"{connection.ops.quote_name(field)}=%s" for field in values) + " WHERE id=%s",
                [*values.values(), pk])

    def blocked(self, operation, names=("lib_loan_active_account", "lib_loan_active_email")):
        before = (EmailOutbox.objects.count(), EmailAttempt.objects.count())
        with self.assertRaises(IntegrityError) as result:
            with transaction.atomic():
                operation()
        self.assertIn(result.exception.__cause__.diag.constraint_name, names)
        self.assertEqual((EmailOutbox.objects.count(), EmailAttempt.objects.count()), before)

    def other_copy(self):
        resource = Resource.objects.create(id="different-title", title="Other", author="Author", category=self.resource.category)
        return BookCopy.objects.create(resource=resource, accession_number="OTHER-1")

    def assert_no_duplicates(self):
        with connection.cursor() as cursor:
            cursor.execute("""SELECT count(*) FROM (
                SELECT c.resource_id, l.borrower_id FROM library_loan l
                JOIN library_bookcopy c ON c.id=l.book_copy_id
                WHERE l.status IN ('requested','reserved','approved','borrowed','overdue')
                AND l.borrower_id IS NOT NULL GROUP BY c.resource_id,l.borrower_id HAVING count(*)>1
            ) duplicates""")
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("""SELECT count(*) FROM library_loan l JOIN library_bookcopy c
                ON c.id=l.book_copy_id WHERE l.identity_resource_id IS DISTINCT FROM c.resource_id""")
            self.assertEqual(cursor.fetchone()[0], 0)

    def concurrent(self, operations, isolation="READ COMMITTED"):
        barrier = Barrier(len(operations))

        def run(operation):
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
                        cursor.execute("SET LOCAL lock_timeout='10s'")
                        cursor.execute("SELECT pg_backend_pid(), txid_current()")
                        backend = cursor.fetchone()
                    barrier.wait(timeout=15)
                    operation()
                return "committed", backend
            except IntegrityError as exc:
                self.assertIn(exc.__cause__.diag.constraint_name,
                              ("lib_loan_active_account", "lib_loan_active_email"))
                return "duplicate", backend
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            results = list(pool.map(run, operations))
        self.assertEqual(len({item[1][0] for item in results}), len(operations))
        self.assertEqual(len({item[1][1] for item in results}), len(operations))
        self.assertCountEqual([item[0] for item in results], ["committed", "duplicate"])
        self.assert_no_duplicates()

    def test_raw_insert_different_copies_rejected(self):
        self.raw_insert("one")
        self.blocked(lambda: self.raw_insert("two", book_copy_id=self.spare.pk))

    def test_raw_insert_same_copy_rejected(self):
        self.raw_insert("one")
        self.blocked(lambda: self.raw_insert("two"))

    def test_same_account_changing_entered_email_cannot_bypass(self):
        self.raw_insert("one", borrower_email="")
        self.blocked(lambda: self.raw_insert("two", borrower_email="another@example.test"))

    def test_guest_email_normalized_without_rewriting_history(self):
        self.raw_insert("one", borrower_id=None, borrower_email=" Guest@Example.test ")
        self.blocked(lambda: self.raw_insert("two", borrower_id=None, borrower_email="guest@example.test"))
        self.assertEqual(Loan.objects.get(pk="one").borrower_email, " Guest@Example.test ")

    def test_guest_then_linked_same_email_cannot_bypass(self):
        self.raw_insert("guest", borrower_id=None)
        self.blocked(lambda: self.raw_insert("linked"))

    def test_linked_then_guest_same_email_cannot_bypass(self):
        self.raw_insert("linked")
        self.blocked(lambda: self.raw_insert("guest", borrower_id=None))

    def test_two_linked_accounts_sharing_email_are_not_a_bypass(self):
        other = get_user_model().objects.create_user("other", email=self.student.email)
        self.raw_insert("one")
        self.blocked(lambda: self.raw_insert("two", borrower_id=other.pk))

    def test_distinct_students_allowed(self):
        other = get_user_model().objects.create_user("other", email="other@example.test")
        self.raw_insert("one")
        self.raw_insert("two", borrower_id=other.pk, borrower_email=other.email)
        self.assert_no_duplicates()

    def test_same_student_distinct_resources_allowed(self):
        other = self.other_copy()
        self.raw_insert("one")
        self.raw_insert("two", book_copy_id=other.pk)
        self.assert_no_duplicates()

    def test_active_unlinked_blank_identity_rejected(self):
        for email in ("", "   "):
            with self.subTest(email=repr(email)):
                self.blocked(lambda: self.raw_insert("invalid", borrower_id=None, borrower_email=email),
                             ("lib_loan_active_identity",))

    def test_null_email_cannot_bypass_not_null_column(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.raw_insert("null", borrower_id=None, borrower_email=None)

    def test_closed_anonymous_history_is_allowed(self):
        for status in ("returned", "cancelled", "notify"):
            self.raw_insert(status, status=status, borrower_id=None, borrower_email="")

    def test_every_active_status_is_protected(self):
        for status in Loan.active_statuses():
            with self.subTest(status=status), transaction.atomic():
                self.raw_insert("one", status=status)
                self.blocked(lambda: self.raw_insert("two", book_copy_id=self.spare.pk))
                transaction.set_rollback(True)

    def test_reborrow_after_return_cancel_and_notify_completion(self):
        for status in ("returned", "cancelled", "notify"):
            with self.subTest(status=status), transaction.atomic():
                self.raw_insert("old")
                self.raw_update("old", status=status)
                self.raw_insert("new", book_copy_id=self.spare.pk)
                self.assert_no_duplicates()
                transaction.set_rollback(True)

    def test_notify_requested_still_blocks_duplicate_borrow(self):
        self.raw_insert("waiting", loan_type="notify")
        self.blocked(lambda: self.raw_insert("borrow"))
        self.raw_update("waiting", loan_type="borrow")
        self.assertEqual(Loan.objects.get(pk="waiting").status, "requested")

    def test_sql_reactivation_cannot_bypass(self):
        self.raw_insert("active")
        self.blocked(lambda: self.raw_update(self.loan.pk, status="requested"))

    def test_sql_book_copy_reassignment_cannot_bypass(self):
        other = self.other_copy()
        self.raw_insert("one")
        self.raw_insert("two", book_copy_id=other.pk)
        self.blocked(lambda: self.raw_update("two", book_copy_id=self.spare.pk))
        self.assert_no_duplicates()

    def test_sql_borrower_reassignment_cannot_bypass(self):
        other = get_user_model().objects.create_user("other", email="other@example.test")
        self.raw_insert("one")
        self.raw_insert("two", borrower_id=other.pk, borrower_email=other.email)
        self.blocked(lambda: self.raw_update("two", borrower_id=self.student.pk))

    def test_sql_email_update_cannot_bypass(self):
        self.raw_insert("one", borrower_id=None)
        self.raw_insert("two", borrower_id=None, borrower_email="other@example.test")
        self.blocked(lambda: self.raw_update("two", borrower_email=" STUDENT@EXAMPLE.TEST "))

    def test_forged_resource_on_insert_is_overwritten_and_rejected(self):
        self.raw_insert("one")
        self.blocked(lambda: self.raw_insert("two", identity_resource_id="forged"))

    def test_forged_resource_on_update_cannot_open_a_slot(self):
        self.raw_insert("one")
        self.raw_update("one", identity_resource_id="forged")
        self.assertEqual(Loan.objects.get(pk="one").identity_resource_id, self.resource.pk)
        self.blocked(lambda: self.raw_insert("two"))

    def test_sql_copy_resource_move_rejected_when_it_merges_duplicates(self):
        other = self.other_copy()
        self.raw_insert("one")
        self.raw_insert("two", book_copy_id=other.pk)
        self.blocked(lambda: BookCopy.objects.filter(pk=other.pk).update(resource=self.resource))
        other.refresh_from_db()
        self.assertEqual(other.resource_id, "different-title")
        self.assert_no_duplicates()

    def test_safe_copy_resource_move_cascades_all_loan_keys(self):
        other = self.other_copy()
        self.raw_insert("one")
        BookCopy.objects.filter(pk=self.copy.pk).update(resource_id=other.resource_id)
        self.assertEqual(set(Loan.objects.values_list("identity_resource_id", flat=True)), {other.resource_id})
        self.blocked(lambda: self.raw_insert("two", book_copy_id=other.pk))
        self.assert_no_duplicates()

    def test_orm_base_save_without_clean_or_loan_save_still_rejected(self):
        self.raw_insert("one")
        instance = Loan(id="two", borrower=self.student, book_copy=self.spare)
        self.blocked(lambda: models.Model.save(instance, force_insert=True))

    def test_orm_bulk_identity_update_still_rejected(self):
        other = get_user_model().objects.create_user("other", email="other@example.test")
        self.raw_insert("one")
        self.raw_insert("two", borrower_id=other.pk, borrower_email=other.email)
        self.blocked(lambda: Loan.objects.filter(pk="two").update(borrower_id=self.student.pk))

    def test_model_translates_database_rejection_and_rolls_back_events(self):
        self.raw_insert("one")
        with patch.object(Loan, "full_clean", return_value=None):
            with self.assertRaisesMessage(ValidationError, "already have an active"):
                self.make("two", self.spare.pk)
        self.assertFalse(Loan.objects.filter(pk="two").exists())
        self.assertFalse(EmailOutbox.objects.exists())
        self.assertFalse(EmailAttempt.objects.exists())

    def test_api_database_rejection_is_400_not_500(self):
        self.raw_insert("one")
        with patch.object(Loan, "full_clean", return_value=None):
            self.assertEqual(self.api_create("two", self.spare.pk), 400)
        self.assertFalse(EmailOutbox.objects.exists())
        self.assertFalse(EmailAttempt.objects.exists())

    def test_admin_save_translates_database_rejection(self):
        self.raw_insert("one")
        instance = Loan(id="two", borrower=self.student, book_copy=self.spare)
        request = RequestFactory().post("/admin/library/loan/add/")
        request.user = self.admin
        with patch.object(Loan, "full_clean", return_value=None):
            with self.assertRaisesMessage(ValidationError, "already have an active"):
                LoanAdmin(Loan, admin.site).save_model(request, instance, None, False)
        self.assertFalse(EmailOutbox.objects.exists())

    def test_admin_form_surfaces_database_race_as_message(self):
        self.raw_insert("one")
        request = RequestFactory().post("/admin/library/loan/add/")
        model_admin = LoanAdmin(Loan, admin.site)
        def actual_database_failure(*args, **kwargs):
            self.make("two", self.spare.pk)
        with patch.object(Loan, "full_clean", return_value=None), \
                patch.object(DeviceLocalModelAdmin, "changeform_view", side_effect=actual_database_failure), \
                patch.object(model_admin, "message_user") as message:
            self.assertEqual(model_admin.changeform_view(request).status_code, 302)
            self.assertIn("already have an active", message.call_args.args[1])
        self.assertFalse(EmailOutbox.objects.exists())

    def test_admin_copy_move_surfaces_conflict(self):
        other = self.other_copy()
        self.raw_insert("one")
        self.raw_insert("two", book_copy_id=other.pk)
        other.resource = self.resource
        request = RequestFactory().post(f"/admin/library/bookcopy/{other.pk}/change/")
        model_admin = BookCopyAdmin(BookCopy, admin.site)
        with patch.object(DeviceLocalModelAdmin, "changeform_view", side_effect=lambda *a, **k: other.save()), \
                patch.object(model_admin, "message_user") as message:
            self.assertEqual(model_admin.changeform_view(request).status_code, 302)
            self.assertIn("already have an active", message.call_args.args[1])
        self.assert_no_duplicates()

    def test_raw_concurrent_different_copies(self):
        self.concurrent([lambda: self.raw_insert("one"), lambda: self.raw_insert("two", book_copy_id=self.spare.pk)])

    def test_raw_concurrent_same_copy(self):
        self.concurrent([lambda: self.raw_insert("one"), lambda: self.raw_insert("two")])

    def test_raw_concurrent_guest_case_and_spaces(self):
        self.concurrent([lambda: self.raw_insert("one", borrower_id=None, borrower_email=" Guest@EXAMPLE.test "),
                         lambda: self.raw_insert("two", borrower_id=None, borrower_email="guest@example.test", book_copy_id=self.spare.pk)])

    def test_raw_concurrent_repeatable_read_does_not_depend_on_snapshot_visibility(self):
        self.concurrent([lambda: self.raw_insert("one"), lambda: self.raw_insert("two", book_copy_id=self.spare.pk)],
                        isolation="REPEATABLE READ")

    def test_copy_resource_move_racing_insert(self):
        other = self.other_copy()
        self.raw_insert("moving", book_copy_id=other.pk)
        self.concurrent([lambda: self.raw_insert("new"),
                         lambda: BookCopy.objects.filter(pk=other.pk).update(resource_id=self.resource.pk)])

    def test_two_sql_updates_compete_for_same_identity(self):
        self.raw_insert("one", borrower_id=None, borrower_email="one@example.test")
        self.raw_insert("two", borrower_id=None, borrower_email="two@example.test", book_copy_id=self.spare.pk)
        self.concurrent([lambda: self.raw_update("one", borrower_email="target@example.test"),
                         lambda: self.raw_update("two", borrower_email="target@example.test")])

    def test_partial_save_recomputes_key_from_persisted_copy(self):
        other = self.other_copy()
        instance = Loan.objects.get(pk=self.loan.pk)
        instance.book_copy = other
        instance.notes = "Synthetic note"
        instance.save(update_fields=["notes"])
        instance.refresh_from_db()
        self.assertEqual(instance.book_copy_id, self.copy.pk)
        self.assertEqual(instance.identity_resource_id, self.resource.pk)

    def test_preflight_stops_on_duplicates_without_altering_history(self):
        old = ("library", "0024_phase2_timezones_email")
        new = ("library", "0025_active_loan_identity")
        # Roll back this entire synthetic downgrade/upgrade experiment, even if
        # an assertion fails; other tests always see the installed protection.
        with transaction.atomic():
            MigrationExecutor(connection).migrate([old])
            executor = MigrationExecutor(connection)
            OldLoan = executor.loader.project_state([old]).apps.get_model("library", "Loan")
            for pk in ("duplicate-one", "duplicate-two"):
                OldLoan.objects.create(id=pk, borrower_id=self.student.pk, book_copy_id=self.copy.pk,
                                       borrower_email=self.student.email)
            before = list(OldLoan.objects.order_by("pk").values())
            with self.assertRaisesMessage(RuntimeError, "stopped without repairing data"):
                MigrationExecutor(connection).migrate([new])
            self.assertEqual(list(OldLoan.objects.order_by("pk").values()), before)
            with connection.cursor() as cursor:
                columns = {col.name for col in connection.introspection.get_table_description(cursor, "library_loan")}
                self.assertNotIn("identity_resource_id", columns)
            transaction.set_rollback(True)

    def test_preflight_detects_guest_duplicates_and_missing_identity(self):
        migration = import_module("library.migrations.0025_active_loan_identity")
        old = ("library", "0024_phase2_timezones_email")
        with transaction.atomic():
            MigrationExecutor(connection).migrate([old])
            executor = MigrationExecutor(connection)
            OldLoan = executor.loader.project_state([old]).apps.get_model("library", "Loan")
            OldLoan.objects.create(id="guest1", book_copy_id=self.copy.pk, borrower_email=" Guest@example.test ")
            OldLoan.objects.create(id="guest2", book_copy_id=self.spare.pk, borrower_email="guest@example.test")
            OldLoan.objects.create(id="noidentity", book_copy_id=self.copy.pk, borrower_email="   ")
            with connection.schema_editor() as editor:
                with self.assertRaisesMessage(RuntimeError, "duplicate email/resource groups=1, active loans without identity=1"):
                    migration.preflight(executor.loader.project_state([old]).apps, editor)
            transaction.set_rollback(True)

    def test_migration_backfill_preserves_existing_dates_and_emails(self):
        old = ("library", "0024_phase2_timezones_email")
        new = ("library", "0025_active_loan_identity")
        with transaction.atomic():
            MigrationExecutor(connection).migrate([old])
            executor = MigrationExecutor(connection)
            OldLoan = executor.loader.project_state([old]).apps.get_model("library", "Loan")
            OldLoan.objects.create(id="historical", borrower_id=self.student.pk, book_copy_id=self.copy.pk,
                                   status="returned", borrower_email=" STUDENT@example.test ", due_date="2020-01-01",
                                   approved_at=fixtures.NOW, delivery_days=5)
            OldLoan.objects.create(id="active", borrower_id=self.student.pk, book_copy_id=self.spare.pk)
            before = list(OldLoan.objects.order_by("pk").values())
            # The surrounding test transaction is only for cleanup. Complete
            # historical FK checks before DDL, as a real pre-migration commit does.
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            MigrationExecutor(connection).migrate([new])
            after = list(Loan.objects.order_by("pk").values())
            for row in after:
                self.assertEqual(row.pop("identity_resource_id"), self.resource.pk)
            self.assertEqual(before, after)
            self.blocked(lambda: self.raw_insert("duplicate"))
            transaction.set_rollback(True)
