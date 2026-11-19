"""Transactional event producers. No transport, signals or on_commit gap."""
import hashlib
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .email_models import EmailOutbox
from .email_policy import enqueue_enabled, owns_event, routes_to_django
from .n8n_email_templates import ADMIN_RECIPIENT, template_version
from .timezones import validated_timezone

NAMESPACE = uuid.UUID("6810f28e-c74c-4b75-b164-722abf9ecdb7")
UNSENT = ("blocked", "pending", "retry_wait", "claimed")


def saved_zone(user):
    if user is None:
        return None
    from .models import UserProfile
    value = UserProfile.objects.filter(user_id=user.pk).values_list("time_zone", flat=True).first()
    try:
        validated_timezone(value)
    except (ValidationError, TypeError, ValueError):
        return None
    return value


def identity(source):
    stamp = getattr(source, "requested_at", None) or getattr(source, "submitted_at", None)
    return f"{source._meta.model_name}:{source.pk}:{stamp.isoformat() if stamp else ''}"


def event_uuid(source, event, suffix=""):
    return uuid.uuid5(NAMESPACE, f"{identity(source)}:{event}:{suffix}")


def enqueue(*, event, event_id, user, email, role, payload, loan=None, book_request=None,
            logical_key=None, kind="event", **snapshots):
    """Must be called in the source transaction. Unique index arbitrates races."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Email enqueue requires the source database transaction.")
    if not email:
        raise ValidationError("Email recipient has no address; configure the account before enabling enqueue.")
    recipient_key = f"user:{user.pk}" if user else "email:" + hashlib.sha256(email.lower().encode()).hexdigest()
    key = logical_key or hashlib.sha256(f"{event_id}:{recipient_key}:{role}".encode()).hexdigest()
    existing = EmailOutbox.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    zone = saved_zone(user)
    code = "" if zone else "recipient_timezone_missing"
    isolated = getattr(settings, "LIBRARY_ISOLATED_TESTS", False)
    if not owns_event(event) or (not isolated and not routes_to_django(event)):
        code = "n8n_handoff_required"
    try:
        with transaction.atomic():
            return EmailOutbox.objects.create(
                event_id=event_id, event_type=event, message_kind=kind,
                loan=loan, book_request=book_request, recipient=user,
                recipient_key=recipient_key, recipient_email=email, recipient_role=role,
                recipient_timezone=zone, template_key=f"{event}.{role}",
                template_version=template_version(f"{event}.{role}"), payload=payload,
                idempotency_key=key, status="blocked" if code else "pending",
                error_code=code, error_summary="Recipient timezone or event ownership requires review." if code else "",
                **snapshots,
            )
    except IntegrityError:
        existing = EmailOutbox.objects.filter(idempotency_key=key).first()
        if existing is None:
            raise
        return existing


def administrators(*, preserve_n8n_recipient=False):
    ids = getattr(settings, "LIBRARY_EMAIL_ADMIN_USER_IDS", ())
    users = list(get_user_model().objects.filter(pk__in=ids, is_active=True))
    from .models import UserProfile
    for user in users:
        if not (user.is_staff or UserProfile.objects.filter(user=user, role__in=("admin", "librarian")).exists()):
            raise ImproperlyConfigured("Configured email administrator must be library staff.")
    if not ids or len(users) != len(set(map(str, ids))) or any(not u.email for u in users):
        raise ImproperlyConfigured("Configure active LIBRARY_EMAIL_ADMIN_USER_IDS with email addresses before enqueue activation.")
    if preserve_n8n_recipient and (len(users) != 1 or users[0].email.casefold() != ADMIN_RECIPIENT.casefold()):
        raise ImproperlyConfigured("n8n compatibility requires exactly one configured administrator matching the exported borrow-request recipient.")
    return users


def library_url():
    return getattr(settings, "FRONTEND_BASE_URL", "http://localhost:3001").rstrip("/") + "/resources"


def loan_payload(loan):
    resource = loan.book_copy.resource if loan.book_copy_id else None
    return {
        "student_name": loan.borrower_name or (loan.borrower.get_full_name() if loan.borrower_id else "Student"),
        "book_title": resource.title if resource else "Library book", "loan_id": loan.pk,
        "copy_number": loan.book_copy.accession_number if loan.book_copy_id else None,
        "status": loan.status, "requested_at": loan.requested_at.isoformat(),
        "confirmed_at": (loan.approved_at or loan.borrowed_at).isoformat() if (loan.approved_at or loan.borrowed_at) else None,
        "returned_at": loan.returned_at.isoformat() if loan.returned_at else None,
        "requested_from": loan.requested_from.isoformat() if loan.requested_from else None,
        "due_date": loan.due_date.isoformat() if loan.due_date else None,
        "delivery_days": loan.delivery_days, "library_url": library_url(),
    }


def emit_loan(loan, event, *, suffix="", extra=None, admin=False):
    payload = {**loan_payload(loan), **(extra or {})}
    eid = event_uuid(loan, event, suffix)
    email = loan.borrower_email or (loan.borrower.email if loan.borrower_id else "")
    result = [enqueue(event=event, event_id=eid, user=loan.borrower, email=email,
                      role="student", payload=payload, loan=loan)]
    if admin:
        preserve = event == "loan_submitted" and template_version(f"{event}.admin") == 2
        admin_payload = {**payload, "borrower_email": loan.borrower_email, "borrower_phone": loan.borrower_phone}
        result.extend(enqueue(event=event, event_id=eid, user=u,
                              email=ADMIN_RECIPIENT if preserve else u.email,
                              role="admin", payload=admin_payload, loan=loan)
                      for u in administrators(preserve_n8n_recipient=preserve))
    return result


def cancel_stale_reminders(loan):
    rows = EmailOutbox.objects.filter(loan=loan, message_kind="reminder", status__in=UNSENT)
    if loan.status in ("borrowed", "overdue") and loan.returned_at is None:
        rows = rows.exclude(deadline_revision=loan.email_deadline_revision, due_date_snapshot=loan.due_date)
    rows.update(status="cancelled", lease_token=None, lease_expires_at=None, worker_id="",
                error_code="loan_changed", error_summary="Loan no longer matches the reminder snapshot.", updated_at=timezone.now())


def record_loan_change(loan, previous):
    if not enqueue_enabled():
        return
    # Compare persisted fields, including update_fields exclusions, rather than a
    # caller's potentially dirty in-memory instance.
    from .models import Loan
    loan = Loan.objects.select_related("borrower", "book_copy__resource").get(pk=loan.pk)
    cancel_stale_reminders(loan)
    if previous is None:
        if loan.loan_type == "notify" and loan.status == "requested":
            emit_loan(loan, "notify_registered")
        elif loan.loan_type == "borrow" and loan.status in ("requested", "reserved"):
            emit_loan(loan, "loan_submitted", admin=True)
    first_confirmation = (loan.status in ("approved", "borrowed")
                          and (previous is None or previous.status in ("requested", "reserved")))
    if first_confirmation:
        event = "reservation_confirmed" if previous and previous.status == "reserved" else "borrow_confirmed"
        emit_loan(loan, event)
    if previous and previous.due_date != loan.due_date and not first_confirmation:
        if loan.status in ("approved", "borrowed", "overdue"):
            emit_loan(loan, "due_date_changed", suffix=str(loan.email_deadline_revision), extra={
                "old_due_date": previous.due_date.isoformat() if previous.due_date else None,
                "old_delivery_days": previous.delivery_days,
            })
    if previous and loan.status == "cancelled" and previous.status != "cancelled":
        emit_loan(loan, "loan_cancelled")
    if previous and loan.status == "returned" and previous.status != "returned":
        from .views import build_feedback_url
        emit_loan(loan, "loan_returned", extra={"feedback_url": build_feedback_url(loan)})
        if loan.book_copy_id:
            waiting = Loan.objects.filter(book_copy__resource_id=loan.book_copy.resource_id, status="requested").exclude(pk=loan.pk)
            for target in waiting.select_related("borrower", "book_copy__resource"):
                event = "notify_available" if target.loan_type == "notify" else "book_now_available"
                # A notify enrollment receives one availability message. Waiting
                # borrow requests may be notified on distinct availability cycles.
                emit_loan(target, event, suffix="" if event == "notify_available" else str(event_uuid(loan, "loan_returned")))


def record_book_request(request):
    if not enqueue_enabled():
        return
    event = "book_request_submitted"
    eid = event_uuid(request, event)
    payload = {"student_name": request.student_name, "book_title": request.book_title,
               "requested_at": request.submitted_at.isoformat(), "status": request.status,
               "library_url": library_url()}
    enqueue(event=event, event_id=eid, user=request.requester, email=request.student_email,
            role="student", payload=payload, book_request=request)
    for user in administrators():
        enqueue(event=event, event_id=eid, user=user, email=user.email,
                role="admin", payload=payload, book_request=request)


def enqueue_manual(loan, *, subject, message, request_id):
    if not enqueue_enabled():
        raise ValidationError("Email enqueue is disabled.")
    try:
        request_id = uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationError("A stable UUID requestId is required for manual email retries.") from exc
    if "\n" in subject or "\r" in subject:
        raise ValidationError("Email subjects cannot contain newlines.")
    payload = {**loan_payload(loan), "manual_subject": subject, "manual_message": message}
    with transaction.atomic():
        row = enqueue(event="manual_email", event_id=event_uuid(loan, "manual_email", str(request_id)),
                      user=loan.borrower, email=loan.borrower_email, role="student", payload=payload, loan=loan)
        if row.payload.get("manual_subject") != subject or row.payload.get("manual_message") != message:
            raise ValidationError("This requestId already belongs to a different email.")
        return row
