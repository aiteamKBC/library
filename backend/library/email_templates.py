"""Versioned English template registry; all user content is autoescaped."""
from datetime import date, datetime
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.template.loader import render_to_string

from .notification_timing import format_recipient_timestamp
from .timezones import validated_timezone

COPY = {
    "loan_submitted.student": ("Borrow request received", "We have received your borrow request. The library team will review it."),
    "loan_submitted.admin": ("New library borrow request", "A student has submitted a borrow request. Please review it in Library Admin."),
    "book_request_submitted.student": ("Book request received", "Thank you for suggesting a book. The library team will review your request."),
    "book_request_submitted.admin": ("New book suggestion", "A student has requested a book. Please review the suggestion in Library Admin."),
    "notify_registered.student": ("Availability notification registered", "We will notify you when this book becomes available. This is not a borrowing confirmation."),
    "borrow_confirmed.student": ("Your borrowing is confirmed", "The library team has confirmed your borrowing. Please keep the return date below."),
    "reservation_confirmed.student": ("Your reservation is confirmed", "The library team has confirmed your reserved book. Please keep the return date below."),
    "notify_available.student": ("A book you are following is available", "A copy is now available. Visit the library to request it; availability can change."),
    "book_now_available.student": ("Your requested book is available", "A copy of your requested book is now available. The library team can review your waiting request."),
    "loan_returned.student": ("Book return recorded", "Thank you for returning your book. We would appreciate your feedback."),
    "due_date_changed.student": ("Your book return date has changed", "The library team has updated your borrowing details. Please use the new return date below."),
    "loan_cancelled.student": ("Borrow request cancelled", "Your borrow request has been cancelled."),
    "manual_email.student": ("Message from KBC Library", "The library team has sent you a message about your borrowing."),
    "due_today.student": ("Your library book is due today", "Please return your library book today, or contact the library team if you need help."),
    "overdue.student": ("Your library book is overdue", "Our records show that your book has not been returned. Please return it or contact the library team."),
}


def render_email(message):
    if message.template_version == 2:
        from .n8n_email_templates import render_n8n_email
        return render_n8n_email(message)
    if message.template_version != 1 or message.template_key not in COPY:
        raise ValidationError("Unsupported email template or version.")
    zone = message.recipient_timezone
    validated_timezone(zone)
    payload = message.payload
    subject, text = COPY[message.template_key]
    if message.event_type == "manual_email":
        subject = payload.get("manual_subject", "")
    if not subject or "\r" in subject or "\n" in subject:
        raise ValidationError("Invalid email subject.")
    rows = []
    if message.recipient_role in ("admin", "librarian"):
        rows.append(("Student", payload.get("student_name", "Student")))
    for key, label in (("requested_at", "Requested"), ("confirmed_at", "Confirmed"), ("returned_at", "Returned")):
        if payload.get(key):
            instant = datetime.fromisoformat(payload[key].replace("Z", "+00:00"))
            rows.append((label, format_recipient_timestamp(instant, zone) + f" ({zone})"))
    for key, label in (("requested_from", "Requested from"), ("old_due_date", "Previous return date"), ("due_date", "Return date")):
        if payload.get(key):
            rows.append((label, date.fromisoformat(payload[key]).strftime("%d %b %Y")))
    if payload.get("old_delivery_days") is not None:
        rows.append(("Previous delivery days", payload["old_delivery_days"]))
    if payload.get("delivery_days") is not None:
        rows.append(("Delivery days", payload["delivery_days"]))
    if payload.get("status"):
        rows.append(("Status", payload["status"].replace("_", " ").title()))
    links = []
    for key, label in (("library_url", "Visit KBC Library"), ("feedback_url", "Share your feedback")):
        url = payload.get(key)
        if url:
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
                raise ValidationError("Invalid library email link.")
            links.append((label, url))
    return subject, render_to_string("library/emails/message.html", {
        "heading": subject, "intro": text,
        "student_name": "Library Team" if message.recipient_role in ("admin", "librarian") else payload.get("student_name", "Student"),
        "book_title": payload.get("book_title", "Library book"), "rows": rows, "links": links,
        "manual_message": payload.get("manual_message") if message.event_type == "manual_email" else None,
    })
