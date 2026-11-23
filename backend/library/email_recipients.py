"""Source-bound recipient authorization. SELECTs only; no delivery or repair."""
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email

from .email_policy import EVENTS


REMINDER_EVENTS = frozenset({"due_today", "overdue"})
ADMIN_EVENTS = frozenset({"loan_submitted", "book_request_submitted"})


def _same_address(address, expected):
    if (not isinstance(expected, str) or expected != expected.strip()
            or "\r" in expected or "\n" in expected):
        return False
    try:
        validate_email(expected)
    except ValidationError:
        return False
    return address.casefold() == expected.casefold()


def source_recipient_allowed(message, address):
    """Bind the current source, role, account and address, never cached relations.

    Student request APIs can retain a caller-supplied contact email. Matching
    only that field would still authorize arbitrary mailboxes, so a student
    destination must also match the source owner's current active account.
    Configured administrators can receive legitimate guest-source notices.
    """
    from .models import BookRequest, Loan

    try:
        event = getattr(message, "event_type", None)
        role = getattr(message, "recipient_role", None)
        recipient_id = getattr(message, "recipient_id", None)
        if (event not in EVENTS or role not in ("student", "admin") or recipient_id is None
                or getattr(message, "recipient_key", None) != f"user:{recipient_id}"
                or not _same_address(address, getattr(message, "recipient_email", None))
                or getattr(message, "template_key", None) != f"{event}.{role}"
                or getattr(message, "message_kind", None) != (
                    "reminder" if event in REMINDER_EVENTS else "event")):
            return False
        if role == "admin" and event not in ADMIN_EVENTS:
            return False

        loan_id = getattr(message, "loan_id", None)
        request_id = getattr(message, "book_request_id", None)
        if event == "book_request_submitted":
            if (loan_id is not None or not request_id
                    or getattr(message, "source_type", None) != "book_request"
                    or getattr(message, "source_id", None) != str(request_id)):
                return False
            source = BookRequest.objects.filter(pk=request_id).values(
                "requester_id", "student_email", "requester__email", "requester__is_active").first()
            if source is None:
                return False
            owner_id, active = source["requester_id"], source["requester__is_active"]
            account_email, source_email = source["requester__email"], source["student_email"]
        else:
            if (request_id is not None or not loan_id
                    or getattr(message, "source_type", None) != "loan"
                    or getattr(message, "source_id", None) != str(loan_id)):
                return False
            source = Loan.objects.filter(pk=loan_id).values(
                "borrower_id", "borrower_email", "borrower__email", "borrower__is_active").first()
            if source is None:
                return False
            owner_id, active = source["borrower_id"], source["borrower__is_active"]
            account_email = source["borrower__email"]
            source_email = source["borrower_email"] or account_email

        if role == "student":
            return bool(owner_id is not None and str(owner_id) == str(recipient_id) and active
                        and _same_address(address, account_email)
                        and _same_address(address, source_email))

        from .email_events import administrators
        # Stored version-2 messages retain their approved original n8n
        # recipient even when the current compatibility switch is later off.
        preserve = event == "loan_submitted" and getattr(message, "template_version", None) == 2
        users = administrators(preserve_n8n_recipient=preserve)
        return any(str(user.pk) == str(recipient_id) and _same_address(address, user.email)
                   for user in users)
    except (AttributeError, TypeError, ValueError, ValidationError, ImproperlyConfigured):
        return False
