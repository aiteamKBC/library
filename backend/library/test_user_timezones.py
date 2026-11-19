from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from . import tests as delivery_tests
from .models import Loan, UserProfile
from .notification_timing import due_reminder, format_recipient_timestamp, local_reminder_window, reminder_is_current
from .timezones import LoanTimezoneSnapshot, recipient_timezone_status, validated_timezone


UTC = dt_timezone.utc


class RecipientTimePolicyTests(SimpleTestCase):
    def test_valid_iana_zones_and_missing_or_invalid_values(self):
        for name in ("Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai", "UTC"):
            self.assertEqual(validated_timezone(name).key, name)
            self.assertEqual(recipient_timezone_status(name), "valid")
        for value in (None, "", "Mars/City", "../UTC", "/etc/localtime", "+03:00", " London "):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validated_timezone(value)
        self.assertEqual(recipient_timezone_status(None), "missing")
        self.assertEqual(recipient_timezone_status("Mars/City"), "invalid")

    def test_0900_in_each_recipient_zone_and_season(self):
        for zone, winter, summer in (
            ("Africa/Cairo", 7, 6), ("Europe/London", 9, 8),
            ("America/New_York", 14, 13), ("Asia/Dubai", 5, 5),
        ):
            for day, expected in ((date(2026, 1, 15), winter), (date(2026, 7, 15), summer)):
                with self.subTest(zone=zone, day=day):
                    scheduled, expires = local_reminder_window(day, zone)
                    self.assertEqual(scheduled.hour, expected)
                    local = scheduled.astimezone(ZoneInfo(zone))
                    self.assertEqual((local.date(), local.hour), (day, 9))
                    self.assertGreater(expires, scheduled)

    def test_countries_switch_dst_on_different_dates(self):
        for zone, day, hour in (
            ("Europe/London", date(2026, 3, 15), 9),
            ("America/New_York", date(2026, 3, 15), 13),
            ("Europe/London", date(2026, 3, 30), 8),
            ("Africa/Cairo", date(2026, 3, 30), 7),
            ("Africa/Cairo", date(2026, 4, 30), 6),
            ("Europe/London", date(2026, 10, 25), 9),
            ("America/New_York", date(2026, 10, 25), 13),
        ):
            self.assertEqual(local_reminder_window(day, zone)[0].hour, hour)
        self.assertIsNone(local_reminder_window(date(2011, 12, 30), "Pacific/Apia"))

    def candidate(self, **overrides):
        values = dict(loan_id="synthetic-loan", recipient_key="student-1", recipient_role="student",
                      due_date=date(2026, 7, 15), deadline_revision=1, recipient_timezone="Europe/London",
                      now=datetime(2026, 7, 15, 8, tzinfo=UTC), status="borrowed")
        values.update(overrides)
        return due_reminder(**values)

    def test_due_today_and_odd_overdue_days_only(self):
        for days in range(-1, 11):
            with self.subTest(days=days):
                instant = datetime(2026, 7, 15, 8, tzinfo=UTC) + timedelta(days=days)
                plan = self.candidate(now=instant, status="overdue" if days > 0 else "borrowed")
                if days == 0 or days in (1, 3, 5, 7, 9):
                    self.assertIsNotNone(plan)
                    self.assertEqual(plan.days_overdue, days)
                else:
                    self.assertIsNone(plan)
        self.assertIsNone(self.candidate(now=datetime(2026, 7, 15, 7, 59, 59, tzinfo=UTC)))

    def test_no_missed_day_catchup_and_old_plans_expire(self):
        plan = self.candidate()
        tomorrow = datetime(2026, 7, 16, 8, tzinfo=UTC)
        self.assertFalse(reminder_is_current(plan, due_date=plan.due_date, deadline_revision=1,
                         recipient_timezone=plan.recipient_timezone, now=tomorrow, status="borrowed"))
        latest = self.candidate(now=tomorrow)
        self.assertEqual(latest.days_overdue, 1)
        self.assertIsNone(self.candidate(now=tomorrow + timedelta(days=1)))

    def test_logical_key_survives_timezone_change_and_accepted_history_blocks_regression(self):
        now = datetime(2026, 7, 15, 18, tzinfo=UTC)
        new_york = self.candidate(now=now, recipient_timezone="America/New_York")
        dubai = self.candidate(now=now, recipient_timezone="Asia/Dubai")
        self.assertEqual(new_york.logical_key, dubai.logical_key)
        self.assertNotEqual(new_york.scheduled_at_utc, dubai.scheduled_at_utc)
        self.assertIsNone(self.candidate(now=now, last_sent_days_overdue=1))
        self.assertNotEqual(dubai.logical_key, self.candidate(now=now, deadline_revision=2).logical_key)
        self.assertNotEqual(dubai.logical_key, self.candidate(now=now, recipient_key="student-2").logical_key)

    def test_return_deadline_revision_or_recipient_zone_change_invalidates_plan(self):
        plan = self.candidate()
        values = dict(due_date=plan.due_date, deadline_revision=1, recipient_timezone=plan.recipient_timezone,
                      now=plan.scheduled_at_utc, status="borrowed")
        self.assertTrue(reminder_is_current(plan, **values))
        for change in ({"returned_at": plan.scheduled_at_utc}, {"status": "returned"},
                       {"due_date": date(2026, 7, 16)}, {"deadline_revision": 2},
                       {"recipient_timezone": "Asia/Dubai"}):
            self.assertFalse(reminder_is_current(plan, **(values | change)))
        self.assertIsNone(self.candidate(status="returned"))
        with self.assertRaises(ValidationError):
            self.candidate(recipient_timezone=None)

    def test_event_timestamp_formatting_has_no_0900_delay(self):
        instant = datetime(2026, 7, 15, 0, 30, tzinfo=UTC)
        self.assertEqual(format_recipient_timestamp(instant, "Europe/London"), "15 Jul 2026 01:30 BST")
        self.assertEqual(format_recipient_timestamp(instant, "America/New_York"), "14 Jul 2026 20:30 EDT")
        self.assertEqual(format_recipient_timestamp(instant, "Asia/Dubai"), "15 Jul 2026 04:30 +04")

    def test_saved_student_zone_is_frozen_at_server_confirmation_even_after_travel(self):
        saved_student_zone = "Africa/Cairo"
        server_now = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)
        with patch("library.timezones.timezone.now", return_value=server_now), timezone.override(ZoneInfo("Europe/London")):
            snapshot = LoanTimezoneSnapshot.for_student(saved_student_zone)
        self.assertEqual(snapshot.confirmed_at, server_now)
        self.assertEqual(snapshot.deadline(2), date(2026, 8, 17))
        saved_student_zone = "America/New_York"
        with timezone.override(ZoneInfo(saved_student_zone)):
            self.assertEqual(snapshot.deadline(2), date(2026, 8, 17))
        with self.assertRaises(FrozenInstanceError):
            snapshot.calculation_timezone = saved_student_zone
        with self.assertRaises(ValidationError):
            LoanTimezoneSnapshot.for_student(None)

    def test_isolated_settings_use_disposable_database_only(self):
        self.assertTrue(settings.ISOLATED_TESTS)
        database = settings.DATABASES["default"]
        if database["ENGINE"] == "django.db.backends.postgresql":
            # Phase 3's runner creates a fresh synthetic local cluster. It never
            # accepts an arbitrary DATABASE_URL or a shared development database.
            self.assertEqual(database["HOST"], "127.0.0.1")
            self.assertEqual(database["USER"], "kbc_test_admin")
            self.assertEqual(database["NAME"], "test_kbc_phase3_tests")
            self.assertEqual(database["PASSWORD"], "")
            self.assertGreaterEqual(int(database["PORT"]), 1024)
        else:
            self.assertEqual(database["ENGINE"], "django.db.backends.sqlite3")
            name = database["NAME"]
            self.assertTrue(name == ":memory:" or (name.startswith("file:memorydb_") and "mode=memory" in name))
        self.assertEqual(settings.N8N_LIBRARY_WEBHOOK_URL, "")


