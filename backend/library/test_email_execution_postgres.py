"""Actual independent process/session tests; never use the application database."""
from datetime import timedelta
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import sys
import time
from threading import Thread
from unittest import skipUnless
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from .email_execution import execution_lock, drain_outbox, LOCK_ID
from .email_models import EmailOutbox
from .email_worker import EmailWorker
from .test_email_system import EmailSystemTests, FakeGraph


@skipUnless(connection.vendor == "postgresql" and os.environ.get("KBC_SYNTHETIC_PG_PORT"),
            "Requires the guarded fresh local PostgreSQL cluster and independent processes.")
@override_settings(LIBRARY_EMAIL_WORKER_DIRECT=True)
class ExecutionProcessTests(TransactionTestCase):
    setUp = EmailSystemTests.setUp
    new_loan = EmailSystemTests.new_loan
    one_message = EmailSystemTests.one_message

    def child(self, mode):
        cfg = connection.settings_dict
        self.assertEqual((cfg["HOST"], cfg["NAME"], cfg["USER"]),
                         ("127.0.0.1", "test_kbc_phase3_tests", "kbc_test_admin"))
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PYTHONTZPATH") if key in os.environ}
        env.update(LIBRARY_ISOLATED_TESTS="1", KBC_SYNTHETIC_PG_PORT=str(cfg["PORT"]))
        process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "email_execution_test_child.py"), mode],
                                   env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(cleanup)
        lines = Queue()
        Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        try:
            first = lines.get(timeout=20).strip()
        except Empty:
            self.fail("Synthetic child failed to reach its synchronization point.")
        self.assertTrue(first, "Synthetic child exited before synchronization.")
        return process, first

    def assert_lock_available(self):
        deadline = time.monotonic() + 5
        while True:
            with execution_lock() as acquired:
                if acquired:
                    break
            if time.monotonic() >= deadline:
                self.fail("Synthetic backend did not release its advisory lock.")
            time.sleep(0.05)  # Test-only disconnect detection grace period.
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=%s AND granted", [LOCK_ID])
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_other_process_excludes_worker_and_releases_after_success(self):
        process, first = self.child("lock")
        self.assertTrue(first.startswith("locked:1:"))
        with patch("library.email_execution.EmailWorker") as worker:
            self.assertTrue(drain_outbox()["busy"])
        worker.assert_not_called()
        process.communicate("release\n", timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assert_lock_available()

    def test_exception_releases_session_lock(self):
        process, _ = self.child("lock")
        process.communicate("fail\n", timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assert_lock_available()

    def test_killed_process_releases_session_lock(self):
        process, _ = self.child("lock")
        process.kill()
        process.communicate(timeout=10)
        self.assert_lock_available()

    def test_backend_connection_loss_releases_lock(self):
        process, first = self.child("lock")
        pid = int(first.rsplit(":", 1)[1])
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(%s)", [pid])
            self.assertTrue(cursor.fetchone()[0])
        process.communicate("release\n", timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assert_lock_available()

    def test_real_worker_process_excludes_other_invocation_and_accepts_once(self):
        row = self.one_message()
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        process, first = self.child("worker")
        self.assertEqual(first, "submitting")
        with patch("library.email_execution.EmailWorker") as worker:
            self.assertTrue(drain_outbox()["busy"])
        worker.assert_not_called()
        process.communicate("finish\n", timeout=10)
        self.assertEqual(process.returncode, 0)
        row.refresh_from_db()
        self.assertEqual(row.status, "accepted")
        self.assertEqual(row.attempts.count(), 1)
        self.assert_lock_available()

    def test_crash_during_submission_recovers_uncertain_without_replay(self):
        row = self.one_message()
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        process, first = self.child("worker")
        self.assertEqual(first, "submitting")
        process.kill()
        process.communicate(timeout=10)
        EmailOutbox.objects.filter(pk=row.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        fake = FakeGraph()
        worker = EmailWorker(client=fake)
        with patch("library.email_execution.EmailWorker", return_value=worker):
            drain_outbox()
            drain_outbox()
        row.refresh_from_db()
        self.assertEqual(row.status, "uncertain")
        self.assertEqual(row.attempts.get().result, "uncertain")
        self.assertEqual(fake.sent, [])
        self.assert_lock_available()

    def test_crash_after_claim_recovers_and_sends_once(self):
        row = self.one_message()
        EmailOutbox.objects.filter(pk=row.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        process, first = self.child("claim")
        self.assertEqual(first, "claimed")
        process.kill()
        process.communicate(timeout=10)
        EmailOutbox.objects.filter(pk=row.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        fake = FakeGraph()
        worker = EmailWorker(client=fake)
        with patch("library.email_execution.EmailWorker", return_value=worker):
            drain_outbox()
            drain_outbox()
        row.refresh_from_db()
        self.assertEqual(row.status, "accepted")
        self.assertEqual(len(fake.sent), 1)
        self.assert_lock_available()
