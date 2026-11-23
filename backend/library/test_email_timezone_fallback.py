"""Optional email timezone fallback, using only synthetic data and providers."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from . import test_email_system as fixtures
from .email_events import enqueue_manual, saved_zone
from .email_models import EmailOutbox
from .email_scheduler import schedule_reminders
from .models import Loan, UserProfile


@override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE="")
class EmailTimezoneResolutionTests(SimpleTestCase):
    def resolve(self, value):
        # Empty strings cannot be persisted under the current profile constraint;
        # cover the resolver boundary without weakening that constraint.
        with patch("library.models.UserProfile.objects.filter") as profiles:
            profiles.return_value.values_list.return_value.first.return_value = value
            return saved_zone(SimpleNamespace(pk=123))

    def test_default_keeps_missing_zones_blocked(self):
        for value in (None, ""):
            with self.subTest(value=value):
                self.assertIsNone(self.resolve(value))

    @override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE="Europe/London")
    def test_null_and_empty_zones_use_the_configured_fallback(self):
        for value in (None, ""):
            with self.subTest(value=value):
                self.assertEqual(self.resolve(value), "Europe/London")

    def test_saved_preference_wins_even_if_the_unused_fallback_is_invalid(self):
        for fallback in ("Europe/London", "Not/A_Zone", None):
            with self.subTest(fallback=fallback), override_settings(
                LIBRARY_EMAIL_FALLBACK_TIMEZONE=fallback
            ):
                self.assertEqual(self.resolve("America/New_York"), "America/New_York")

    @override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE="Europe/London")
    def test_nonempty_invalid_preferences_are_not_replaced(self):
        for value in ("Not/A_Zone", " ", " Europe/London", 42):
            with self.subTest(value=value):
                self.assertIsNone(self.resolve(value))

    def test_invalid_fallbacks_fail_closed(self):
        for fallback in ("Not/A_Zone", " ", " Europe/London", None, 42):
            with self.subTest(fallback=fallback), override_settings(
                LIBRARY_EMAIL_FALLBACK_TIMEZONE=fallback
            ):
                self.assertIsNone(self.resolve(None))

    @override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE="Europe/London")
    def test_unlinked_recipient_stays_blocked_without_a_database_read(self):
        self.assertIsNone(saved_zone(None))


@override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE="Europe/London")
class EmailTimezoneFallbackFlowTests(TestCase):
    setUp = fixtures.EmailSystemTests.setUp
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm
    reminder_loan = fixtures.EmailSystemTests.reminder_loan
    one_message = fixtures.EmailSystemTests.one_message
    set_zone = fixtures.EmailSystemTests.set_zone
    worker = fixtures.EmailSystemTests.worker

    def test_missing_profile_uses_fallback_without_creating_a_profile(self):
        user = get_user_model().objects.create_user("no-timezone-profile")
        self.assertEqual(saved_zone(user), "Europe/London")
        self.assertFalse(UserProfile.objects.filter(user=user).exists())

    def test_email_fallback_does_not_supply_a_new_loan_calculation_timezone(self):
        self.set_zone(None)
        with override_settings(LIBRARY_USER_LOCAL_POLICY_ENABLED=True,
                               LIBRARY_USER_LOCAL_CUTOVER_AT="2028-01-01T00:00:00Z"):
            with self.assertRaises(ValidationError):
                self.loan.first_confirmation_policy(fixtures.NOW)

    def test_event_snapshot_and_delivery_do_not_change_profile_or_loan(self):
        self.set_zone(None)
        profile_before = UserProfile.objects.filter(user=self.student).values().get()
        loan_before = Loan.objects.filter(pk=self.loan.pk).values().get()
        row = enqueue_manual(self.loan, subject="Synthetic", message="Synthetic",
                             request_id=uuid.uuid4())
        self.assertEqual((row.status, row.recipient_timezone), ("pending", "Europe/London"))
        self.one_message("manual_email")
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=fixtures.NOW), ["accepted"])
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(UserProfile.objects.filter(user=self.student).values().get(), profile_before)
        self.assertEqual(Loan.objects.filter(pk=self.loan.pk).values().get(), loan_before)

    def test_reminder_uses_london_dst_window_without_changing_dates_or_profiles(self):
        self.reminder_loan()
        self.set_zone(None)
        profile_before = UserProfile.objects.filter(user=self.student).values().get()
        for revision, (day, hour, expiry) in enumerate((
            (date(2028, 1, 15), 9, datetime(2028, 1, 16, tzinfo=fixtures.UTC)),
            (date(2028, 7, 15), 8, datetime(2028, 7, 15, 23, tzinfo=fixtures.UTC)),
        ), start=1):
            with self.subTest(day=day):
                Loan._base_manager.filter(pk=self.loan.pk).update(
                    due_date=day, email_deadline_revision=revision)
                loan_before = Loan.objects.filter(pk=self.loan.pk).values().get()
                at = datetime(day.year, day.month, day.day, hour, tzinfo=fixtures.UTC)
                self.assertEqual(schedule_reminders(now=at - timedelta(seconds=1))["queued"], 0)
                self.assertEqual(schedule_reminders(now=at)["queued"], 1)
                self.assertEqual(schedule_reminders(now=at + timedelta(minutes=1))["queued"], 0)
                row = self.loan.email_messages.get(message_kind="reminder", deadline_revision=revision)
                self.assertEqual(row.recipient_timezone, "Europe/London")
                self.assertEqual((row.available_at, row.expires_at), (at, expiry))
                self.assertEqual(Loan.objects.filter(pk=self.loan.pk).values().get(), loan_before)
        self.assertEqual(UserProfile.objects.filter(user=self.student).values().get(), profile_before)

    def test_saved_preference_after_enqueue_reschedules_the_same_reminder_once(self):
        self.reminder_loan()
        self.set_zone(None)
        self.assertEqual(schedule_reminders(now=fixtures.NOW)["queued"], 1)
        row = self.loan.email_messages.get(message_kind="reminder")
        original = (row.pk, row.event_id, row.idempotency_key)
        self.assertEqual(row.recipient_timezone, "Europe/London")
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")

        self.set_zone("America/New_York")  # 08:00 at NOW; eligible an hour later.
        worker, fake = self.worker()
        claim = worker.claim(now=fixtures.NOW)
        self.assertEqual(worker.process(claim, now=fixtures.NOW), "pending")
        row.refresh_from_db()
        later = fixtures.NOW + timedelta(hours=1)
        self.assertEqual((row.recipient_timezone, row.available_at), ("America/New_York", later))
        self.assertFalse(fake.sent)
        self.assertEqual(schedule_reminders(now=later)["queued"], 0)
        self.assertEqual(worker.run_once(now=later), ["accepted"])
        with override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE="Asia/Dubai"):
            self.assertEqual(schedule_reminders(now=later + timedelta(minutes=1))["queued"], 0)
        row.refresh_from_db()
        self.assertEqual((row.pk, row.event_id, row.idempotency_key), original)
        self.assertEqual(row.attempts.count(), 1)
        self.assertEqual(len(fake.sent), 1)

    def test_worker_does_not_hide_a_corrupt_saved_preference_with_fallback(self):
        row = self.one_message()
        self.set_zone("Not/A_Zone")
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=fixtures.NOW), ["blocked"])
        row.refresh_from_db()
        self.assertEqual(row.error_code, "recipient_timezone_missing")
        self.assertFalse(row.attempts.exists())
        self.assertFalse(fake.sent)

    def test_removing_fallback_blocks_pending_delivery_before_an_attempt(self):
        self.set_zone(None)
        row = enqueue_manual(self.loan, subject="Synthetic", message="Synthetic",
                             request_id=uuid.uuid4())
        self.one_message("manual_email")
        worker, fake = self.worker()
        with override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE=""):
            self.assertEqual(worker.run_once(now=fixtures.NOW), ["blocked"])
        row.refresh_from_db()
        self.assertEqual(row.error_code, "recipient_timezone_missing")
        self.assertFalse(row.attempts.exists())
        self.assertFalse(fake.sent)

    def test_enabling_fallback_does_not_replay_historical_blocked_messages(self):
        self.set_zone(None)
        request_id = uuid.uuid4()
        with override_settings(LIBRARY_EMAIL_FALLBACK_TIMEZONE=""):
            row = enqueue_manual(self.loan, subject="Synthetic", message="Synthetic",
                                 request_id=request_id)
        self.assertEqual(row.status, "blocked")
        repeated = enqueue_manual(self.loan, subject="Synthetic", message="Synthetic",
                                  request_id=request_id)
        self.assertEqual((repeated.pk, repeated.status), (row.pk, "blocked"))
        EmailOutbox.objects.exclude(pk=row.pk).update(status="cancelled")
        worker, fake = self.worker()
        self.assertEqual(worker.run_once(now=fixtures.NOW), [])
        self.assertFalse(row.attempts.exists())
        self.assertFalse(fake.sent)
