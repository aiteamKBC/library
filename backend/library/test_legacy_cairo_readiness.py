from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import StringIO
import json
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.db import connection
from django.forms.models import model_to_dict
from django.test import TestCase, RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from . import tests as delivery_tests
from .admin import LoanAdmin
from .models import BookCopy, Category, Loan, Resource, UserProfile
from .timezones import confirmation_timezone, LEGACY_CAIRO, LONDON

UTC = dt_timezone.utc


@override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=False, LIBRARY_LONDON_CUTOVER_AT="",
                   LIBRARY_USER_LOCAL_CUTOVER_AT="")
class OriginalCairoConfirmationTests(TestCase):
    setUp = delivery_tests.LoanDeliveryPeriodTests.setUp
    approve = delivery_tests.LoanDeliveryPeriodTests.approve
    confirmed_at = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)

    def pending(self):
        Loan._base_manager.filter(pk=self.loan.pk).update(status="requested", approved_at=None, borrowed_at=None,
            due_date=date(2026, 10, 25), delivery_days=0, calculation_policy=None, calculation_timezone=None,
            operational_timezone=None, confirmation_local_date=None, email_deadline_revision=0)
        BookCopy.objects.filter(pk=self.copy.pk).update(status="available")
        self.loan.refresh_from_db()

    def test_legacy_confirmation_needs_no_student_timezone_and_uses_cairo_in_summer_and_winter(self):
        self.assertFalse(UserProfile.objects.filter(user=self.student).exists())
        for instant, local_day in ((datetime(2026, 7, 15, 22, 30, tzinfo=UTC), date(2026, 7, 16)),
                                   (datetime(2026, 1, 15, 22, 30, tzinfo=UTC), date(2026, 1, 16))):
            for days in (0, 2, 5):
                with self.subTest(instant=instant, delivery_days=days):
                    self.pending()
                    self.confirmed_at = instant
                    with override_settings(TIME_ZONE="Europe/London"), timezone.override(LONDON):
                        response = self.approve(days)
                    self.assertEqual(response.status_code, 200, response.data)
                    self.loan.refresh_from_db()
                    self.assertEqual(self.loan.calculation_policy, "cairo_v1")
                    self.assertEqual(self.loan.calculation_timezone, "Africa/Cairo")
                    self.assertEqual(self.loan.confirmation_local_date, local_day)
                    self.assertEqual(self.loan.due_date, local_day + timedelta(days=30 + days))
                    self.assertEqual(self.loan.approved_at, instant)
                    self.assertFalse(UserProfile.objects.filter(user=self.student).exists())

    def test_preview_and_admin_use_cairo_without_a_london_boundary(self):
        with patch("library.models.timezone.now", return_value=self.confirmed_at):
            preview = self.client.get("/api/loans/loan/return-date-preview/?deliveryDays=2")
            request = RequestFactory().post("/admin/library/loan/")
            request.user = self.staff
            model_admin = LoanAdmin(Loan, admin.site)
            form_type = model_admin.get_form(request, self.loan)
            values = model_to_dict(self.loan)
            values.update(status="borrowed", delivery_days=2, requested_at_0="2026-07-01", requested_at_1="12:00:00")
            form = form_type(data=values, instance=self.loan)
            self.assertTrue(form.is_valid(), form.errors)
            model_admin.save_model(request, form.save(commit=False), form, True)
        self.loan.refresh_from_db()
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data["dueDate"], self.loan.due_date.isoformat())
        self.assertEqual(self.loan.due_date, date(2026, 8, 17))

    def test_explicit_invalid_london_configuration_is_not_silently_ignored(self):
        for value in (" ", "invalid", "2026-01-01T00:00:00", "2026-01-01T00:00:00+02:00"):
            with self.subTest(value=value), override_settings(LIBRARY_LONDON_CUTOVER_AT=value):
                before = Loan.objects.filter(pk=self.loan.pk).values().get()
                response = self.approve(0)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(Loan.objects.filter(pk=self.loan.pk).values().get(), before)

    def test_a_proven_london_boundary_still_selects_the_original_cairo_and_london_sides(self):
        boundary = datetime(2026, 10, 15, 22, 30, tzinfo=UTC)
        with override_settings(LIBRARY_LONDON_CUTOVER_AT=boundary.isoformat()):
            self.assertEqual(confirmation_timezone(boundary - timedelta(microseconds=1)), LEGACY_CAIRO)
            self.assertEqual(confirmation_timezone(boundary), LONDON)

    def test_new_student_policy_still_requires_its_own_approved_boundary_and_saved_profile(self):
        with override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=True, LIBRARY_USER_LOCAL_CUTOVER_AT=""):
            response = self.approve(0)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("LIBRARY_USER_LOCAL_CUTOVER_AT", str(response.data))
        with override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=True, LIBRARY_USER_LOCAL_CUTOVER_AT="2026-01-01T00:00:00Z"):
            response = self.approve(0)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("timezone", str(response.data).lower())

    def test_unclassified_history_is_not_recalculated_or_classified_by_the_cairo_default(self):
        anchor = datetime(2026, 1, 1, tzinfo=UTC)
        Loan._base_manager.filter(pk=self.loan.pk).update(status="borrowed", approved_at=anchor,
            borrowed_at=anchor, due_date=date(2026, 5, 19))
        self.loan.refresh_from_db()
        before = self.loan.due_date
        self.loan.notes = "Synthetic note only"
        self.loan.save(update_fields={"notes"})
        self.assertEqual(self.loan.due_date, before)
        self.assertIsNone(self.loan.calculation_policy)
        self.loan.delivery_days = 5
        with self.assertRaisesMessage(ValidationError, "unclassified"):
            self.loan.save(update_fields={"delivery_days"})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before)
        self.assertIsNone(self.loan.calculation_timezone)


class PendingLoanTimezoneChecklistTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Synthetic readiness", slug="synthetic-readiness")
        resource = Resource.objects.create(id="readiness-book", title="Synthetic", author="Synthetic", category=category)
        self.copy = BookCopy.objects.create(resource=resource, accession_number="READY-1")
        self.users = []
        for index in range(17):
            user = get_user_model().objects.create_user(f"synthetic-{index}", email=f"synthetic-{index}@example.test")
            self.users.append(user)
            UserProfile.objects.create(user=user)
            Loan.objects.create(id=f"pending-{index:02d}", borrower=user, borrower_email=user.email, book_copy=self.copy)

    def check(self, **options):
        output = StringIO()
        call_command("check_loan_timezone_readiness", stdout=output, **options)
        return json.loads(output.getvalue())

    def test_17_missing_timezones_are_reported_without_writes_or_creating_preferences(self):
        with CaptureQueriesContext(connection) as queries:
            result = self.check(expected_borrow_count=17)
        self.assertEqual((result["requested_borrow"], result["ready"], result["blocked"]), (17, 0, 17))
        self.assertTrue(result["count_matches"])
        self.assertTrue(all(row["blockers"] == ["TIMEZONE_MISSING"] for row in result["loans"]))
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in queries))
        self.assertEqual(UserProfile.objects.filter(time_zone__isnull=True).count(), 17)
        self.assertNotIn("@", json.dumps(result))

    def test_link_profile_inactive_and_invalid_zone_have_separate_blockers(self):
        Loan._base_manager.filter(pk="pending-00").update(borrower=None)
        UserProfile.objects.filter(user=self.users[1]).delete()
        get_user_model().objects.filter(pk=self.users[2].pk).update(is_active=False)
        UserProfile.objects.filter(user=self.users[3]).update(time_zone="Invalid/Region", time_zone_source="manual", time_zone_updated_at=timezone.now())
        result = self.check()
        blockers = {row["loan_id"]: row["blockers"] for row in result["loans"]}
        self.assertEqual(blockers["pending-00"], ["ACCOUNT_NOT_LINKED"])
        self.assertEqual(blockers["pending-01"], ["PROFILE_MISSING"])
        self.assertIn("ACCOUNT_INACTIVE", blockers["pending-02"])
        self.assertEqual(blockers["pending-03"], ["TIMEZONE_INVALID"])
        self.assertFalse(UserProfile.objects.filter(user=self.users[1]).exists())

    def test_explicit_synthetic_browser_and_manual_preferences_pass_without_assuming_one_country(self):
        for index, user in enumerate(self.users):
            UserProfile.objects.filter(user=user).update(time_zone=("Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai")[index % 4],
                time_zone_source="manual" if index % 2 else "browser", time_zone_updated_at=timezone.now())
        result = self.check(expected_borrow_count=17, require_ready=True)
        self.assertEqual((result["ready"], result["blocked"]), (17, 0))

    def test_required_readiness_fails_on_missing_zones_and_count_mismatch(self):
        with self.assertRaises(CommandError):
            self.check(expected_borrow_count=17, require_ready=True)
        result = self.check(expected_borrow_count=18)
        self.assertFalse(result["count_matches"])
        with self.assertRaises(CommandError):
            self.check(expected_borrow_count=-1)

    def test_notify_registrations_are_not_miscounted_as_borrow_requests(self):
        user = get_user_model().objects.create_user("synthetic-notify", email="notify@example.test")
        Loan.objects.create(id="notify-only", borrower=user, borrower_email=user.email, book_copy=self.copy, loan_type="notify")
        result = self.check(expected_borrow_count=17)
        self.assertEqual(result["requested_total"], 18)
        self.assertEqual(result["requested_borrow"], 17)
        self.assertEqual(result["requested_notify"], 1)
