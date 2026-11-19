"""Static, reviewed n8n templates. No credentials or JavaScript evaluation.

Version 2 is opt-in for NEW outbox entries. Existing version 1 messages retain
their original rendering, even after configuration changes.
"""
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.template.loader import render_to_string

from .timezones import validated_timezone

REFERENCE = json.loads(Path(__file__).with_name("n8n_email_reference.json").read_text(encoding="utf-8"))
ADMIN_RECIPIENT = REFERENCE["admin_recipient"]
TEMPLATES = REFERENCE["templates"]


def template_version(key):
    return 2 if getattr(settings, "LIBRARY_EMAIL_N8N_COMPAT_ENABLED", False) and key in TEMPLATES else 1


def render_n8n_email(message):
    if message.template_key not in TEMPLATES:
        raise ValidationError("Unsupported n8n email template.")
    validated_timezone(message.recipient_timezone)
    payload = message.payload
    context = {key: payload.get(key) for key in (
        "student_name", "book_title", "loan_id", "copy_number", "borrower_email",
        "borrower_phone", "requested_from", "due_date", "feedback_url",
    )}
    if context["due_date"]:
        context["due_date_display"] = date.fromisoformat(context["due_date"]).strftime("%d %b %Y")
    if message.template_key == "loan_returned.student":
        url = context["feedback_url"] or ""
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise ValidationError("Invalid library email link.")
    reference = TEMPLATES[message.template_key]
    # Subjects are plain text; HTML is escaped separately by the Django loader.
    subject = Template(reference["subject"]).render(Context(context, autoescape=False, use_l10n=False))
    if not subject or "\r" in subject or "\n" in subject:
        raise ValidationError("Invalid email subject.")
    return subject, render_to_string("library/emails/n8n/" + reference["file"], context)
