"""Finite delivery/recovery execution; no resident loop or retry sleeps.

The receiver and process_email_outbox share this execution path.
Defaults: at most five batches of 100 messages. A full budget leaves remaining
work durable for another invocation; more_due reports immediately recoverable
work, not future retries. No successful exit promises inbox delivery.

Managed commands require config.email_worker_settings and an explicit direct
LIBRARY_EMAIL_WORKER_DATABASE_URL; the web connection is unchanged. Session
advisory locks are incompatible with transaction pooling. All managed launches
must use this guard and one fixed OS unit with bounded concurrency. Set an
appropriate service timeout, restart-on-failure policy and boot/recovery timer.
Do not kill normal batches on a short timer: interrupted submissions become
uncertain and require review. The receiver code exists; OS units are not installed.
"""
from collections import Counter
from contextlib import contextmanager

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from .email_models import EmailOutbox
from .email_worker import EmailWorker
from config.email_worker_database import validate_direct_database

# Session advisory lock shared by event, scheduler and recovery invocations.
LOCK_ID = 681027243


@contextmanager
def execution_lock():
    if not getattr(settings, "LIBRARY_EMAIL_WORKER_DIRECT", False):
        raise ImproperlyConfigured("Use --settings=config.email_worker_settings for managed email execution.")
    validate_direct_database(connection.settings_dict)
    if connection.vendor != "postgresql":
        raise ImproperlyConfigured("Managed email execution requires PostgreSQL.")
    if connection.in_atomic_block:
        raise ImproperlyConfigured("Managed email execution must run outside transactions.")
    acquired = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
            result = cursor.fetchone()
            if not result or type(result[0]) is not bool:
                raise RuntimeError("Invalid email execution lock result.")
            acquired = result[0]
        yield acquired
    finally:
        try:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
                    result = cursor.fetchone()
                    if not result or result[0] is not True:
                        raise RuntimeError("Email execution lock ownership was lost.")
        finally:
            # This dedicated command owns its session, including busy/error paths.
            connection.close()


def drain_outbox(*, limit=100, max_batches=5):
    if not 1 <= limit <= 10000 or not 1 <= max_batches <= 100:
        raise ValueError("Invalid worker batch bounds.")
    with execution_lock() as acquired:
        if not acquired:
            return {"busy": True, "batches": 0, "outcomes": {}}
        worker = EmailWorker()
        counts = Counter()
        for batch in range(max_batches):
            results = worker.run_once(limit=limit)
            counts.update(results)
            if len(results) < limit:
                break
        now = timezone.now()
        more_due = EmailOutbox.objects.filter(
            Q(status__in=("pending", "retry_wait"), available_at__lte=now)
            | Q(status__in=("claimed", "submitting"), lease_expires_at__lte=now)).exists()
        # Never sleep for retries or replay uncertain mail. Phase 2 recovery timer
        # also covers the exit/wake race and expired leases beyond this batch.
        return {"busy": False, "batches": batch + 1, "outcomes": dict(counts),
                "more_due": more_due}
