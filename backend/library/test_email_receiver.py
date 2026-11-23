"""No network or real delivery. Linux descriptor tests are explicitly separate."""
from collections import deque
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest import skipUnless
from unittest.mock import MagicMock, patch
from io import StringIO

from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings

from config.email_worker_database import worker_database
from . import email_activation, email_receiver
from .email_execution import execution_lock


class QueueSocket:
    def __init__(self, *messages):
        self.messages = deque(messages)

    def recv(self, size):
        if not self.messages:
            raise BlockingIOError()
        return self.messages.popleft()[:size]


class ReceiverTests(SimpleTestCase):
    def test_command_rejects_missing_activation_without_database_access(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(CommandError):
            call_command("receive_email_wake", stdout=StringIO())

    def test_valid_burst_coalesces_to_one_bounded_worker(self):
        channel = QueueSocket(*[email_receiver.WAKE_MESSAGE] * 20)
        with patch.object(email_receiver, "drain_outbox", return_value={}) as worker:
            result = email_receiver.receive_and_process(channel, limit=2, max_batches=3)
        self.assertEqual(result["valid"], 20)
        worker.assert_called_once_with(limit=2, max_batches=3)

    def test_invalid_empty_and_oversized_datagrams_never_trigger_delivery(self):
        channel = QueueSocket(b"", b"other", email_receiver.WAKE_MESSAGE + b"suffix")
        with patch.object(email_receiver, "drain_outbox") as worker:
            result = email_receiver.receive_and_process(channel, recover_if_idle=True)
        worker.assert_not_called()
        self.assertEqual(result["invalid"], 3)

    def test_signal_budget_leaves_excess_for_next_activation(self):
        channel = QueueSocket(*[email_receiver.WAKE_MESSAGE] * 4)
        with patch.object(email_receiver, "drain_outbox", return_value={}):
            result = email_receiver.receive_and_process(channel, max_signals=2)
        self.assertEqual(result["signals"], 2)
        self.assertEqual(len(channel.messages), 2)

    def test_arrivals_during_worker_and_exit_are_not_discarded(self):
        channel = QueueSocket(email_receiver.WAKE_MESSAGE)
        def work(**kwargs):
            channel.messages.extend([email_receiver.WAKE_MESSAGE] * 3)
            return {}
        with patch.object(email_receiver, "drain_outbox", side_effect=work) as worker:
            email_receiver.receive_and_process(channel)
        worker.assert_called_once()
        self.assertEqual(len(channel.messages), 3)
        channel.messages.append(email_receiver.WAKE_MESSAGE)  # arrival after return
        with patch.object(email_receiver, "drain_outbox", return_value={}) as worker:
            self.assertEqual(email_receiver.receive_and_process(channel)["valid"], 4)
        worker.assert_called_once()

    def test_busy_worker_returns_without_loop_or_spawn(self):
        with patch.object(email_receiver, "drain_outbox", return_value={"busy": True}) as worker:
            result = email_receiver.receive_and_process(QueueSocket(email_receiver.WAKE_MESSAGE))
        self.assertTrue(result["worker"]["busy"])
        worker.assert_called_once()

    def test_lost_wake_recovery_with_empty_socket(self):
        with patch.object(email_receiver, "drain_outbox", return_value={}) as worker:
            email_receiver.receive_and_process(QueueSocket())
            worker.assert_not_called()
            email_receiver.receive_and_process(QueueSocket(), recover_if_idle=True)
        worker.assert_called_once()

    def test_worker_failure_propagates_for_service_restart(self):
        with patch.object(email_receiver, "drain_outbox", side_effect=RuntimeError("fake failure")):
            with self.assertRaises(RuntimeError):
                email_receiver.receive_and_process(QueueSocket(email_receiver.WAKE_MESSAGE))

    def test_socket_failure_propagates_without_delivery(self):
        channel = MagicMock()
        channel.recv.side_effect = PermissionError()
        with patch.object(email_receiver, "drain_outbox") as worker, self.assertRaises(PermissionError):
            email_receiver.receive_and_process(channel)
        worker.assert_not_called()

    def test_invalid_bounds_read_nothing(self):
        channel = MagicMock()
        for bounds in ({"max_signals": 0}, {"max_signals": 4097}, {"limit": 0}, {"max_batches": 101}):
            with self.assertRaises(ValueError):
                email_receiver.receive_and_process(channel, **bounds)
        channel.recv.assert_not_called()

    @override_settings(LIBRARY_EMAIL_WAKE_ENABLED=True, LIBRARY_EMAIL_WAKE_SOCKET="/run/library/wake")
    def test_missing_receiver_permissions_and_timeout_do_not_escape_sender(self):
        for error in (FileNotFoundError(), PermissionError(), TimeoutError()):
            with self.subTest(error=type(error).__name__), \
                    patch.object(email_activation.os.path, "isabs", return_value=True), \
                    patch.object(email_activation.socket, "socket", side_effect=error), \
                    self.assertLogs("library.email_activation", level="WARNING"):
                self.assertFalse(email_activation.wake_worker())

    def test_bad_activation_environment_never_opens_descriptor(self):
        for env in ({}, {"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "2"},
                    {"LISTEN_PID": "bad", "LISTEN_FDS": "1"}):
            with patch.dict(os.environ, env, clear=True), patch.object(email_receiver.socket, "socket") as factory:
                with self.assertRaises(ImproperlyConfigured), email_receiver.inherited_socket("/run/library/wake"):
                    pass
                factory.assert_not_called()

    @patch.object(socket, "AF_UNIX", 1, create=True)
    def test_descriptor_validation_and_shutdown_close_without_shutdown_or_unlink(self):
        channel = MagicMock(family=socket.AF_UNIX)
        channel.getsockopt.return_value = socket.SOCK_DGRAM
        channel.getsockname.return_value = "/run/library/wake"
        with patch.dict(os.environ, {"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "1"}), \
                patch.object(email_receiver.os.path, "isabs", return_value=True), \
                patch.object(email_receiver.os, "set_inheritable") as cloexec, \
                patch.object(email_receiver.socket, "socket", return_value=channel):
            with self.assertRaises(KeyboardInterrupt), email_receiver.inherited_socket("/run/library/wake"):
                raise KeyboardInterrupt()
        cloexec.assert_called_once_with(3, False)
        channel.close.assert_called_once()
        channel.shutdown.assert_not_called()

    @patch.object(socket, "AF_UNIX", 1, create=True)
    def test_wrong_socket_type_is_closed_and_rejected(self):
        channel = MagicMock(family=socket.AF_INET)
        with patch.dict(os.environ, {"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "1"}), \
                patch.object(email_receiver.os.path, "isabs", return_value=True), \
                patch.object(email_receiver.os, "set_inheritable"), \
                patch.object(email_receiver.socket, "socket", return_value=channel):
            with self.assertRaises(ImproperlyConfigured), email_receiver.inherited_socket("/run/library/wake"):
                pass
        channel.close.assert_called_once()

    @skipUnless(sys.platform.startswith("linux") and hasattr(socket, "AF_UNIX"),
                "Requires Linux Unix datagrams and inherited descriptors; systemd itself is not exercised.")
    def test_real_linux_descriptor_concurrent_datagrams_and_late_wake(self):
        # Child owns all descriptors and only uses sockets bound inside its own
        # temporary directory. Never replace fd 3 in the test-runner process.
        script = r'''
import os, socket, tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import django
django.setup()
from library.email_receiver import inherited_socket, receive_and_process, WAKE_MESSAGE
with tempfile.TemporaryDirectory(prefix="library-socket-test-") as root:
    path = root + "/wake"
    owner = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    owner.bind(path)
    manager = owner.dup()
    raw = owner.detach()
    if raw != 3:
        os.dup2(raw, 3)
        os.close(raw)
    os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS="1")
    def send(_=None):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
            sender.settimeout(1)
            sender.sendto(WAKE_MESSAGE, path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(send, range(4)))
    with inherited_socket(path) as channel:
        with patch("library.email_receiver.drain_outbox", side_effect=lambda **kw: send()) as worker:
            assert receive_and_process(channel)["valid"] == 4
            assert worker.call_count == 1
    # Manager's descriptor survives receiver close and retains the late signal.
    assert manager.recv(100) == WAKE_MESSAGE
    manager.close()
print("unix-descriptor-ok")
'''
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP", "PYTHONTZPATH") if key in os.environ}
        env.update(LIBRARY_ISOLATED_TESTS="1", DJANGO_SETTINGS_MODULE="config.test_settings")
        result = subprocess.run([sys.executable, "-B", "-c", script], env=env,
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unix-descriptor-ok", result.stdout)


class DirectDatabaseTests(SimpleTestCase):
    web = {"ENGINE": "django.db.backends.postgresql", "HOST": "ep-test-pooler.region.neon.tech", "NAME": "library"}
    url = "postgresql://worker:synthetic@ep-test.region.neon.tech/library?sslmode=require"

    def test_direct_worker_configuration_preserves_web(self):
        original = dict(self.web)
        cfg = worker_database(self.url, self.web)
        self.assertEqual(cfg["HOST"], "ep-test.region.neon.tech")
        self.assertEqual(cfg["CONN_MAX_AGE"], 0)
        self.assertEqual(self.web, original)

    def test_worker_settings_module_changes_only_worker_database(self):
        env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TMP", "TEMP") if key in os.environ}
        env.update(LIBRARY_ISOLATED_TESTS="1", DATABASE_URL=self.url.replace("ep-test.", "ep-test-pooler."),
                   LIBRARY_EMAIL_WORKER_DATABASE_URL=self.url)
        script = """
from config import settings
# Isolated base settings deliberately force SQLite. Supply only the synthetic
# web configuration before importing the separate worker settings module.
settings.DATABASES = {'default': settings.database_config()}
from config import email_worker_settings
assert settings.DATABASES['default']['HOST'] == 'ep-test-pooler.region.neon.tech'
assert email_worker_settings.DATABASES['default']['HOST'] == 'ep-test.region.neon.tech'
assert email_worker_settings.LIBRARY_EMAIL_WORKER_DIRECT is True
assert not email_worker_settings.LIBRARY_EMAIL_WORKER_ENABLED
print('isolated-settings-ok')
"""
        result = subprocess.run([sys.executable, "-B", "-c", script], env=env,
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("isolated-settings-ok", result.stdout)

    @override_settings(LIBRARY_EMAIL_WORKER_DIRECT=True)
    def test_connection_loss_during_acquire_and_unlock_closes_session(self):
        for effects in ([OSError("connection lost")], [None, OSError("connection lost")]):
            db = MagicMock(vendor="postgresql", in_atomic_block=False)
            db.settings_dict = {"ENGINE": "django.db.backends.postgresql", "HOST": "localhost"}
            cursor = db.cursor.return_value.__enter__.return_value
            cursor.execute.side_effect = effects
            cursor.fetchone.return_value = (True,)
            with patch("library.email_execution.connection", db), self.assertRaises(OSError), execution_lock():
                pass
            db.close.assert_called_once()

    def test_pooler_missing_wrong_database_and_unsupported_options_fail_closed(self):
        for url in (None, "", self.url.replace("ep-test.", "ep-test-pooler."),
                    self.url.replace("/library", "/other"), self.url + "&pool_mode=transaction",
                    self.url.replace("ep-test.", "ep-other."), self.url.replace("require", "disable"),
                    self.url + "&connect_timeout=0", "postgresql://worker:synthetic@[bad"):
            with self.subTest(url_type="invalid"), self.assertRaises(ImproperlyConfigured) as error:
                worker_database(url, self.web)
            self.assertNotIn("synthetic", str(error.exception))

    def test_default_web_settings_cannot_execute_worker(self):
        with override_settings(LIBRARY_EMAIL_WORKER_DIRECT=False), \
                patch("library.email_execution.connection") as db:
            with self.assertRaises(ImproperlyConfigured), execution_lock():
                pass
        db.cursor.assert_not_called()

    @override_settings(LIBRARY_EMAIL_WORKER_DIRECT=True)
    def test_lock_result_and_cleanup_on_busy_failed_acquire_and_failed_unlock(self):
        for results, raises in (([(False,)], False), ([(None,)], True), ([(True,), (False,)], True)):
            db = MagicMock(vendor="postgresql", in_atomic_block=False)
            db.settings_dict = {"ENGINE": "django.db.backends.postgresql", "HOST": "localhost"}
            db.cursor.return_value.__enter__.return_value.fetchone.side_effect = results
            with patch("library.email_execution.connection", db):
                if raises:
                    with self.assertRaises(RuntimeError), execution_lock():
                        pass
                else:
                    with execution_lock() as acquired:
                        self.assertFalse(acquired)
            db.close.assert_called_once()

    @override_settings(LIBRARY_EMAIL_WORKER_DIRECT=True)
    def test_pooled_runtime_configuration_rejected_before_connect(self):
        db = MagicMock(vendor="postgresql", in_atomic_block=False)
        db.settings_dict = self.web
        with patch("library.email_execution.connection", db):
            with self.assertRaises(ImproperlyConfigured), execution_lock():
                pass
        db.cursor.assert_not_called()
