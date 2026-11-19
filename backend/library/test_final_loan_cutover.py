"""Synthetic activation boundaries only; never a production cutover proposal."""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import models
from django.forms.models import model_to_dict
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from . import tests as delivery_tests
from .admin import LoanAdmin
from .models import BookCopy, Loan, UserProfile

UTC = dt_timezone.utc
# This is a fixture, NOT an activation recommendation or application default.
BOUNDARY = datetime(2030, 7, 1, tzinfo=UTC)


@override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=True,
                   LIBRARY_USER_LOCAL_CUTOVER_AT="2030-07-01T00:00:00Z",
                   LIBRARY_LONDON_CUTOVER_AT="")
class FinalLoanCutoverTests(TestCase):
    setUp = delivery_tests.LoanDeliveryPeriodTests.setUp
    approve = delivery_tests.LoanDeliveryPeriodTests.approve
    confirmed_at = BOUNDARY

    def zone(self, zone="Africa/Cairo", user=None):
        user = user or self.student
        return UserProfile.objects.update_or_create(user=user, defaults={
            "time_zone": zone, "time_zone_source": "manual", "time_zone_updated_at": BOUNDARY,
        })[0]

    def pending(self):
        # Reset only the synthetic fixture, never classify or rewrite real history.
        Loan._base_manager.filter(pk=self.loan.pk).update(status="requested", approved_at=None,
            borrowed_at=None, returned_at=None, due_date=date(2030, 8, 1), delivery_days=0,
            calculation_policy=None, calculation_timezone=None, operational_timezone=None,
            confirmation_local_date=None, email_deadline_revision=0)
        BookCopy.objects.filter(pk=self.copy.pk).update(status="available")
        self.loan.refresh_from_db()

    def snapshot(self):
        return Loan.objects.filter(pk=self.loan.pk).values().get()

    def historical(self, *, classified=False, status="borrowed", anchor=BOUNDARY - timedelta(days=100),
                   borrowed_at=None):
        local_day = anchor.astimezone(ZoneInfo("Africa/Cairo")).date() if anchor else None
        Loan._base_manager.filter(pk=self.loan.pk).update(status=status, approved_at=anchor,
            borrowed_at=borrowed_at, due_date=date(2030, 4, 11), delivery_days=2,
            calculation_policy="cairo_v1" if classified else None,
            calculation_timezone="Africa/Cairo" if classified else None,
            operational_timezone="Europe/London" if classified else None,
            confirmation_local_date=local_day if classified else None)
        self.loan.refresh_from_db()
        return self.loan

    def test_exact_boundary_uses_student_zone_without_london_cutover(self):
        self.zone("America/New_York")
        for delta in (timedelta(0), timedelta(microseconds=1)):
            with self.subTest(delta=delta):
                self.pending()
                self.confirmed_at = BOUNDARY + delta
                response = self.approve(3)
                self.assertEqual(response.status_code, 200, response.data)
                self.loan.refresh_from_db()
                self.assertEqual(self.loan.calculation_policy, "user_local_v1")
                self.assertEqual(self.loan.calculation_timezone, "America/New_York")
                self.assertEqual(self.loan.confirmation_local_date, date(2030, 6, 30))
                self.assertEqual(self.loan.due_date, date(2030, 8, 2))
                self.assertEqual(self.loan.approved_at, self.confirmed_at)

    def test_before_boundary_stays_legacy_and_does_not_invent_london_history(self):
        self.zone("America/New_York")
        self.confirmed_at = BOUNDARY - timedelta(microseconds=1)
        response = self.approve(0)
        self.assertEqual(response.status_code, 200, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.calculation_policy, "cairo_v1")
        self.assertEqual(self.loan.confirmation_local_date, date(2030, 7, 1))
        self.assertEqual(self.loan.due_date, date(2030, 7, 31))

    def test_proven_legacy_boundary_is_used_only_before_student_cutover(self):
        self.zone("America/New_York")
        for london_cutover, expected in (("2030-06-01T00:00:00Z", "london_v1"),
                                         ("2030-07-01T00:00:00Z", "cairo_v1")):
            with self.subTest(policy=expected), override_settings(LIBRARY_LONDON_CUTOVER_AT=london_cutover):
                self.pending()
                self.confirmed_at = BOUNDARY - timedelta(microseconds=1)
                self.assertEqual(self.approve(0).status_code, 200)
                self.loan.refresh_from_db()
                self.assertEqual(self.loan.calculation_policy, expected)

    def test_old_request_confirmed_after_activation_uses_saved_student_zone(self):
        self.zone("Asia/Dubai")
        Loan._base_manager.filter(pk=self.loan.pk).update(requested_at=BOUNDARY - timedelta(days=500))
        self.assertEqual(self.approve(5).status_code, 200)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.confirmation_local_date, date(2030, 7, 1))
        self.assertEqual(self.loan.due_date, date(2030, 8, 5))
        self.assertEqual(self.loan.approved_at, BOUNDARY)

    def test_summer_winter_and_delivery_days_use_explicit_student_calendar(self):
        for stamp in (datetime(2031, 1, 15, 22, 30, tzinfo=UTC), datetime(2031, 7, 15, 22, 30, tzinfo=UTC)):
            for zone, day_offset in (("Africa/Cairo", 1), ("Europe/London", 0),
                                     ("America/New_York", 0), ("Asia/Dubai", 1)):
                for days in (0, 2, 5):
                    with self.subTest(stamp=stamp, zone=zone, delivery=days):
                        self.pending()
                        self.zone(zone)
                        self.confirmed_at = stamp
                        with timezone.override(ZoneInfo("Pacific/Honolulu")):
                            response = self.approve(days)
                        self.assertEqual(response.status_code, 200, response.data)
                        self.loan.refresh_from_db()
                        expected_day = stamp.date() + timedelta(days=day_offset)
                        self.assertEqual(self.loan.confirmation_local_date, expected_day)
                        self.assertEqual(self.loan.due_date, expected_day + timedelta(days=30 + days))
                        self.assertEqual(self.loan.calculation_timezone, zone)
                        self.assertEqual(self.loan.operational_timezone, zone)
                        self.assertEqual(self.loan.approved_at, stamp)

    def test_midnight_minus_at_plus_in_all_four_zones(self):
        for zone in ("Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"):
            self.zone(zone)
            for month in (1, 7):
                midnight = datetime(2031, month, 15, tzinfo=ZoneInfo(zone)).astimezone(UTC)
                for delta, offset in ((timedelta(microseconds=-1), -1), (timedelta(0), 0),
                                      (timedelta(microseconds=1), 0)):
                    with self.subTest(zone=zone, month=month, delta=delta):
                        self.pending()
                        self.confirmed_at = midnight + delta
                        self.assertEqual(self.approve(2).status_code, 200)
                        self.loan.refresh_from_db()
                        day = date(2031, month, 15) + timedelta(days=offset)
                        self.assertEqual(self.loan.confirmation_local_date, day)
                        self.assertEqual(self.loan.due_date, day + timedelta(days=32))

    def test_dst_transition_instants_add_calendar_days_not_fixed_utc_hours(self):
        cases = (("Europe/London", "2031-03-30T00:59:59+00:00"),
                 ("Europe/London", "2031-03-30T01:00:00+00:00"),
                 ("Europe/London", "2031-10-26T00:59:59+00:00"),
                 ("Europe/London", "2031-10-26T01:00:00+00:00"),
                 ("America/New_York", "2031-03-09T06:59:59+00:00"),
                 ("America/New_York", "2031-03-09T07:00:00+00:00"),
                 ("America/New_York", "2031-11-02T05:59:59+00:00"),
                 ("America/New_York", "2031-11-02T06:00:00+00:00"),
                 ("Africa/Cairo", "2031-04-24T21:59:59+00:00"),
                 ("Africa/Cairo", "2031-04-24T22:00:00+00:00"))
        for zone, iso in cases:
            with self.subTest(zone=zone, instant=iso):
                self.pending()
                self.zone(zone)
                self.confirmed_at = datetime.fromisoformat(iso)
                expected = self.confirmed_at.astimezone(ZoneInfo(zone)).date()
                self.assertEqual(self.approve(5).status_code, 200)
                self.loan.refresh_from_db()
                self.assertEqual(self.loan.confirmation_local_date, expected)
                self.assertEqual(self.loan.due_date, expected + timedelta(days=35))

    def test_travel_and_later_return_do_not_rebase_a_user_local_loan(self):
        self.zone("America/New_York")
        self.assertEqual(self.approve(2).status_code, 200)
        self.loan.refresh_from_db()
        old = self.snapshot()
        self.zone("Asia/Dubai")
        self.loan.notes = "Travel after confirmation"
        self.loan.save(update_fields={"notes"})
        returned = BOUNDARY + timedelta(days=40)
        with patch("library.models.timezone.now", return_value=returned):
            response = self.client.patch("/api/loans/loan/", {"status": "returned", "returnCondition": "good"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.loan.refresh_from_db()
        for field in ("due_date", "approved_at", "borrowed_at", *Loan.POLICY_FIELDS, "email_deadline_revision"):
            self.assertEqual(getattr(self.loan, field), old[field])
        self.assertEqual(self.loan.returned_at, returned)

    def test_missing_invalid_or_unlinked_student_is_rejected_atomically(self):
        for mode in ("missing", "invalid", "unlinked"):
            with self.subTest(mode=mode):
                self.pending()
                if mode == "invalid":
                    self.zone()
                    UserProfile.objects.filter(user=self.student).update(time_zone="Invalid/NotAZone")
                else:
                    UserProfile.objects.filter(user=self.student).delete()
                if mode == "unlinked":
                    Loan._base_manager.filter(pk=self.loan.pk).update(borrower=None)
                before = self.snapshot()
                response = self.approve(2)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn("timezone", str(response.data).lower())
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(BookCopy.objects.get(pk=self.copy.pk).status, "available")
                Loan._base_manager.filter(pk=self.loan.pk).update(borrower=self.student)

    def test_missing_invalid_or_non_utc_activation_is_rejected_without_mutation(self):
        self.zone()
        for value in ("", "garbage", "2030-07-01T00:00:00", "2030-07-01T00:00:00+02:00"):
            with self.subTest(value=value), override_settings(LIBRARY_USER_LOCAL_CUTOVER_AT=value):
                before = self.snapshot()
                response = self.approve(0)
                self.assertEqual(response.status_code, 400)
                self.assertIn("LIBRARY_USER_LOCAL_CUTOVER_AT", str(response.data))
                self.assertEqual(self.snapshot(), before)

    def test_disabled_policy_does_not_activate_just_because_timestamp_is_configured(self):
        self.zone()
        with override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=False):
            response = self.approve(0)
        self.assertEqual(response.status_code, 200, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.calculation_policy, "cairo_v1")
        self.assertEqual(self.loan.calculation_timezone, "Africa/Cairo")

    def test_history_with_and_without_snapshot_survives_invalid_or_missing_cutover(self):
        for classified in (False, True):
            for anchor in (BOUNDARY - timedelta(days=100), None) if not classified else (BOUNDARY - timedelta(days=100),):
                with self.subTest(classified=classified, anchor=anchor):
                    self.pending()
                    self.historical(classified=classified, anchor=anchor)
                    before = self.snapshot()
                    self.zone("Asia/Dubai")
                    with override_settings(LIBRARY_USER_LOCAL_CUTOVER_AT="not-an-approved-instant"):
                        self.loan.notes = "Unrelated historical edit"
                        self.loan.save(update_fields={"notes"})
                        self.loan.save(update_fields={"delivery_days"})
                        response = self.client.patch("/api/loans/loan/", {"status": "returned", "returnCondition": "good"}, format="json")
                    self.assertEqual(response.status_code, 200, response.data)
                    self.loan.refresh_from_db()
                    for field in ("due_date", "delivery_days", "approved_at", "borrowed_at", *Loan.POLICY_FIELDS, "email_deadline_revision"):
                        self.assertEqual(getattr(self.loan, field), before[field])

    def test_approved_history_uses_original_approval_not_post_activation_checkout(self):
        anchor = BOUNDARY - timedelta(microseconds=1)
        self.historical(status="approved", anchor=anchor)
        self.zone("Asia/Dubai")
        before = self.snapshot()
        with patch("library.models.timezone.now", return_value=BOUNDARY + timedelta(days=10)):
            response = self.client.patch("/api/loans/loan/", {"status": "borrowed"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.approved_at, anchor)
        self.assertEqual(self.loan.due_date, before["due_date"])
        self.assertIsNone(self.loan.calculation_policy)

    def test_preview_api_and_admin_use_the_same_saved_student_policy(self):
        self.zone("America/New_York")
        self.zone("Asia/Dubai", user=self.staff)
        with patch("library.models.timezone.now", return_value=BOUNDARY):
            preview = self.client.get("/api/loans/loan/return-date-preview/?deliveryDays=3")
            request = RequestFactory().post("/admin/library/loan/")
            request.user = self.staff
            model_admin = LoanAdmin(Loan, admin.site)
            form_type = model_admin.get_form(request, self.loan)
            data = model_to_dict(self.loan)
            data.update(status="borrowed", delivery_days=3, requested_at_0="2029-01-01", requested_at_1="12:00:00")
            form = form_type(data=data, instance=self.loan)
            self.assertTrue(form.is_valid(), form.errors)
            obj = form.save(commit=False)
            model_admin.save_model(request, obj, form, True)
        self.loan.refresh_from_db()
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(self.loan.due_date.isoformat(), preview.data["dueDate"])
        self.assertEqual(self.loan.calculation_timezone, "America/New_York")

    def test_timestamp_output_is_utc_and_deadline_is_still_a_datefield(self):
        self.zone("Asia/Dubai")
        response = self.approve(0)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(datetime.fromisoformat(response.data["approvedAt"].replace("Z", "+00:00")), BOUNDARY)
        self.assertEqual(len(response.data["dueDate"]), 10)
        self.assertIsInstance(Loan._meta.get_field("due_date"), models.DateField)
        self.assertNotIsInstance(Loan._meta.get_field("due_date"), models.DateTimeField)

    def test_old_deadline_stays_fixed_on_changed_delivery_api_and_preview(self):
        for classified in (False, True):
            with self.subTest(classified=classified):
                self.pending()
                self.historical(classified=classified)
                before = self.snapshot()
                with patch("library.models.timezone.now", return_value=BOUNDARY + timedelta(days=10)):
                    for days in (5, 0, 20):
                        preview = self.client.get(f"/api/loans/loan/return-date-preview/?deliveryDays={days}")
                        result = self.client.patch("/api/loans/loan/", {"deliveryDays": days}, format="json")
                        self.assertEqual(preview.status_code, 200, preview.data)
                        self.assertEqual(result.status_code, 200, result.data)
                        self.assertEqual(result.data["dueDate"], before["due_date"].isoformat())
                        self.assertEqual(preview.data["dueDate"], result.data["dueDate"])
                        self.loan.refresh_from_db()
                        self.assertEqual(self.loan.delivery_days, days)
                        self.assertEqual(self.loan.email_deadline_revision, before["email_deadline_revision"])
                        for field in ("approved_at", "borrowed_at", *Loan.POLICY_FIELDS):
                            self.assertEqual(getattr(self.loan, field), before[field])

    def test_old_london_snapshot_is_not_recalculated_on_admin_delivery_edit(self):
        self.historical(classified=True)
        Loan._base_manager.filter(pk=self.loan.pk).update(calculation_policy="london_v1", calculation_timezone="Europe/London")
        self.loan.refresh_from_db()
        before = self.snapshot()
        self.loan.delivery_days = 7
        request = RequestFactory().post("/admin/library/loan/")
        request.user = self.staff
        with patch("library.models.timezone.now", return_value=BOUNDARY + timedelta(days=1)):
            LoanAdmin(Loan, admin.site).save_model(request, self.loan, None, True)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before["due_date"])
        self.assertEqual(self.loan.delivery_days, 7)
        self.assertEqual(self.loan.calculation_policy, "london_v1")

    def test_old_return_with_delivery_edit_preserves_due_date(self):
        self.historical()
        before = self.snapshot()
        with patch("library.models.timezone.now", return_value=BOUNDARY + timedelta(days=1)):
            result = self.client.patch("/api/loans/loan/", {
                "status": "returned", "returnCondition": "good", "deliveryDays": 9,
            }, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before["due_date"])
        self.assertEqual(self.loan.returned_at, BOUNDARY + timedelta(days=1))
        self.assertEqual(self.loan.email_deadline_revision, before["email_deadline_revision"])

    def test_no_anchor_history_keeps_date_without_guessing_policy(self):
        self.historical(anchor=None)
        before = self.snapshot()
        self.loan.delivery_days = 5
        with patch("library.models.timezone.now", return_value=BOUNDARY):
            self.loan.save(update_fields={"delivery_days"})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before["due_date"])
        self.assertIsNone(self.loan.approved_at)
        self.assertIsNone(self.loan.borrowed_at)
        self.assertTrue(all(getattr(self.loan, field) is None for field in Loan.POLICY_FIELDS))

    def test_first_approval_before_boundary_protects_later_checkout(self):
        self.historical(anchor=BOUNDARY - timedelta(microseconds=1), borrowed_at=BOUNDARY + timedelta(days=10))
        before = self.snapshot()
        self.loan.delivery_days = 5
        with patch("library.models.timezone.now", return_value=BOUNDARY + timedelta(days=11)):
            self.loan.save(update_fields={"delivery_days"})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before["due_date"])

    def test_missing_approval_falls_back_to_original_borrowed_timestamp(self):
        self.historical(anchor=None, borrowed_at=BOUNDARY - timedelta(microseconds=1))
        before = self.snapshot()
        self.loan.delivery_days = 5
        with patch("library.models.timezone.now", return_value=BOUNDARY):
            self.loan.save(update_fields={"delivery_days"})
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before["due_date"])

    def test_new_delivery_edit_after_travel_uses_frozen_student_date(self):
        self.zone("America/New_York")
        self.assertEqual(self.approve(2).status_code, 200)
        self.loan.refresh_from_db()
        before = self.snapshot()
        self.zone("Asia/Dubai")
        with patch("library.models.timezone.now", return_value=BOUNDARY + timedelta(days=10)):
            response = self.client.patch("/api/loans/loan/", {"deliveryDays": 5}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, before["confirmation_local_date"] + timedelta(days=35))
        self.assertEqual(self.loan.calculation_timezone, "America/New_York")
        self.assertEqual(self.loan.approved_at, BOUNDARY)
        self.assertEqual(self.loan.email_deadline_revision, before["email_deadline_revision"] + 1)

    def test_old_due_date_cannot_be_overwritten_directly_or_by_api(self):
        self.historical()
        before = self.snapshot()
        with patch("library.models.timezone.now", return_value=BOUNDARY):
            result = self.client.patch("/api/loans/loan/", {"dueDate": "2030-12-01"}, format="json")
            self.assertEqual(result.status_code, 400, result.data)
            self.assertEqual(self.snapshot(), before)
            self.loan.due_date = date(2030, 12, 1)
            with self.assertRaisesMessage(ValidationError, "historical return date"):
                self.loan.save(update_fields={"due_date"})
        self.assertEqual(self.snapshot(), before)

    def test_retained_cutover_keeps_history_fixed_if_new_confirmations_are_disabled(self):
        self.historical(classified=True)
        before = self.snapshot()
        self.loan.delivery_days = 10
        with override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=False), patch("library.models.timezone.now", return_value=BOUNDARY):
            self.loan.save(update_fields={"delivery_days"})
        self.assertEqual(self.loan.due_date, before["due_date"])

    def test_future_boundary_does_not_freeze_history_early(self):
        self.historical(classified=True)
        self.loan.delivery_days = 5
        with patch("library.models.timezone.now", return_value=BOUNDARY - timedelta(microseconds=1)):
            self.loan.save(update_fields={"delivery_days"})
        self.assertEqual(self.loan.due_date, self.loan.confirmation_local_date + timedelta(days=35))

    def test_missing_old_due_date_is_not_reconstructed_on_checkout(self):
        self.historical(classified=True, status="approved")
        Loan._base_manager.filter(pk=self.loan.pk).update(due_date=None)
        self.loan.refresh_from_db()
        before = self.snapshot()
        with patch("library.models.timezone.now", return_value=BOUNDARY):
            response = self.client.patch("/api/loans/loan/", {"status": "borrowed"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("cannot be reconstructed", str(response.data))
        self.assertEqual(self.snapshot(), before)
