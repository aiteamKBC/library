from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone as dt_timezone
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
import uuid

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, connections, transaction
from django.db.models.deletion import ProtectedError
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, RequestFactory, override_settings
from django.utils import timezone

from . import tests as delivery_tests
from .admin import LoanAdmin, EmailOutboxAdmin, EmailAttemptAdmin
from .models import Loan, UserProfile, BookRequest, NotificationLog, EmailOutbox, EmailAttempt
from .timezone_preferences import save_own_timezone


UTC = dt_timezone.utc
NOW = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)
LOCAL_SETTINGS = dict(LIBRARY_USER_LOCAL_POLICY_ENABLED=True, LIBRARY_USER_LOCAL_CUTOVER_AT="2026-01-01T00:00:00Z")


class Phase2Tests(TestCase):
    setUp = delivery_tests.LoanDeliveryPeriodTests.setUp
    approve = delivery_tests.LoanDeliveryPeriodTests.approve
    confirmed_at = NOW

    def preference(self, zone="Africa/Cairo", source="browser"):
        return save_own_timezone(self.student, zone, source=source, explicit=source == "manual")[0]

    def outbox(self, **kwargs):
        values = dict(event_id=uuid.uuid4(), event_type="borrow_confirmed", message_kind="event",
            loan=self.loan, recipient=self.student, recipient_key=f"user:{self.student.pk}",
            recipient_email="synthetic@example.com", recipient_role="student", recipient_timezone="Africa/Cairo",
            template_key="borrow_confirmed", idempotency_key=str(uuid.uuid4()), status="pending")
        values.update(kwargs)
        return EmailOutbox.objects.create(**values)

    def test_browser_updates_persist_and_explicit_preference_is_not_overwritten(self):
        self.client.force_authenticate(self.student)
        for zone in ("Africa/Cairo", "America/New_York"):
            response = self.client.post("/api/auth/timezone-observation/", {"timeZone": zone}, format="json")
            self.assertTrue(response.data["saved"])
            self.assertEqual(UserProfile.objects.get(user=self.student).time_zone, zone)
        response = self.client.put("/api/auth/timezone-preference/", {"timeZone": "Asia/Dubai", "source": "manual"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post("/api/auth/timezone-observation/", {"timeZone": "Europe/London"}, format="json")
        self.assertEqual(response.data["status"], "manual_preserved")
        self.assertFalse(response.data["saved"])
        self.assertEqual(response.data["savedTimeZone"], "Asia/Dubai")
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.data["user"]["timeZoneSource"], "manual")
        self.assertEqual(response.data["user"]["timeZoneStatus"], "valid")
        response = self.client.put("/api/auth/timezone-preference/", {"timeZone": "Europe/London", "source": "browser"}, format="json")
        self.assertEqual(response.data["user"]["timeZoneSource"], "browser")

    def test_invalid_or_cross_user_preference_cannot_be_saved(self):
        self.preference()
        self.client.force_authenticate(self.student)
        for body in ({"timeZone": "Mars/Invalid", "source": "manual"},
                     {"timeZone": "Asia/Dubai", "source": "manual", "userId": self.staff.pk},
                     {"timeZone": "Asia/Dubai", "source": "unknown"}):
            self.assertEqual(self.client.put("/api/auth/timezone-preference/", body, format="json").status_code, 400)
        self.assertFalse(UserProfile.objects.filter(user=self.staff).exists())
        self.assertEqual(UserProfile.objects.get(user=self.student).time_zone, "Africa/Cairo")

    def test_out_of_order_browser_observations_do_not_replace_newer_preference(self):
        save_own_timezone(self.student, "Asia/Dubai", source="browser", observed_at=NOW)
        profile, result = save_own_timezone(self.student, "America/New_York", source="browser", observed_at=NOW - timedelta(seconds=1))
        self.assertEqual(result, "stale_ignored")
        self.assertEqual(profile.time_zone, "Asia/Dubai")

    @override_settings(**LOCAL_SETTINGS)
    def test_new_policy_freezes_saved_student_zone_not_admin_zone_or_device(self):
        self.preference("Africa/Cairo")
        save_own_timezone(self.staff, "America/New_York", source="manual", explicit=True)
        response = self.approve(2)
        self.assertEqual(response.status_code, 200, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.calculation_policy, "user_local_v1")
        self.assertEqual(self.loan.calculation_timezone, "Africa/Cairo")
        self.assertEqual(self.loan.operational_timezone, "Africa/Cairo")
        self.assertEqual(self.loan.confirmation_local_date, date(2026, 7, 16))
        self.assertEqual(self.loan.due_date, date(2026, 8, 17))
        self.assertEqual(self.loan.approved_at, NOW)
        original_revision = self.loan.email_deadline_revision
        self.preference("Asia/Dubai")
        self.loan.notes = "Travel is presentation/preference only"
        self.loan.save(update_fields=["notes"])
        self.assertEqual(self.loan.due_date, date(2026, 8, 17))
        self.assertEqual(self.loan.email_deadline_revision, original_revision)
        self.loan.delivery_days = 5
        self.loan.save(update_fields=["delivery_days"])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, date(2026, 8, 20))
        self.assertEqual(self.loan.calculation_timezone, "Africa/Cairo")
        self.assertEqual(self.loan.approved_at, NOW)

    @override_settings(**LOCAL_SETTINGS)
    def test_missing_student_timezone_or_account_blocks_confirmation_without_guess(self):
        response = self.approve(0)
        self.assertEqual(response.status_code, 400, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, "requested")
        self.assertIsNone(self.loan.calculation_policy)
        self.loan.borrower = None
        self.loan.save(update_fields=["borrower"])
        self.assertEqual(self.approve(0).status_code, 400)

    @override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=True, LIBRARY_USER_LOCAL_CUTOVER_AT="")
    def test_enabling_without_approved_cutover_fails_closed(self):
        self.preference()
        response = self.approve(0)
        self.assertEqual(response.status_code, 400)
        self.assertIn("LIBRARY_USER_LOCAL_CUTOVER_AT", str(response.data))

    @override_settings(**LOCAL_SETTINGS)
    def test_new_policy_preview_matches_save_and_overdue_uses_frozen_calendar(self):
        self.preference("America/New_York")
        with patch("library.models.timezone.now", return_value=NOW):
            preview = self.client.get("/api/loans/loan/return-date-preview/?deliveryDays=0")
        result = self.approve(0)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(preview.data["dueDate"], result.data["dueDate"])
        self.assertEqual(result.data["dueDate"], "2026-08-14")
        self.preference("Asia/Dubai")
        for instant, count in ((datetime(2026, 8, 15, 1, tzinfo=UTC), 0),
                               (datetime(2026, 8, 15, 4, tzinfo=UTC), 1)):
            with patch("library.models.timezone.now", return_value=instant):
                result = self.client.post("/api/loans/process_overdue/", {}, format="json")
            self.assertEqual(result.data["count"], count)

    def test_unclassified_history_is_preserved_and_recalculation_is_blocked(self):
        Loan._base_manager.filter(pk=self.loan.pk).update(status="borrowed", approved_at=NOW, borrowed_at=NOW)
        self.loan.refresh_from_db()
        self.loan.notes = "Safe historical note"
        self.loan.save(update_fields=["notes"])
        before = self.loan.due_date
        self.loan.delivery_days = 3
        with self.assertRaisesMessage(ValidationError, "unclassified"):
            self.loan.save(update_fields=["delivery_days"])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before)
        self.assertIsNone(self.loan.calculation_policy)

    def test_policy_snapshot_is_immutable_and_cannot_be_changed_by_api(self):
        self.assertEqual(self.approve(0).status_code, 200)
        self.loan.refresh_from_db()
        self.loan.calculation_timezone = "Asia/Dubai"
        with self.assertRaises(ValidationError):
            self.loan.save()
        response = self.client.patch("/api/loans/loan/", {"calculationTimeZone": "Asia/Dubai", "emailDeadlineRevision": 999}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotEqual(response.data["calculationTimeZone"], "Asia/Dubai")
        self.assertNotEqual(response.data["emailDeadlineRevision"], 999)

    def test_revision_changes_once_for_final_persisted_date_only(self):
        self.assertEqual(self.loan.email_deadline_revision, 0)
        self.assertEqual(self.approve(0).status_code, 200)
        self.loan.refresh_from_db()
        revision = self.loan.email_deadline_revision
        self.assertEqual(revision, 1)
        for payload in ({"notes": "A"}, {"deliveryDays": 0}, {"notes": "B", "deliveryDays": 0}):
            response = self.client.patch("/api/loans/loan/", payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["emailDeadlineRevision"], revision)
        self.loan.delivery_days = 3
        self.loan.save(update_fields=["delivery_days"])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.email_deadline_revision, revision + 1)
        self.loan.due_date += timedelta(days=1)
        self.loan.save(update_fields=["due_date"])
        self.assertEqual(self.loan.email_deadline_revision, revision + 2)

    def test_confirmation_with_identical_final_date_does_not_increment_revision(self):
        Loan._base_manager.filter(pk=self.loan.pk).update(due_date=date(2026, 8, 15))
        self.assertEqual(self.approve(0).status_code, 200)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, date(2026, 8, 15))
        self.assertEqual(self.loan.email_deadline_revision, 0)

    def test_positional_update_fields_persists_deadline_and_revision_together(self):
        self.approve(0)
        self.loan.refresh_from_db()
        before = self.loan.email_deadline_revision
        self.loan.delivery_days = 2
        self.loan.save(False, False, None, ["delivery_days"])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.email_deadline_revision, before + 1)
        self.assertEqual(self.loan.due_date, date(2026, 8, 17))
        self.loan.due_date += timedelta(days=10)
        self.loan.notes = "Unsaved deadline must not count"
        self.loan.save(update_fields=["notes"])
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.email_deadline_revision, before + 1)

    def test_stale_duplicate_partial_edit_does_not_increment_twice_or_lose_updates(self):
        self.approve(0)
        a, b = Loan.objects.get(pk=self.loan.pk), Loan.objects.get(pk=self.loan.pk)
        baseline = a.email_deadline_revision
        a.delivery_days = 3
        a.save(update_fields=["delivery_days"])
        b.delivery_days = 3
        b.save(update_fields=["delivery_days"])
        b.refresh_from_db()
        self.assertEqual(b.email_deadline_revision, baseline + 1)
        stale = Loan.objects.get(pk=b.pk)
        b.delivery_days = 5
        b.save(update_fields=["delivery_days"])
        stale.delivery_days = 4
        with self.assertRaisesMessage(ValidationError, "concurrently"):
            stale.save(update_fields=["delivery_days"])
        b.refresh_from_db()
        self.assertEqual(b.delivery_days, 5)
        self.assertEqual(b.email_deadline_revision, baseline + 2)

    def test_bulk_deadline_or_status_mutations_are_guarded(self):
        for values in ({"due_date": date(2027, 1, 1)}, {"delivery_days": 3}, {"status": "borrowed"}, {"email_deadline_revision": 999}):
            with self.assertRaises(ValidationError):
                Loan.objects.filter(pk=self.loan.pk).update(**values)
        self.loan.delivery_days = 2
        with self.assertRaises(ValidationError):
            Loan.objects.bulk_update([self.loan], ["delivery_days"])

    def test_admin_save_uses_same_revision_logic_and_keeps_metadata_readonly(self):
        self.approve(0)
        self.loan.refresh_from_db()
        before = self.loan.email_deadline_revision
        request = RequestFactory().post("/admin/library/loan/loan/change/")
        request.user = self.staff
        model_admin = LoanAdmin(Loan, admin.site)
        self.loan.delivery_days = 2
        model_admin.save_model(request, self.loan, None, True)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.email_deadline_revision, before + 1)
        self.assertIn("email_deadline_revision", model_admin.get_readonly_fields(request, self.loan))

    def test_email_fk_types_sources_and_history_survive_source_deletion(self):
        message = self.outbox()
        self.assertEqual(EmailOutbox._meta.get_field("loan").target_field.max_length, 50)
        self.assertEqual(EmailOutbox._meta.get_field("book_request").target_field.max_length, 50)
        self.assertEqual(message.source_id, self.loan.pk)
        original = self.loan.pk
        self.loan.delete()
        message.refresh_from_db()
        self.assertIsNone(message.loan_id)
        self.assertEqual(message.source_id, original)
        self.assertEqual(message.recipient_email, "synthetic@example.com")

    def test_attempt_fk_is_mandatory_unique_and_history_is_protected(self):
        message = self.outbox()
        attempt = EmailAttempt.objects.create(message=message, attempt_number=1, result="started")
        with self.assertRaises(ProtectedError):
            message.delete()
        with self.assertRaises(ValidationError):
            attempt.delete()
        with self.assertRaises(ValidationError):
            EmailAttempt.objects.filter(pk=attempt.pk).delete()
        for row in (EmailAttempt(message=message, attempt_number=1, result="started"),
                    EmailAttempt(message=message, attempt_number=0, result="started"),
                    EmailAttempt(message=None, attempt_number=2, result="started")):
            with self.subTest(number=row.attempt_number), self.assertRaises(IntegrityError), transaction.atomic():
                EmailAttempt.objects.bulk_create([row])

    def test_outbox_database_constraints_reject_invalid_rows_and_duplicate_key(self):
        message = self.outbox()
        for values in ({"idempotency_key": message.idempotency_key}, {"idempotency_key": ""},
                       {"status": "pending", "recipient_timezone": None},
                       {"status": "claimed"}, {"message_kind": "reminder"}, {"template_version": 0}):
            row = self.outbox()
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                EmailOutbox.objects.filter(pk=row.pk).update(**values)

    def test_reminder_snapshots_and_lease_can_be_stored_without_sending(self):
        message = self.outbox(message_kind="reminder", due_date_snapshot=date(2026, 8, 15),
            deadline_revision=3, reminder_local_date=date(2026, 8, 15),
            available_at=NOW, expires_at=NOW + timedelta(days=1))
        message.status = "claimed"
        message.lease_token = uuid.uuid4()
        message.lease_expires_at = NOW + timedelta(minutes=2)
        message.worker_id = "synthetic-test-worker"
        message.save()
        self.assertEqual(EmailAttempt.objects.count(), 0)
        self.assertEqual(message.deadline_revision, 3)

    def test_outbox_cannot_have_both_sources_and_book_request_history_survives(self):
        request = BookRequest.objects.create(id="synthetic-request", student_name="Synthetic", student_email="synthetic@example.com",
                                            book_title="Synthetic", category="Synthetic")
        message = self.outbox()
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmailOutbox.objects.filter(pk=message.pk).update(book_request=request)
        message = self.outbox(loan=None, book_request=request)
        request.delete()
        message.refresh_from_db()
        self.assertIsNone(message.book_request_id)
        self.assertEqual(message.source_id, "synthetic-request")

    def test_email_timestamps_require_explicit_offsets_and_errors_are_sanitized(self):
        with self.assertRaises(ValidationError):
            self.outbox(available_at=datetime(2026, 7, 15, 12))
        with self.assertRaises(ValidationError):
            self.outbox(error_summary="Authorization: Bearer synthetic-test-value")
        message = self.outbox(available_at=NOW.astimezone(dt_timezone(timedelta(hours=4))))
        self.assertEqual(message.available_at.utcoffset(), timedelta(0))

    def test_unknown_recipient_timezone_is_blocked_not_assumed_and_email_admin_is_readonly(self):
        message = self.outbox(recipient=None, recipient_key="external:approved-mailbox", recipient_role="external",
                              recipient_timezone=None, status="blocked")
        self.assertEqual(message.status, "blocked")
        self.assertIsNone(message.recipient_timezone)
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        for cls, model in ((EmailOutboxAdmin, EmailOutbox), (EmailAttemptAdmin, EmailAttempt)):
            model_admin = cls(model, admin.site)
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_timezone_and_loan_changes_do_not_enqueue_messages(self):
        self.preference()
        self.approve(0)
        self.loan.refresh_from_db()
        self.loan.delivery_days = 3
        self.loan.save(update_fields=["delivery_days"])
        self.assertEqual(EmailOutbox.objects.count(), 0)
        self.assertEqual(EmailAttempt.objects.count(), 0)