class TimezoneObservationTests(TestCase):
    setUp = delivery_tests.LoanDeliveryPeriodTests.setUp

    def test_authenticated_student_and_admin_observation_is_validated_and_saved(self):
        for user in (self.student, self.staff):
            self.client.force_authenticate(user)
            response = self.client.post("/api/auth/timezone-observation/", {"timeZone": "America/New_York"}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data["saved"])
            self.assertEqual(response.data["savedTimeZone"], "America/New_York")
            profile = UserProfile.objects.get(user=user)
            self.assertEqual(profile.time_zone, "America/New_York")
            self.assertEqual(profile.time_zone_source, "browser")

    def test_missing_invalid_and_other_user_payloads_are_rejected(self):
        for payload in ({}, [], "invalid", {"timeZone": ""}, {"timeZone": "Mars/City"},
                        {"timeZone": "Asia/Dubai", "userId": self.student.pk},
                        {"timeZone": "Asia/Dubai", "confirmedAt": "2026-01-01T00:00:00Z"}):
            response = self.client.post("/api/auth/timezone-observation/", payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post("/api/auth/timezone-observation/", {"timeZone": "Asia/Dubai"}).status_code, 401)

    def test_client_clock_cannot_supply_booking_timestamp(self):
        self.loan.delete()  # Synthetic in-memory record only.
        server_now = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)
        with patch("library.views.timezone.now", return_value=server_now):
            response = self.client.post("/api/loans/", {
                "id": "synthetic-booking", "resourceId": self.resource.pk,
                "borrowerName": "Synthetic Student", "borrowerEmail": "synthetic@example.com",
                "borrowerPhone": "07123456789", "requestedAt": "2000-01-01T00:00:00Z",
            }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Loan.objects.get(pk="synthetic-booking").requested_at, server_now)
        self.assertEqual(response.data["requestedAt"], "2026-07-15T22:30:00Z")

    def test_history_lateness_does_not_depend_on_viewer_timezone(self):
        Loan._base_manager.filter(pk=self.loan.pk).update(status="returned", due_date=date(2026, 7, 15),
            returned_at=datetime(2026, 7, 15, 23, 30, tzinfo=UTC), return_condition="good")
        for zone in ("Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"):
            with self.subTest(zone=zone), timezone.override(ZoneInfo(zone)):
                response = self.client.get("/api/loans/loan/")
                self.assertEqual(response.data["returnDaysLate"], 1)
                self.assertEqual(response.data["returnedAt"], "2026-07-15T23:30:00Z")
                self.assertEqual(response.data["dueDate"], "2026-07-15")

    def test_api_does_not_interpret_naive_timestamps_using_server_or_viewer_timezone(self):
        from .serializers import UTCDateTimeField
        from rest_framework.exceptions import ValidationError as APIValidationError
        with self.assertRaises(APIValidationError):
            UTCDateTimeField().run_validation("2026-07-15T23:30:00")

    def test_api_offsets_round_trip_to_the_same_utc_instant_for_all_viewers(self):
        from .serializers import UTCDateTimeField
        expected = datetime(2026, 7, 15, 23, 30, tzinfo=UTC)
        values = ("2026-07-15T23:30:00Z", "2026-07-16T02:30:00+03:00",
                  "2026-07-16T00:30:00+01:00", "2026-07-15T19:30:00-04:00", "2026-07-16T03:30:00+04:00")
        for zone in ("Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"):
            with timezone.override(ZoneInfo(zone)):
                for value in values:
                    with self.subTest(viewer=zone, input=value):
                        field = UTCDateTimeField()
                        parsed = field.run_validation(value)
                        self.assertEqual(parsed, expected)
                        self.assertEqual(field.to_representation(parsed), "2026-07-15T23:30:00Z")

    def test_native_admin_provides_utc_display_metadata_without_changing_datefields(self):
        from django.test import Client
        self.staff.is_superuser = True
        self.staff.save(update_fields=["is_superuser"])
        instant = datetime(2026, 7, 15, 23, 30, tzinfo=UTC)
        Loan._base_manager.filter(pk=self.loan.pk).update(status="borrowed", approved_at=instant,
            borrowed_at=instant, due_date=date(2026, 8, 15))
        client = Client()
        client.force_login(self.staff)
        response = client.get("/admin/library/loan/loan/change/")
        self.assertEqual(response.status_code, 200)
        fields = response.context_data["device_timestamp_fields"]
        self.assertEqual(fields["approved_at"], instant.isoformat())
        self.assertNotIn("due_date", fields)
        self.assertContains(response, "device-time.js")
        response = client.get("/admin/library/loan/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context_data["device_timestamp_rows"][0]["fields"]["approved_at"], instant.isoformat())
