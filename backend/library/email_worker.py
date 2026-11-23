"""Short PostgreSQL claims, durable submission fence, bounded safe retries."""
import random
import uuid
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection, transaction
from django.db.models import Max
from django.utils import timezone

from .email_events import identity, saved_zone, availability_eligible, DEADLINE_EVENTS, deadline_event_is_current
from .email_models import EmailOutbox, EmailAttempt
from .email_policy import owns_event, require_worker, require_live_delivery, recipient_allowed, email_provider
from .email_providers import create_email_client
from .email_scheduler import last_accepted_day
from .email_templates import render_email
from .email_transport import DeliveryResult
from .notification_timing import due_reminder, local_reminder_window
from .timezones import validated_timezone


def clear_lease(row):
    row.lease_token = row.lease_expires_at = None
    row.worker_id = ""


@contextmanager
def locked_message(pk):
    """Resource -> Loan -> Outbox, matching availability writers."""
    from .models import Loan, Resource
    with transaction.atomic():
        loan_id = EmailOutbox.objects.filter(pk=pk).values_list("loan_id", flat=True).first()
        resource_id = Loan.objects.filter(pk=loan_id).values_list("book_copy__resource_id", flat=True).first() if loan_id else None
        Resource.lock_availability(resource_id)
        loan = Loan.objects.select_for_update().filter(pk=loan_id).first() if loan_id else None
        row = EmailOutbox.objects.select_for_update().filter(pk=pk).first()
        yield row, loan


def stop(row, state, code):
    row.status, row.error_code = state, code
    row.error_summary = code.replace("_", " ").capitalize() + "."
    clear_lease(row)
    row.save()


def eligibility(row, loan, now):
    """Returns (action, code). Re-evaluated at the durable submission boundary."""
    if row.event_type in ("notify_registered", "notify_available") and loan and loan.loan_type != "notify":
        return "cancelled", "notify_request_converted"
    if row.event_type in DEADLINE_EVENTS and not deadline_event_is_current(row, loan):
        return "cancelled", "stale_loan_deadline"
    if not owns_event(row.event_type):
        return "blocked", "n8n_handoff_required"
    if not recipient_allowed(row.recipient_email):
        return "blocked", "recipient_not_allowlisted"
    zone = saved_zone(row.recipient)
    if not zone:
        return "blocked", "recipient_timezone_missing"
    row.recipient_timezone = zone
    if row.expires_at and now >= row.expires_at:
        # Re-evaluate timezone changes below for reminder windows first.
        if row.message_kind != "reminder":
            return "cancelled", "message_expired"
    if row.source_type == "loan" and loan is None:
        return "cancelled", "source_deleted"
    if row.message_kind == "reminder":
        if (loan is None or loan.status not in ("borrowed", "overdue") or loan.returned_at is not None
                or loan.due_date != row.due_date_snapshot or loan.email_deadline_revision != row.deadline_revision):
            return "cancelled", "stale_reminder"
        local_day = now.astimezone(validated_timezone(zone)).date()
        if row.reminder_local_date != local_day:
            return "cancelled", "reminder_day_expired"
        window = local_reminder_window(local_day, zone)
        if window is None:
            return "cancelled", "invalid_local_reminder_time"
        row.expires_at = window[1]
        if now < window[0]:
            row.available_at = window[0]
            return "pending", "recipient_timezone_rescheduled"
        plan = due_reminder(loan_id=identity(loan), recipient_key=row.recipient_key,
                            recipient_role=row.recipient_role, due_date=loan.due_date,
                            deadline_revision=loan.email_deadline_revision, recipient_timezone=zone,
                            now=now, status=loan.status, returned_at=loan.returned_at,
                            last_sent_days_overdue=last_accepted_day(loan, row.recipient_key))
        if plan is None or "reminder:" + plan.logical_key != row.idempotency_key:
            return "cancelled", "stale_reminder"
    if row.event_type in ("notify_available", "book_now_available"):
        expected_type = "notify" if row.event_type == "notify_available" else "borrow"
        if loan is None or loan.loan_type != expected_type or not availability_eligible(loan):
            return "cancelled", "availability_changed"
        # Old return-cycle outboxes must not cause a second send for an already
        # notified enrollment. Resource lock serializes concurrent submissions.
        siblings = EmailOutbox.objects.filter(loan=loan, event_type=row.event_type,
                                               recipient_role=row.recipient_role).exclude(pk=row.pk)
        if siblings.filter(status__in=("accepted", "uncertain", "submitting")).exists():
            return "cancelled", "availability_already_notified"
    if row.event_type in DEADLINE_EVENTS and EmailOutbox.objects.filter(
        loan=loan, event_type__in=DEADLINE_EVENTS, recipient_key=row.recipient_key,
        recipient_role=row.recipient_role, status="submitting",
    ).exclude(pk=row.pk).exists():
        # Serialize deadline submissions, without holding a DB lock during IO.
        # Expired submitting leases become uncertain through normal recovery.
        row.available_at = now + timedelta(seconds=30)
        return ("retry_wait" if row.attempts_count else "pending"), "loan_email_in_flight"
    return None, ""


