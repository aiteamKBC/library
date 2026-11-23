from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch, MagicMock

from django.core.management import call_command, CommandError
from django.db import transaction
from django.test import TransactionTestCase, SimpleTestCase, override_settings
from django.utils import timezone

from . import email_activation as activation
from .email_execution import drain_outbox, execution_lock, LOCK_ID
from .email_models import EmailOutbox, EmailAttempt
from .email_scheduler import schedule_reminders
from .email_worker import EmailWorker
from .graph_client import GraphResult
from . import test_email_system as fixtures

FakeGraph, NOW = fixtures.FakeGraph, fixtures.NOW


@contextmanager
def acquired_lock():
    yield True


class ActivationTransactionTests(TransactionTestCase):
    setUp = fixtures.EmailSystemTests.setUp
    new_loan = fixtures.EmailSystemTests.new_loan
    confirm = fixtures.EmailSystemTests.confirm
    reminder_loan = fixtures.EmailSystemTests.reminder_loan
    one_message = fixtures.EmailSystemTests.one_message

    def test_actual_commit_wakes_once_for_student_and_admin(self):
        with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True), patch.object(activation, "wake_worker") as wake:
            with transaction.atomic():
                loan = self.new_loan("committed")
                self.assertEqual(loan.email_messages.count(), 2)
                wake.assert_not_called()
            wake.assert_called_once_with()

    def test_rollback_discards_rows_and_wake(self):
        with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True), patch.object(activation, "wake_worker") as wake:
            with self.assertRaises(RuntimeError), transaction.atomic():
                self.new_loan("rolled-back")
                raise RuntimeError()
            wake.assert_not_called()
        self.assertFalse(EmailOutbox.objects.filter(source_id="rolled-back").exists())

    def test_nested_savepoint_does_not_suppress_surviving_wake(self):
        with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True), patch.object(activation, "wake_worker") as wake:
            with transaction.atomic(), activation.coalesce_wakeups():
                try:
                    with transaction.atomic():
                        activation.wake_after_commit()
                        raise RuntimeError()
                except RuntimeError:
                    pass
                activation.wake_after_commit()
            wake.assert_called_once_with()

    def test_failed_socket_preserves_committed_pending_email(self):
        with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True, LIBRARY_EMAIL_WAKE_SOCKET="/run/library/wake"), \
                patch.object(activation.os.path, "isabs", return_value=True), \
                patch.object(activation.socket, "socket", side_effect=OSError), \
                self.assertLogs("library.email_activation", level="WARNING"):
            self.new_loan("failed-wake")
        self.assertEqual(EmailOutbox.objects.filter(source_id="failed-wake", status="pending").count(), 2)

    def test_blocked_rows_and_disabled_activation_do_not_signal(self):
        with patch.object(activation, "wake_worker") as wake:
            self.new_loan("disabled-wake")
            with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True, LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=False):
                self.new_loan("blocked-wake")
            wake.assert_not_called()

    def test_scheduler_coalesces_committed_reminders_and_exits(self):
        self.reminder_loan()
        with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True), patch.object(activation, "wake_worker") as wake:
            result = schedule_reminders(now=NOW)
            self.assertEqual(result["queued"], 1)
            wake.assert_called_once_with()
            schedule_reminders(now=NOW)
            self.assertEqual(wake.call_count, 1)

    def test_scheduler_command_signals_without_running_delivery(self):
        self.reminder_loan()
        with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True), \
                patch("library.email_scheduler.timezone.now", return_value=NOW), \
                patch.object(activation, "wake_worker") as wake, \
                patch.object(EmailWorker, "run_once") as delivery:
            call_command("schedule_email_reminders", stdout=StringIO())
            wake.assert_called_once_with()
            delivery.assert_not_called()

    def test_partial_scope_failure_still_wakes_committed_work(self):
        with override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True), patch.object(activation, "wake_worker") as wake:
            with self.assertRaises(RuntimeError), activation.coalesce_wakeups():
                with transaction.atomic():
                    activation.wake_after_commit()
                raise RuntimeError()
            wake.assert_called_once_with()

    def test_bounded_drain_and_recovery_preserve_provider_history(self):
        row = self.one_message()
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=timezone.now() - timedelta(days=1))
        fake = FakeGraph(GraphResult("retryable_failure", 429), GraphResult("accepted", 202))
        worker = EmailWorker(client=fake)
        with patch("library.email_execution.execution_lock", acquired_lock), \
                patch("library.email_execution.EmailWorker", return_value=worker):
            result = drain_outbox(limit=1, max_batches=2)
            self.assertEqual(result["outcomes"], {"retry_wait": 1})
            self.assertEqual(len(fake.sent), 1)
            EmailOutbox.objects.filter(pk=row.pk).update(available_at=timezone.now() - timedelta(days=1))
            result = drain_outbox(limit=1, max_batches=2)
            self.assertEqual(result["outcomes"], {"accepted": 1})
            drain_outbox(limit=1, max_batches=2)
        self.assertEqual(len(fake.sent), 2)
        self.assertEqual(EmailAttempt.objects.filter(message=row).count(), 2)

    def test_expired_claim_recovered_but_submission_never_replayed(self):
        row = self.one_message()
        fake = FakeGraph()
        worker = EmailWorker(client=fake)
        worker.claim(now=NOW)
        EmailOutbox.objects.filter(pk=row.pk).update(lease_expires_at=timezone.now() - timedelta(days=1),
                                                    available_at=timezone.now() - timedelta(days=1))
        with patch("library.email_execution.execution_lock", acquired_lock), \
                patch("library.email_execution.EmailWorker", return_value=worker):
            self.assertEqual(drain_outbox(limit=1)["outcomes"], {"accepted": 1})
            EmailOutbox.objects.filter(pk=row.pk).update(status="uncertain")
            drain_outbox(limit=1)
        self.assertEqual(len(fake.sent), 1)

    def test_expired_submission_becomes_uncertain_without_sending(self):
        row = self.one_message()
        fake = FakeGraph()
        worker = EmailWorker(client=fake)
        _, token = worker.claim(now=NOW)
        past = timezone.now() - timedelta(days=1)
        EmailOutbox.objects.filter(pk=row.pk).update(status="submitting", attempts_count=1,
                                                    lease_expires_at=past)
        EmailAttempt.objects.create(message=row, attempt_number=1, result="started",
                                    lease_token=token, started_at=past)
        with patch("library.email_execution.execution_lock", acquired_lock), \
                patch("library.email_execution.EmailWorker", return_value=worker):
            drain_outbox()
            drain_outbox()
        row.refresh_from_db()
        self.assertEqual(row.status, "uncertain")
        self.assertEqual(row.attempts.get().result, "uncertain")
        self.assertEqual(fake.sent, [])


