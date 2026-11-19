"""Explicit, fail-closed gates. Importing this module never sends mail."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email
from uuid import UUID

EVENTS = frozenset({
    "loan_submitted", "book_request_submitted", "notify_registered",
    "borrow_confirmed", "reservation_confirmed", "notify_available",
    "book_now_available", "loan_returned", "due_date_changed", "loan_cancelled",
    "manual_email", "due_today", "overdue",
})


def enqueue_enabled():
    return getattr(settings, "LIBRARY_EMAIL_ENQUEUE_ENABLED", False)


def owns_event(event):
    owned = getattr(settings, "LIBRARY_EMAIL_OWNED_EVENTS", ())
    # n8n's current enrollment path shares the loan_submitted webhook route.
    if event in ("notify_registered", "loan_submitted") and not {"notify_registered", "loan_submitted"} <= set(owned):
        return False
    return (getattr(settings, "LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED", False) and event in owned)


def require_worker():
    if not getattr(settings, "LIBRARY_EMAIL_WORKER_ENABLED", False):
        raise ImproperlyConfigured("Library email worker is disabled.")


def recipient_allowlist():
    """Fail closed on empty/malformed configuration; no domains or wildcards."""
    values = getattr(settings, "LIBRARY_EMAIL_RECIPIENT_ALLOWLIST", ())
    if not isinstance(values, (list, tuple, set, frozenset)):
        return frozenset()
    result = set()
    for value in values:
        if not isinstance(value, str) or value != value.strip() or "\r" in value or "\n" in value:
            return frozenset()
        try:
            validate_email(value)
        except ValidationError:
            return frozenset()
        if "*" in value:
            return frozenset()
        result.add(value.casefold())
    return frozenset(result)


def recipient_allowed(address):
    if not isinstance(address, str) or address != address.strip() or "\r" in address or "\n" in address:
        return False
    try:
        validate_email(address)
    except ValidationError:
        return False
    return address.casefold() in recipient_allowlist()


def graph_mailbox_target():
    """Optional explicit mailbox identity; no directory lookup or credential reuse."""
    value = getattr(settings, "LIBRARY_GRAPH_MAILBOX_ID", "")
    if not value:
        return settings.LIBRARY_GRAPH_SENDER
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ImproperlyConfigured("LIBRARY_GRAPH_MAILBOX_ID must be the sender mailbox user's UUID.") from exc


def routes_to_django(event):
    """Future handoff only. Existing n8n routing is unchanged while flags are off."""
    if not owns_event(event):
        return False
    try:
        require_live_delivery()
    except ImproperlyConfigured:
        return False
    return True


def require_live_graph():
    require_worker()
    if email_provider() != "graph":
        raise ImproperlyConfigured("Microsoft Graph is not the selected email provider.")
    if not (enqueue_enabled() and getattr(settings, "LIBRARY_GRAPH_SEND_ENABLED", False)
            and getattr(settings, "LIBRARY_GRAPH_CREDENTIALS_APPROVED", False)
            and getattr(settings, "LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED", False)):
        raise ImproperlyConfigured("Live Graph delivery needs explicit activation, rotated credentials and n8n handoff.")
    if not recipient_allowlist():
        raise ImproperlyConfigured("Configure an explicit recipient allowlist before live Graph activation.")
    for name in ("LIBRARY_GRAPH_TENANT_ID", "LIBRARY_GRAPH_CLIENT_ID", "LIBRARY_GRAPH_CLIENT_SECRET", "LIBRARY_GRAPH_SENDER"):
        if not getattr(settings, name, ""):
            raise ImproperlyConfigured(f"{name} must be configured before activation.")
    try:
        validate_email(settings.LIBRARY_GRAPH_SENDER)
        if getattr(settings, "LIBRARY_GRAPH_REPLY_TO", ""):
            validate_email(settings.LIBRARY_GRAPH_REPLY_TO)
    except ValidationError as exc:
        raise ImproperlyConfigured("Configure valid Graph sender/Reply-To addresses before activation.") from exc
    graph_mailbox_target()


def email_provider():
    value = getattr(settings, "LIBRARY_EMAIL_PROVIDER", "gmail")
    if value not in ("gmail", "graph"):
        raise ImproperlyConfigured("LIBRARY_EMAIL_PROVIDER must explicitly be gmail or graph.")
    return value


def gmail_identities():
    """No guessed/default SMTP identity; validate before any OAuth request."""
    account = getattr(settings, "LIBRARY_GMAIL_ACCOUNT_EMAIL", "")
    sender = getattr(settings, "LIBRARY_GMAIL_SENDER", "")
    reply = getattr(settings, "LIBRARY_GMAIL_REPLY_TO", "") or sender
    name = getattr(settings, "LIBRARY_GMAIL_SENDER_NAME", "")
    for value in (account, sender, reply):
        if not isinstance(value, str) or value != value.strip() or "\r" in value or "\n" in value:
            raise ValidationError("Configure valid Gmail account, sender and Reply-To addresses.")
        validate_email(value)
    if not isinstance(name, str) or "\r" in name or "\n" in name:
        raise ValidationError("Invalid Gmail sender display name.")
    return account, sender, reply, name


def require_live_gmail():
    require_worker()
    if email_provider() != "gmail":
        raise ImproperlyConfigured("Gmail is not the selected email provider.")
    if not (enqueue_enabled() and getattr(settings, "LIBRARY_GMAIL_SEND_ENABLED", False)
            and getattr(settings, "LIBRARY_GMAIL_CREDENTIALS_APPROVED", False)
            and getattr(settings, "LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED", False)):
        raise ImproperlyConfigured("Live Gmail delivery needs explicit activation, approved OAuth credentials and n8n handoff.")
    if not recipient_allowlist():
        raise ImproperlyConfigured("Configure an explicit recipient allowlist before live Gmail activation.")
    for name in ("LIBRARY_GMAIL_CLIENT_ID", "LIBRARY_GMAIL_CLIENT_SECRET", "LIBRARY_GMAIL_REFRESH_TOKEN"):
        if not isinstance(getattr(settings, name, None), str) or not getattr(settings, name).strip():
            raise ImproperlyConfigured(f"{name} must be configured before activation.")
    try:
        gmail_identities()
    except ValidationError as exc:
        raise ImproperlyConfigured("Configure verified Gmail account, sender and Reply-To before activation.") from exc


def require_live_delivery():
    if email_provider() == "gmail":
        require_live_gmail()
    else:
        require_live_graph()
