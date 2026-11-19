from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import BookCopy, Category, Loan, Resource


class LoanDeliveryPeriodTests(TestCase):
    confirmed_at = datetime(2026, 10, 15, 12, tzinfo=dt_timezone.utc)

    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_user("librarian", is_staff=True)
        self.student = get_user_model().objects.create_user("student", email="student@example.com")
        category = Category.objects.create(name="Books", slug="books")
        self.resource = Resource.objects.create(id="book", title="Book", author="Author", category=category)
        self.copy = BookCopy.objects.create(resource=self.resource, accession_number="BOOK-1")
        self.loan = Loan.objects.create(
            id="loan", borrower=self.student, borrower_name="Student",
            borrower_email=self.student.email, borrower_phone="07123456789",
            book_copy=self.copy, requested_from=date(2026, 10, 10), due_date=date(2026, 10, 25),
        )
        self.client = APIClient()
        self.client.force_authenticate(self.staff)
        webhook = patch("library.views.send_library_webhook", return_value=True)
        self.webhook = webhook.start()
        self.addCleanup(webhook.stop)

    def approve(self, days):
        with patch("library.models.timezone.now", return_value=self.confirmed_at):
            return self.client.post("/api/loans/loan/approve/", {"deliveryDays": days}, format="json")

    def test_confirmation_replaces_requested_dates_with_30_days_plus_delivery(self):
        for days in (0, 3, 5):
            with self.subTest(delivery_days=days):
                # Each subtest starts from a pending request.
                Loan._base_manager.filter(pk=self.loan.pk).update(status="requested", approved_at=None, borrowed_at=None)
                BookCopy.objects.filter(pk=self.copy.pk).update(status="available")
                response = self.approve(days)
                self.assertEqual(response.status_code, 200, response.data)
                self.loan.refresh_from_db()
                self.assertEqual(self.loan.approved_at, self.confirmed_at)
                self.assertEqual(self.loan.borrowed_at, self.confirmed_at)
                self.assertEqual(self.loan.due_date, date(2026, 11, 14) + timedelta(days=days))
                self.assertEqual(response.data["deliveryDays"], days)
                self.assertEqual(self.webhook.call_args.args[0]["dueDate"], self.loan.due_date.isoformat())

    def test_delivery_update_uses_original_confirmation_and_can_be_reset_to_zero(self):
        self.assertEqual(self.approve(3).status_code, 200)
        for days in (5, 0):
            with patch("library.models.timezone.now", return_value=self.confirmed_at + timedelta(days=5)):
                response = self.client.patch("/api/loans/loan/", {"deliveryDays": days}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.loan.refresh_from_db()
            self.assertEqual(self.loan.due_date, date(2026, 11, 14) + timedelta(days=days))
            self.assertEqual(self.loan.approved_at, self.confirmed_at)
            self.assertEqual(self.loan.borrowed_at, self.confirmed_at)

    def test_invalid_or_missing_delivery_days_do_not_confirm(self):
        for payload in ({}, {"deliveryDays": -1}, {"deliveryDays": 1.5}, {"deliveryDays": None}, {"deliveryDays": 32768}):
            with self.subTest(payload=payload):
                response = self.client.post("/api/loans/loan/approve/", payload, format="json")
                self.assertEqual(response.status_code, 400, response.data)
                self.loan.refresh_from_db()
                self.assertEqual(self.loan.status, "requested")

    def test_student_cannot_choose_delivery_days(self):
        BookCopy.objects.create(resource=self.resource, accession_number="BOOK-2")
        self.client.force_authenticate(self.student)
        response = self.client.post("/api/loans/", {
            "id": "another", "resourceId": self.resource.pk,
            "borrowerPhone": "07123456789", "deliveryDays": 5,
        }, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("deliveryDays", response.data)
        response = self.client.post("/api/loans/loan/approve/", {"deliveryDays": 5}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_confirmation_cannot_be_repeated_to_restart_period(self):
        self.assertEqual(self.approve(3).status_code, 200)
        self.assertEqual(self.approve(5).status_code, 400)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.delivery_days, 3)

    def test_direct_borrow_transition_also_calculates_deadline(self):
        with patch("library.models.timezone.now", return_value=self.confirmed_at):
            response = self.client.patch("/api/loans/loan/", {"status": "borrowed", "deliveryDays": 5}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["dueDate"], "2026-11-19")

    def test_confirmed_due_date_cannot_bypass_policy(self):
        self.approve(0)
        response = self.client.patch("/api/loans/loan/", {"dueDate": "2027-01-01"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.due_date, date(2026, 11, 14))

    def test_cairo_confirmation_date_is_used_at_utc_midnight_boundary(self):
        self.confirmed_at = datetime(2026, 10, 15, 22, 30, tzinfo=dt_timezone.utc)
        response = self.approve(0)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["dueDate"], "2026-11-15")

    def test_return_and_unrelated_edits_preserve_deadline(self):
        self.approve(3)
        for payload in ({"notes": "Updated"}, {"status": "returned", "returnCondition": "good"}):
            response = self.client.patch("/api/loans/loan/", payload, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["dueDate"], "2026-11-17")
        response = self.client.patch("/api/loans/loan/", {"deliveryDays": 5}, format="json")
        self.assertEqual(response.status_code, 400, response.data)

    def test_confirmation_invalidates_resource_cache(self):
        cache.set("api:resources:list", ["stale"])
        self.assertEqual(self.approve(0).status_code, 200)
        self.assertIsNone(cache.get("api:resources:list"))

    def test_return_due_day_is_not_overdue_until_the_following_cairo_day(self):
        self.approve(0)
        for current, expected_count in (
            (datetime(2026, 11, 14, 12, tzinfo=dt_timezone.utc), 0),
            (datetime(2026, 11, 15, 12, tzinfo=dt_timezone.utc), 1),
        ):
            with patch("library.models.timezone.now", return_value=current):
                response = self.client.post("/api/loans/process_overdue/", {}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["count"], expected_count)

    def test_borrowing_after_approval_preserves_first_confirmation(self):
        with patch("library.models.timezone.now", return_value=self.confirmed_at):
            response = self.client.patch("/api/loans/loan/", {"status": "approved", "deliveryDays": 3}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        with patch("library.models.timezone.now", return_value=self.confirmed_at + timedelta(days=3)):
            response = self.client.patch("/api/loans/loan/", {"status": "borrowed"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.approved_at, self.confirmed_at)
        self.assertEqual(self.loan.due_date, date(2026, 11, 17))

    def test_editing_notes_does_not_recalculate_legacy_deadlines(self):
        # The active-loan form submits deliveryDays even when only notes change.
        Loan._base_manager.filter(pk=self.loan.pk).update(
            status="borrowed", approved_at=self.confirmed_at,
            borrowed_at=self.confirmed_at, due_date=date(2026, 10, 25),
        )
        response = self.client.patch("/api/loans/loan/", {"notes": "Note only", "deliveryDays": 0}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["dueDate"], "2026-10-25")

    def test_extending_delivery_clears_overdue_when_new_deadline_has_not_passed(self):
        self.approve(0)
        later = datetime(2026, 11, 16, 12, tzinfo=dt_timezone.utc)
        with patch("library.models.timezone.now", return_value=later):
            self.client.post("/api/loans/process_overdue/", {}, format="json")
            self.loan.refresh_from_db()
            self.assertEqual(self.loan.status, "overdue")
            response = self.client.patch("/api/loans/loan/", {"deliveryDays": 5}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["dueDate"], "2026-11-19")
        self.assertEqual(response.data["status"], "borrowed")
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.approved_at, self.confirmed_at)
        self.assertEqual(self.loan.borrowed_at, self.confirmed_at)

    def test_extension_does_not_clear_overdue_if_deadline_is_still_past(self):
        self.approve(0)
        with patch("library.models.timezone.now", return_value=datetime(2026, 11, 20, 12, tzinfo=dt_timezone.utc)):
            self.client.post("/api/loans/process_overdue/", {}, format="json")
            response = self.client.patch("/api/loans/loan/", {"deliveryDays": 3}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "overdue")
        self.assertEqual(response.data["dueDate"], "2026-11-17")

    def test_updated_deadline_is_visible_in_catalogue_and_student_dashboard(self):
        self.approve(2)
        # Prime the public catalogue cache before changing delivery days.
        self.client.get("/api/resources/")
        response = self.client.patch("/api/loans/loan/", {"deliveryDays": 5}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        catalogue = self.client.get("/api/resources/")
        self.assertEqual(catalogue.status_code, 200, catalogue.data)
        book = next(book for book in catalogue.data if book["id"] == self.resource.pk)
        self.assertEqual(book["expectedAvailableDate"], "2026-11-19")
        self.client.force_authenticate(self.student)
        dashboard = self.client.get("/api/auth/dashboard/")
        self.assertEqual(dashboard.status_code, 200, dashboard.data)
        self.assertEqual(dashboard.data["loans"][0]["dueDate"], "2026-11-19")

    def test_fixed_thirty_days_across_leap_february(self):
        self.confirmed_at = datetime(2028, 1, 31, 12, tzinfo=dt_timezone.utc)
        response = self.approve(0)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["dueDate"], "2028-03-01")