class Phase2MigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_history_and_notification_log(self):
        old = [("library", "0023_loan_delivery_days")]
        new = [("library", "0024_phase2_timezones_email")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            old_user = apps.get_model("auth", "User").objects.create(username="synthetic-migration-user", password="!")
            apps.get_model("library", "UserProfile").objects.create(user=old_user, role="admin", phone_number="07000000000")
            category = apps.get_model("library", "Category").objects.create(name="Synthetic migration", slug="synthetic-migration")
            resource = apps.get_model("library", "Resource").objects.create(id="migration-resource", title="Synthetic", author="Synthetic", category=category)
            copy = apps.get_model("library", "BookCopy").objects.create(resource=resource, accession_number="MIG-1")
            apps.get_model("library", "Loan").objects.create(id="migration-loan", book_copy=copy, borrower_name="Synthetic",
                borrower_email="synthetic@example.com", status="borrowed", approved_at=NOW, borrowed_at=NOW,
                due_date=date(2026, 8, 20), delivery_days=5)
            apps.get_model("library", "NotificationLog").objects.create(loan_id="migration-loan", notification_type="due_soon")
            executor = MigrationExecutor(connection)
            executor.migrate(new)
            # Inspect 0024 with its historical model, not columns introduced by
            # later migrations such as the 0025 database identity guard.
            row = executor.loader.project_state(new).apps.get_model("library", "Loan").objects.get(pk="migration-loan")
            self.assertEqual((row.approved_at, row.borrowed_at, row.due_date, row.delivery_days), (NOW, NOW, date(2026, 8, 20), 5))
            self.assertTrue(all(getattr(row, field) is None for field in Loan.POLICY_FIELDS))
            self.assertEqual(row.email_deadline_revision, 0)
            self.assertEqual(NotificationLog.objects.filter(loan_id=row.pk, notification_type="due_soon").count(), 1)
            self.assertEqual(NotificationLog._meta.db_table, "library_notification_log")
            self.assertEqual(EmailOutbox.objects.count(), 0)
            profile = UserProfile.objects.get(user_id=old_user.pk)
            self.assertIsNone(profile.time_zone)
            self.assertEqual(profile.time_zone_source, "")
            self.assertIsNone(profile.time_zone_updated_at)
            self.assertEqual(profile.phone_number, "07000000000")
            executor = MigrationExecutor(connection)
            executor.migrate(old)
            historical = executor.loader.project_state(old).apps
            self.assertEqual(historical.get_model("library", "Loan").objects.get(pk="migration-loan").due_date, date(2026, 8, 20))
            self.assertEqual(historical.get_model("library", "NotificationLog").objects.filter(loan_id="migration-loan").count(), 1)
        finally:
            MigrationExecutor(connection).migrate(latest)


@skipUnless(connection.vendor == "postgresql", "Requires an isolated PostgreSQL instance; SQLite cannot prove row locking.")
class PostgreSQLRevisionConcurrencyTests(TransactionTestCase):
    setUp = delivery_tests.LoanDeliveryPeriodTests.setUp
    approve = delivery_tests.LoanDeliveryPeriodTests.approve
    confirmed_at = NOW

    def test_two_concurrent_identical_delivery_edits_increment_once(self):
        self.approve(0)
        baseline = Loan.objects.get(pk=self.loan.pk).email_deadline_revision
        barrier = Barrier(2)

        def edit():
            try:
                row = Loan.objects.get(pk=self.loan.pk)
                row.delivery_days = 3
                barrier.wait(timeout=10)
                row.save(update_fields=["delivery_days"])
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(edit), pool.submit(edit)]
            for future in futures:
                future.result(timeout=20)
        row = Loan.objects.get(pk=self.loan.pk)
        self.assertEqual(row.email_deadline_revision, baseline + 1)
        self.assertEqual(row.delivery_days, 3)