class EmailWorker:
    def __init__(self, *, worker_id=None, client=None):
        require_worker()
        isolated = getattr(settings, "LIBRARY_ISOLATED_TESTS", False)
        if client is not None and not isolated:
            raise ImproperlyConfigured("Injected email clients are restricted to isolated tests.")
        if client is None:
            require_live_delivery()  # Disabled worker cannot even claim a row.
        if connection.vendor != "postgresql" and not isolated:
            raise ImproperlyConfigured("Email workers require PostgreSQL row locking.")
        self.client = client if client is not None else create_email_client()
        self.provider = getattr(self.client, "provider", email_provider())
        self.worker_id = worker_id or f"library-{uuid.uuid4()}"

    def claim(self, *, now=None):
        now = now or timezone.now()
        with transaction.atomic():
            rows = EmailOutbox.objects.filter(status__in=("pending", "retry_wait"), available_at__lte=now)
            if connection.features.has_select_for_update_skip_locked:
                rows = rows.select_for_update(skip_locked=True)
            else:
                rows = rows.select_for_update()
            row = rows.order_by("available_at", "id").first()
            if row is None:
                return None
            row.status, row.lease_token, row.worker_id = "claimed", uuid.uuid4(), self.worker_id
            row.lease_expires_at = now + timedelta(seconds=settings.LIBRARY_EMAIL_LEASE_SECONDS)
            row.save()
            return row.pk, row.lease_token

    def recover_expired(self, *, now=None, limit=100):
        now = now or timezone.now()
        ids = list(EmailOutbox.objects.filter(status__in=("claimed", "submitting"), lease_expires_at__lte=now)
                   .values_list("pk", flat=True)[:limit])
        for pk in ids:
            with locked_message(pk) as (row, _):
                if not row or row.status not in ("claimed", "submitting") or row.lease_expires_at > now:
                    continue
                if row.status == "claimed":
                    stop(row, "pending", "claim_lease_expired")
                else:
                    EmailAttempt.objects.filter(message=row, result="started", lease_token=row.lease_token).update(
                        result="uncertain", finished_at=now, error_code="submission_lease_expired",
                        error_summary="Submission lease expired; acceptance cannot be established.")
                    stop(row, "uncertain", "submission_lease_expired")
        return len(ids)

    def process(self, claim, *, now=None):
        fixed_now = now
        now = now or timezone.now()
        pk, token = claim
        with locked_message(pk) as (row, loan):
            if not row or row.status != "claimed" or row.lease_token != token or row.lease_expires_at <= now:
                return "fenced"
            action, code = eligibility(row, loan, now)
            if action:
                stop(row, action, code)
                return action
            previous_provider = row.payload.get("_email_provider")
            if previous_provider is None and (row.attempts_count or row.attempts.exists()):
                previous_provider = "graph"  # Attempts predating provider selection.
            if previous_provider is not None and previous_provider != self.provider:
                stop(row, "blocked", "delivery_provider_changed")
                return "blocked"
            try:
                subject, html = render_email(row)
            except (ValidationError, ValueError, TypeError, KeyError):
                stop(row, "failed", "template_validation_failed")
                return "failed"
            last = row.attempts.aggregate(number=Max("attempt_number"))["number"] or 0
            if max(last, row.attempts_count) >= settings.LIBRARY_EMAIL_MAX_ATTEMPTS:
                stop(row, "failed", "retry_limit_reached")
                return "failed"
            row.attempts_count = max(last, row.attempts_count) + 1
            row.payload = {**row.payload, "_email_provider": self.provider}
            attempt = EmailAttempt.objects.create(message=row, attempt_number=row.attempts_count,
                result="started", started_at=now, worker_id=self.worker_id, lease_token=token)
            row.status = "submitting"
            row.error_code = row.error_summary = ""
            row.save()
        # A process crash from here onwards is UNCERTAIN, even before HTTP starts.
        # Never hold a database lock across a provider's external request.
        try:
            result = self.client.send(row, subject, html)
            if result.outcome not in ("accepted", "retryable_failure", "permanent_failure", "uncertain"):
                raise ValueError()
        except Exception:
            result = DeliveryResult("uncertain", code="submission_result_unknown")
        finished = fixed_now or timezone.now()
        with locked_message(pk) as (current, loan):
            if not current or current.status != "submitting" or current.lease_token != token:
                return "fenced"
            if current.lease_expires_at <= finished:
                result = DeliveryResult("uncertain", code="submission_lease_expired")
            # Only allow the worker's sanitized result vocabulary into durable logs.
            allowed_codes = {"", "graph_auth_rejected", "graph_auth_unavailable", "graph_submission_unknown",
                             "recipient_not_allowlisted",
                             "graph_temporary_rejection", "graph_token_rejected", "graph_permanent_rejection",
                             "gmail_auth_rejected", "gmail_auth_unavailable", "gmail_reauthorization_required",
                             "gmail_scope_missing", "gmail_token_rejected", "gmail_rate_limited",
                             "gmail_temporary_rejection", "gmail_permanent_rejection", "gmail_submission_unknown",
                             "submission_result_unknown", "submission_lease_expired"}
            code = result.code if result.code in allowed_codes else "submission_result_unknown"
            attempt.result, attempt.finished_at = result.outcome, finished
            attempt.http_status, attempt.provider_request_id = result.http_status, result.request_id
            attempt.error_code, attempt.error_summary = code, code.replace("_", " ")
            attempt.save()
            current.provider_request_id = result.request_id
            current.error_code, current.error_summary = code, code.replace("_", " ")
            if result.outcome == "accepted":
                current.status, current.accepted_at = "accepted", finished
            elif result.outcome == "uncertain":
                current.status = "uncertain"
            elif result.outcome == "permanent_failure" or current.attempts_count >= settings.LIBRARY_EMAIL_MAX_ATTEMPTS:
                current.status = "failed"
            else:
                current.status = "retry_wait"
                delay = max(result.retry_after, min(3600, 30 * 2 ** (current.attempts_count - 1)) + random.randint(0, 10))
                current.available_at = finished + timedelta(seconds=delay)
            clear_lease(current)
            current.save()
            # locked_message re-reads and locks the request after provider IO.
            # Acceptance of an old notification must not close a converted loan.
            if (result.outcome == "accepted" and current.event_type == "notify_available"
                    and loan and loan.loan_type == "notify" and loan.status == "requested" and loan.returned_at is None):
                loan.status = "notify"
                loan.save(update_fields={"status"})
            return current.status

    def run_once(self, *, limit=100, now=None):
        self.recover_expired(now=now)
        results = []
        for _ in range(limit):
            claim = self.claim(now=now)
            if claim is None:
                break
            results.append(self.process(claim, now=now))
        return results


def retry_message(pk, *, actor):
    """Explicit staff action only; never resubmit accepted/uncertain messages."""
    from .models import UserProfile
    if not actor.is_active or not (actor.is_staff or UserProfile.objects.filter(user=actor, role__in=("admin", "librarian")).exists()):
        raise ValidationError("Only library staff may retry email.")
    with locked_message(pk) as (row, loan):
        if not row or row.status not in ("blocked", "failed"):
            raise ValidationError("Only blocked or definitively failed messages can be retried.")
        if row.error_code == "n8n_handoff_required":
            raise ValidationError("Shadow messages must not be replayed during n8n handoff.")
        action, _ = eligibility(row, loan, timezone.now())
        if action and action != "pending":
            raise ValidationError("Recipient, event ownership or source is not ready for retry.")
        # Manual retry must be bounded too. A new message is a separately reviewed
        # business action, not a way to silently reset attempt history.
        if row.attempts_count >= settings.LIBRARY_EMAIL_MAX_ATTEMPTS:
            raise ValidationError("Retry limit reached; investigate before creating any new message.")
        row.status, row.available_at = "pending", timezone.now()
        row.error_code = row.error_summary = ""
        row.save()
        from .email_activation import wake_after_commit
        wake_after_commit()
        return row
