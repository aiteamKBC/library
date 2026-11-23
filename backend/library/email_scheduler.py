"""Current local-day reminders only; no catch-up cursor or third table."""
import logging
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .email_events import enqueue, event_uuid, identity, loan_payload, saved_zone
from .email_models import EmailOutbox
from .email_policy import enqueue_enabled, owns_event, routes_to_django
from .notification_timing import due_reminder
from .email_activation import coalesce_wakeups, wake_after_commit

logger = logging.getLogger(__name__)


def revive_unsent_reminder(row, loan, plan):
    """Caller holds Loan then Outbox locks. Never resurrect a submitted message."""
    if (row.status != "cancelled" or row.error_code not in {"reminder_day_expired", "invalid_local_reminder_time"}
            or row.message_kind != "reminder" or row.loan_id != loan.pk
            or row.recipient_id != loan.borrower_id or row.recipient_role != "student"
            or row.recipient_key != f"user:{loan.borrower_id}"
            or row.recipient_email != (loan.borrower_email or loan.borrower.email)
            or row.event_type != plan.event or row.due_date_snapshot != plan.due_date
            or row.deadline_revision != plan.deadline_revision or row.reminder_local_date != plan.local_day
            or row.accepted_at is not None or row.attempts_count != 0 or row.attempts.exists()):
        return False
    if not owns_event(plan.event) or (not getattr(settings, "LIBRARY_ISOLATED_TESTS", False) and not routes_to_django(plan.event)):
        return False
    row.recipient_timezone = plan.recipient_timezone
    row.available_at, row.expires_at = plan.scheduled_at_utc, plan.expires_at_utc
    row.payload = {**loan_payload(loan), "days_overdue": plan.days_overdue}
    row.status, row.error_code, row.error_summary = "pending", "", ""
    row.lease_token = row.lease_expires_at = None
    row.worker_id = ""
    row.save()
    wake_after_commit()
    return True


def last_accepted_day(loan, recipient_key):
    values = EmailOutbox.objects.filter(
        loan=loan, recipient_key=recipient_key, message_kind="reminder", status="accepted",
        deadline_revision=loan.email_deadline_revision,
    ).values_list("payload", flat=True)
    days = [p.get("days_overdue") for p in values if isinstance(p.get("days_overdue"), int)]
    return max(days) if days else None


@coalesce_wakeups()
def schedule_reminders(*, now=None, limit=1000):
    if not (enqueue_enabled() and getattr(settings, "LIBRARY_EMAIL_SCHEDULER_ENABLED", False)):
        return {"disabled": True, "scanned": 0, "queued": 0, "missing_timezone": 0}
    from .models import Loan
    now = now or timezone.now()
    counts = {"disabled": False, "scanned": 0, "queued": 0, "missing_timezone": 0}
    # Rotate the scan by last check is not required: the command scans all active
    # rows in bounded-memory chunks. limit caps NEW messages, not eligible loans.
    ids = Loan.objects.filter(status__in=("borrowed", "overdue"), returned_at__isnull=True,
                              due_date__isnull=False).values_list("pk", flat=True).iterator(chunk_size=200)
    for pk in ids:
        if counts["queued"] >= limit:
            break
        with transaction.atomic():
            loan = Loan.objects.select_for_update().filter(pk=pk).first()
            if loan is None:
                continue  # Source may have been deleted after the scan.
            counts["scanned"] += 1
            zone = saved_zone(loan.borrower)
            if not zone:
                counts["missing_timezone"] += 1
                logger.warning("Library reminder blocked: missing/invalid recipient timezone (loan_id=%s).", loan.pk)
                continue  # Never invent a local calendar day/09:00.
            key = f"user:{loan.borrower_id}"
            plan = due_reminder(loan_id=identity(loan), recipient_key=key, recipient_role="student",
                                due_date=loan.due_date, deadline_revision=loan.email_deadline_revision,
                                recipient_timezone=zone, now=now, status=loan.status, returned_at=loan.returned_at,
                                last_sent_days_overdue=last_accepted_day(loan, key))
            if plan is None:
                continue
            logical_key = "reminder:" + plan.logical_key
            existing = EmailOutbox.objects.select_for_update().filter(idempotency_key=logical_key).first()
            if existing is not None:
                counts["queued"] += int(revive_unsent_reminder(existing, loan, plan))
                continue
            enqueue(event=plan.event, event_id=event_uuid(loan, plan.event, plan.logical_key), user=loan.borrower,
                    email=loan.borrower_email or loan.borrower.email, role="student", loan=loan, kind="reminder",
                    logical_key=logical_key, payload={**loan_payload(loan), "days_overdue": plan.days_overdue},
                    due_date_snapshot=plan.due_date, deadline_revision=plan.deadline_revision,
                    reminder_local_date=plan.local_day, available_at=plan.scheduled_at_utc, expires_at=plan.expires_at_utc)
            counts["queued"] += 1
    return counts