class ActivationInterfaceTests(SimpleTestCase):
    @override_settings(LIBRARY_EMAIL_WAKE_ENABLED=False)
    def test_disabled_never_opens_socket(self):
        with patch.object(activation.socket, "socket") as factory:
            self.assertFalse(activation.wake_worker())
            factory.assert_not_called()

    @override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True, LIBRARY_EMAIL_WAKE_SOCKET="/run/library/wake")
    def test_fixed_bounded_local_protocol(self):
        with patch.object(activation.os.path, "isabs", return_value=True), \
                patch.object(activation.socket, "AF_UNIX", 1, create=True), \
                patch.object(activation.socket, "socket") as factory:
            self.assertTrue(activation.wake_worker())
            channel = factory.return_value.__enter__.return_value
            channel.settimeout.assert_called_once_with(0.1)
            channel.sendto.assert_called_once_with(b"library-email-wake-v1", "/run/library/wake")

    @override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True)
    def test_concurrent_event_groups_are_independent(self):
        barrier = Barrier(4)
        def event(_):
            with activation.coalesce_wakeups():
                activation.wake_after_commit()
                barrier.wait(timeout=5)
                activation.wake_after_commit()
        with patch.object(activation.transaction, "on_commit", side_effect=lambda callback, **kw: callback()), \
                patch.object(activation, "wake_worker") as wake:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(event, range(4)))
            self.assertEqual(wake.call_count, 4)

    @override_settings(LIBRARY_EMAIL_WORKER_DIRECT=True)
    def test_lock_is_nonblocking_and_released_on_failure(self):
        db = MagicMock(vendor="postgresql", in_atomic_block=False)
        db.settings_dict = {"ENGINE": "django.db.backends.postgresql", "HOST": "localhost"}
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (True,)
        with patch("library.email_execution.connection", db):
            with self.assertRaises(RuntimeError), execution_lock() as acquired:
                self.assertTrue(acquired)
                raise RuntimeError()
        self.assertEqual(cursor.execute.call_args_list[-1].args, ("SELECT pg_advisory_unlock(%s)", [LOCK_ID]))
        db.close.assert_called_once_with()

    def test_busy_worker_does_not_start_delivery(self):
        @contextmanager
        def busy():
            yield False
        with patch("library.email_execution.execution_lock", busy), patch("library.email_execution.EmailWorker") as worker:
            self.assertTrue(drain_outbox()["busy"])
            worker.assert_not_called()

    def test_batch_limit_stops_and_reports_remaining_work(self):
        with patch("library.email_execution.execution_lock", acquired_lock), \
                patch("library.email_execution.EmailWorker") as factory, \
                patch("library.email_execution.EmailOutbox") as model:
            factory.return_value.run_once.return_value = ["accepted"]
            model.objects.filter.return_value.exists.return_value = True
            result = drain_outbox(limit=1, max_batches=2)
            self.assertEqual(factory.return_value.run_once.call_count, 2)
            self.assertTrue(result["more_due"])

    def test_command_returns_after_finite_drain_and_validates_bounds(self):
        with patch("library.management.commands.process_email_outbox.drain_outbox", return_value={"busy": False}) as drain:
            call_command("process_email_outbox", limit=2, max_batches=3, stdout=StringIO())
            drain.assert_called_once_with(limit=2, max_batches=3)
            with self.assertRaises(CommandError):
                call_command("process_email_outbox", max_batches=0)
