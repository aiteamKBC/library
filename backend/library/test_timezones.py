from datetime import date, datetime, timedelta, timezone as utc_timezone

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import model_to_dict
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from . import tests as delivery_tests
from .admin import LoanAdmin
from .models import BookCopy, Loan
from .timezones import LEGACY_CAIRO


CUTOVER = datetime(2026, 10, 15, 22, 30, tzinfo=utc_timezone.utc)


@override_settings(LIBRARY_LONDON_CUTOVER_AT="2026-10-15T22:30:00Z")
class LondonLoanTests(TestCase):
    confirmed_at = CUTOVER
    setUp = delivery_tests.LoanDeliveryPeriodTests.setUp
    approve = delivery_tests.LoanDeliveryPeriodTests.approve

    def reset_pending(self):
        Loan._base_manager.filter(pk=self.loan.pk).update(
            status="requested", approved_at=None, borrowed_at=None, delivery_days=0,
            due_date=date(2026, 10, 25), requested_at=CUTOVER - timedelta(days=100),
            calculation_policy=None, calculation_timezone=None, operational_timezone=None, confirmation_local_date=None,
            email_deadline_revision=0,
        )
        BookCopy.objects.filter(pk=self.copy.pk).update(status="available")
        self.loan.refresh_from_db()

    def existing(self, *, approved_at=CUTOVER - timedelta(seconds=1), borrowed_at=None,
                 due_date=date(2026, 11, 15), delivery_days=0, status="borrowed"):
        # Explicit synthetic classification, not a production backfill.
        from .timezones import confirmation_timezone
        anchor = approved_at or borrowed_at
        zone = confirmation_timezone(anchor) if anchor else None
        Loan._base_manager.filter(pk=self.loan.pk).update(
            status=status, approved_at=approved_at, borrowed_at=borrowed_at,
            due_date=due_date, delivery_days=delivery_days,
            calculation_policy=("cairo_v1" if zone.key == "Africa/Cairo" else "london_v1") if zone else None,
            calculation_timezone=zone.key if zone else None, operational_timezone="Europe/London" if zone else None,
            confirmation_local_date=timezone.localdate(anchor, timezone=zone) if zone else None,
        )
        self.loan.refresh_from_db()
        return self.loan

    def snapshot(self):
        return Loan._base_manager.filter(pk=self.loan.pk).values().get()

    def test_before_at_and_after_cutover(self):
        for moment, due in (
            (CUTOVER - timedelta(microseconds=1), "2026-11-15"),
            (CUTOVER, "2026-11-14"),
            (CUTOVER + timedelta(microseconds=1), "2026-11-14"),
        ):
            with self.subTest(moment=moment):
                self.reset_pending()
                self.confirmed_at = moment
                result = self.approve(0)
                self.assertEqual(result.status_code, 200, result.data)
                self.assertEqual(result.data["dueDate"], due)
                self.loan.refresh_from_db()
                self.assertEqual(self.loan.approved_at, moment)
                self.assertEqual(self.loan.borrowed_at, moment)

    def test_old_pending_request_first_confirmed_after_cutover_uses_london(self):
        self.reset_pending()
        self.confirmed_at = CUTOVER + timedelta(seconds=1)
        result = self.approve(2)
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["dueDate"], "2026-11-16")

    def test_invalid_configured_cutover_fails_without_saving(self):
        for value in ("not-a-date", "2026-01-01T00:00:00", "2026-01-01T00:00:00+01:00"):
            with self.subTest(value=value), override_settings(LIBRARY_LONDON_CUTOVER_AT=value):
                before = self.snapshot()
                result = self.approve(0)
                self.assertEqual(result.status_code, 400, result.data)
                self.assertIn("LIBRARY_LONDON_CUTOVER_AT", str(result.data))
                self.assertEqual(self.snapshot(), before)
        self.webhook.assert_not_called()

    def test_legacy_delivery_edit_retains_cairo_anchor_after_cutover(self):
        moment = CUTOVER - timedelta(seconds=1)
        loan = self.existing(approved_at=moment, borrowed_at=moment, delivery_days=2,
                             due_date=date(2026, 11, 17))
        with patch_now(datetime(2026, 11, 1, tzinfo=utc_timezone.utc)):
            result = self.client.patch("/api/loans/loan/", {"deliveryDays": 5}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["dueDate"], "2026-11-20")
        loan.refresh_from_db()
        self.assertEqual(loan.approved_at, moment)
        self.assertEqual(loan.borrowed_at, moment)

    def test_new_delivery_edit_uses_original_london_confirmation(self):
        self.assertEqual(self.approve(2).status_code, 200)
        with patch_now(CUTOVER + timedelta(days=10)):
            result = self.client.patch("/api/loans/loan/", {"deliveryDays": 5}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["dueDate"], "2026-11-19")
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.approved_at, CUTOVER)
        self.assertEqual(self.loan.borrowed_at, CUTOVER)

    def test_ordinary_saves_and_same_delivery_preserve_nonstandard_legacy_date(self):
        loan = self.existing(due_date=date(2026, 10, 25))
        with override_settings(LIBRARY_LONDON_CUTOVER_AT=""):
            loan.save()
            loan.notes = "Synthetic note"
            loan.save(update_fields=["notes"])
            result = self.client.patch("/api/loans/loan/", {"deliveryDays": 0, "notes": "Same days"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        loan.refresh_from_db()
        self.assertEqual(loan.due_date, date(2026, 10, 25))

    def test_approved_to_borrowed_preserves_existing_nonstandard_deadline(self):
        moment = CUTOVER - timedelta(seconds=1)
        self.existing(status="approved", approved_at=moment, due_date=date(2026, 10, 25))
        with patch_now(CUTOVER + timedelta(days=3)):
            result = self.client.patch("/api/loans/loan/", {"status": "borrowed"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.approved_at, moment)
        self.assertEqual(self.loan.due_date, date(2026, 10, 25))
        self.assertEqual(self.loan.borrowed_at, CUTOVER + timedelta(days=3))

    def test_missing_confirmation_preserves_data_and_refuses_recalculation(self):
        loan = self.existing(approved_at=None, borrowed_at=None)
        before = self.snapshot()
        result = self.client.patch("/api/loans/loan/", {"deliveryDays": 2}, format="json")
        self.assertEqual(result.status_code, 400, result.data)
        self.assertIn("reliable", str(result.data))
        self.assertEqual(self.snapshot(), before)
        loan.notes = "Safe without an anchor"
        loan.save(update_fields=["notes"])
        result = self.client.get("/api/loans/loan/return-date-preview/?deliveryDays=2")
        self.assertEqual(result.status_code, 400)

    def test_missing_legacy_confirmation_is_not_replaced_by_checkout_time(self):
        self.existing(status="approved", approved_at=None, borrowed_at=None)
        with patch_now(CUTOVER + timedelta(days=2)):
            result = self.client.patch("/api/loans/loan/", {"status": "borrowed"}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.loan.refresh_from_db()
        self.assertIsNone(self.loan.approved_at)
        self.assertIsNone(self.loan.borrowed_at)
        self.assertEqual(self.loan.due_date, date(2026, 11, 15))

    def test_direct_save_preserves_anchor_and_adds_due_to_update_fields(self):
        loan = self.existing(approved_at=CUTOVER, borrowed_at=CUTOVER)
        loan.delivery_days = 5
        loan.save(update_fields=["delivery_days"])
        loan.refresh_from_db()
        self.assertEqual(loan.due_date, date(2026, 11, 19))
        self.assertEqual(loan.approved_at, CUTOVER)
        self.assertEqual(loan.borrowed_at, CUTOVER)
        loan.delivery_days = 7
        loan.notes = "Only notes are persisted"
        loan.save(update_fields=["notes"])
        loan.refresh_from_db()
        self.assertEqual(loan.delivery_days, 5)
        self.assertEqual(loan.due_date, date(2026, 11, 19))

    def test_original_timestamps_cannot_be_changed_by_direct_save(self):
        for field in ("approved_at", "borrowed_at"):
            with self.subTest(field=field):
                loan = self.existing(approved_at=CUTOVER, borrowed_at=CUTOVER)
                setattr(loan, field, CUTOVER + timedelta(days=1))
                with self.assertRaises(ValidationError):
                    loan.save()
                loan.refresh_from_db()
                self.assertEqual(getattr(loan, field), CUTOVER)

    def test_borrowed_at_fallback_is_used_without_changing_it(self):
        moment = CUTOVER - timedelta(seconds=1)
        loan = self.existing(approved_at=None, borrowed_at=moment)
        loan.delivery_days = 2
        loan.save(update_fields=["delivery_days"])
        loan.refresh_from_db()
        self.assertEqual(loan.due_date, date(2026, 11, 17))
        self.assertIsNone(loan.approved_at)
        self.assertEqual(loan.borrowed_at, moment)

    def test_preview_and_confirmation_share_the_same_calculation(self):
        for moment in (CUTOVER - timedelta(seconds=1), CUTOVER):
            with self.subTest(moment=moment), patch_now(moment):
                self.reset_pending()
                before = self.snapshot()
                preview = self.client.get("/api/loans/loan/return-date-preview/?deliveryDays=3")
                self.assertEqual(preview.status_code, 200, preview.data)
                self.assertEqual(self.snapshot(), before)
                self.confirmed_at = moment
                result = self.approve(3)
                self.assertEqual(result.status_code, 200, result.data)
                self.assertEqual(preview.data["dueDate"], result.data["dueDate"])
                preview = self.client.get("/api/loans/loan/return-date-preview/?deliveryDays=5")
                result = self.client.patch("/api/loans/loan/", {"deliveryDays": 5}, format="json")
                self.assertEqual(preview.data["dueDate"], result.data["dueDate"])

    def test_preview_requires_staff_and_valid_delivery_days(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get("/api/loans/loan/return-date-preview/?deliveryDays=0").status_code, 403)
        self.client.force_authenticate(self.staff)
        for value in ("", "-1", "1.5", "32768"):
            self.assertEqual(self.client.get(f"/api/loans/loan/return-date-preview/?deliveryDays={value}").status_code, 400)

    def test_admin_uses_model_calculation_and_protects_confirmation_fields(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        loan_admin = LoanAdmin(Loan, admin.site)
        with patch_now(CUTOVER):
            form_class = loan_admin.get_form(request, self.loan)
            data = model_to_dict(self.loan)
            data.update(status="borrowed", delivery_days=2, requested_at_0="2026-10-10", requested_at_1="12:00:00")
            form = form_class(data=data, instance=self.loan)
            self.assertTrue(form.is_valid(), form.errors)
            obj = form.save(commit=False)
            loan_admin.save_model(request, obj, form, True)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, date(2026, 11, 16))
        self.assertEqual(self.loan.approved_at, CUTOVER)
        fields = loan_admin.get_readonly_fields(request, self.loan)
        self.assertTrue({"approved_at", "borrowed_at", "due_date"}.issubset(fields))

    def test_admin_reports_invalid_configured_cutover_as_form_validation(self):
        request = RequestFactory().get("/admin/")
        request.user = self.staff
        with override_settings(LIBRARY_LONDON_CUTOVER_AT="not-a-date"):
            form_class = LoanAdmin(Loan, admin.site).get_form(request, self.loan)
            data = model_to_dict(self.loan)
            data.update(status="borrowed", delivery_days=0, requested_at_0="2026-10-10", requested_at_1="12:00:00")
            form = form_class(data=data, instance=self.loan)
            self.assertFalse(form.is_valid())
            self.assertIn("LIBRARY_LONDON_CUTOVER_AT", str(form.errors))

    def test_global_and_active_timezone_cannot_change_deadline_policy(self):
        with override_settings(TIME_ZONE="Pacific/Auckland"), timezone.override(LEGACY_CAIRO):
            self.assertEqual(self.loan.calculate_due_date(confirmed_at=CUTOVER), date(2026, 11, 14))
            self.assertEqual(self.loan.calculate_due_date(confirmed_at=CUTOVER - timedelta(seconds=1)), date(2026, 11, 15))

    @override_settings(LIBRARY_LONDON_CUTOVER_AT="2026-01-01T00:00:00Z")
    def test_london_gmt_bst_and_clock_changes_use_calendar_days(self):
        for value, due in (
            ("2026-01-15T22:30:00+00:00", date(2026, 2, 14)),
            ("2026-07-15T22:30:00+00:00", date(2026, 8, 14)),
            ("2026-07-15T23:30:00+00:00", date(2026, 8, 15)),
            ("2026-03-29T00:30:00+00:00", date(2026, 4, 28)),
            ("2026-03-29T01:30:00+00:00", date(2026, 4, 28)),
            ("2026-10-25T00:30:00+00:00", date(2026, 11, 24)),
            ("2026-10-25T01:30:00+00:00", date(2026, 11, 24)),
            ("2028-01-31T12:00:00+00:00", date(2028, 3, 1)),
        ):
            with self.subTest(value=value):
                self.assertEqual(self.loan.calculate_due_date(confirmed_at=datetime.fromisoformat(value)), due)

    def test_overdue_day_is_london_for_both_legacy_and_new_loans(self):
        for anchor in (CUTOVER - timedelta(seconds=1), CUTOVER):
            for moment, count in (
                (datetime(2026, 11, 14, 22, 30, tzinfo=utc_timezone.utc), 0),
                (datetime(2026, 11, 14, 23, 59, 59, tzinfo=utc_timezone.utc), 0),
                (datetime(2026, 11, 15, 0, 0, tzinfo=utc_timezone.utc), 1),
            ):
                with self.subTest(anchor=anchor, moment=moment), patch_now(moment), timezone.override(LEGACY_CAIRO):
                    self.existing(approved_at=anchor, due_date=date(2026, 11, 14))
                    result = self.client.post("/api/loans/process_overdue/", {}, format="json")
                    self.assertEqual(result.status_code, 200, result.data)
                    self.assertEqual(result.data["count"], count)

    def test_overdue_correction_uses_london_today_for_legacy_loan(self):
        self.existing(approved_at=datetime(2026, 10, 15, 12, tzinfo=utc_timezone.utc),
                      due_date=date(2026, 11, 13), delivery_days=1, status="overdue")
        with patch_now(datetime(2026, 11, 14, 22, 30, tzinfo=utc_timezone.utc)), timezone.override(LEGACY_CAIRO):
            result = self.client.patch("/api/loans/loan/", {"deliveryDays": 0}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["dueDate"], "2026-11-14")
        self.assertEqual(result.data["status"], "borrowed")

    def test_overdue_uses_bst_midnight_not_utc_or_cairo_midnight(self):
        for moment, count in (
            (datetime(2026, 7, 15, 21, 30, tzinfo=utc_timezone.utc), 0),
            (datetime(2026, 7, 15, 23, 0, tzinfo=utc_timezone.utc), 1),
        ):
            with self.subTest(moment=moment), patch_now(moment):
                self.existing(due_date=date(2026, 7, 15))
                result = self.client.post("/api/loans/process_overdue/", {}, format="json")
                self.assertEqual(result.data["count"], count)

    def test_api_utc_preserves_london_instant_and_does_not_shift_datefields(self):
        instant = datetime(2026, 7, 15, 23, 30, tzinfo=utc_timezone.utc)
        self.existing(approved_at=instant, borrowed_at=instant, due_date=date(2026, 8, 15))
        result = self.client.get("/api/loans/loan/")
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["approvedAt"], "2026-07-15T23:30:00Z")
        represented = datetime.fromisoformat(result.data["approvedAt"].replace("Z", "+00:00"))
        from .timezones import LONDON
        self.assertEqual(represented.astimezone(LONDON).isoformat(), "2026-07-16T00:30:00+01:00")
        self.assertEqual(result.data["dueDate"], "2026-08-15")
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.approved_at, instant)

    def test_partial_checkout_save_preserves_both_existing_instants(self):
        approved = CUTOVER - timedelta(days=2)
        checkout = CUTOVER - timedelta(days=1)
        loan = self.existing(status="approved", approved_at=approved, borrowed_at=checkout,
                             due_date=date(2026, 10, 25))
        loan.status = "borrowed"
        loan.save(update_fields=["status"])
        loan.refresh_from_db()
        self.assertEqual(loan.approved_at, approved)
        self.assertEqual(loan.borrowed_at, checkout)
        self.assertEqual(loan.due_date, date(2026, 10, 25))

    def test_naive_confirmation_cannot_be_used_for_a_calculation(self):
        with self.assertRaisesMessage(ValidationError, "reliable"):
            self.loan.calculate_due_date(confirmed_at=datetime(2026, 10, 15, 22, 30))

    def test_viewing_and_note_edits_in_any_zone_do_not_change_deadline_or_confirmation(self):
        from zoneinfo import ZoneInfo
        for anchor in (CUTOVER - timedelta(seconds=1), CUTOVER):
            loan = self.existing(approved_at=anchor, borrowed_at=anchor, due_date=date(2026, 10, 25))
            original = (loan.approved_at, loan.borrowed_at, loan.due_date, loan.delivery_days)
            for zone in ("Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"):
                with self.subTest(anchor=anchor, viewer=zone), timezone.override(ZoneInfo(zone)):
                    response = self.client.get("/api/loans/loan/")
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["dueDate"], "2026-10-25")
                    self.assertEqual(response.data["approvedAt"], anchor.isoformat().replace("+00:00", "Z"))
                    response = self.client.patch("/api/loans/loan/", {"notes": f"Viewed in {zone}", "deliveryDays": 0}, format="json")
                    self.assertEqual(response.status_code, 200, response.data)
                    loan.refresh_from_db()
                    self.assertEqual((loan.approved_at, loan.borrowed_at, loan.due_date, loan.delivery_days), original)


def patch_now(moment):
    from unittest.mock import patch
    return patch("library.models.timezone.now", return_value=moment)
