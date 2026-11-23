"""Test-only independent process. Accepts only the guarded disposable cluster."""
import os
import sys
from unittest.mock import patch


def main():
    if os.environ.get("LIBRARY_ISOLATED_TESTS") != "1":
        raise RuntimeError("Isolated test process required.")
    port = int(os.environ["KBC_SYNTHETIC_PG_PORT"])
    if not 1024 <= port <= 65535:
        raise RuntimeError("Invalid synthetic port.")
    # Do not inherit application settings, credentials, libpq services or .env.
    retained = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PYTHONTZPATH") if key in os.environ}
    os.environ.clear()
    os.environ.update(retained)
    os.environ.update(LIBRARY_ISOLATED_TESTS="1", KBC_SYNTHETIC_PG_PORT=str(port),
                      DJANGO_SETTINGS_MODULE="config.test_settings")
    from config import test_settings
    test_settings.DATABASES["default"]["NAME"] = "test_kbc_phase3_tests"
    test_settings.LIBRARY_EMAIL_WORKER_DIRECT = True
    import django
    django.setup()
    from django.db import connection
    from django.test import override_settings
    from library.email_execution import execution_lock, drain_outbox
    from library.email_models import EmailOutbox
    from library.email_worker import EmailWorker
    from library.email_policy import EVENTS
    from library.graph_client import GraphResult

    mode = sys.argv[1]
    if mode == "lock":
        with execution_lock() as acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pid = cursor.fetchone()[0]
            print(f"locked:{int(acquired)}:{pid}", flush=True)
            if sys.stdin.readline().strip() == "fail":
                raise RuntimeError("Synthetic worker failure.")
        return

    class FakeProvider:
        provider = "graph"

        def send(self, *args):
            print("submitting", flush=True)
            sys.stdin.readline()
            return GraphResult("accepted", 202)

    if mode not in ("worker", "claim"):
        raise RuntimeError("Unsupported isolated mode.")
    recipients = tuple(EmailOutbox.objects.values_list("recipient_email", flat=True))
    with override_settings(LIBRARY_EMAIL_WORKER_ENABLED=True, LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=True,
                           LIBRARY_EMAIL_OWNED_EVENTS=tuple(EVENTS), LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=recipients):
        worker = EmailWorker(client=FakeProvider())
        if mode == "claim":
            with execution_lock() as acquired:
                if not acquired:
                    raise RuntimeError("Synthetic claim process could not acquire lock.")
                worker.claim()
                print("claimed", flush=True)
                sys.stdin.readline()
            return
        with patch("library.email_execution.EmailWorker", return_value=worker):
            print(drain_outbox(limit=1, max_batches=1), flush=True)


if __name__ == "__main__":
    main()
