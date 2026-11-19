"""Google OAuth2 + Gmail send transport. No IO on import or construction.

Only refreshes the separately authorized Django grant. No n8n token extraction,
provider fallback, hidden send retry, or credential persistence/logging.
"""
import base64
import json
import re
import threading
import time
from email.headerregistry import Address
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from urllib.parse import quote, urlencode
from urllib.request import Request

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from .email_policy import gmail_identities, owns_event, recipient_allowed, require_live_gmail
from .email_transport import DeliveryResult, http_request, retry_after_seconds

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SEND_SCOPES = {SEND_SCOPE, "https://www.googleapis.com/auth/gmail.compose",
               "https://www.googleapis.com/auth/gmail.modify", "https://mail.google.com/"}
TOKEN_URL = "https://oauth2.googleapis.com/token"
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}


def gmail_http_request(request):
    return http_request(request, read_error_body=True)


def response_object(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, UnicodeDecodeError):
        return {}


class GmailClient:
    provider = "gmail"

    def __init__(self, transport=None):
        if transport is not None and not getattr(settings, "LIBRARY_ISOLATED_TESTS", False):
            raise ImproperlyConfigured("A fake Gmail transport is restricted to isolated tests.")
        self.transport = transport if transport is not None else gmail_http_request
        self._test_transport = transport is not None
        self._token = None
        self._expires = 0
        self._lock = threading.Lock()

    def _access_token(self):
        with self._lock:
            if self._token and self._expires > time.monotonic() + 60:
                return self._token, None
            body = urlencode({
                "grant_type": "refresh_token",
                "client_id": settings.LIBRARY_GMAIL_CLIENT_ID,
                "client_secret": settings.LIBRARY_GMAIL_CLIENT_SECRET,
                "refresh_token": settings.LIBRARY_GMAIL_REFRESH_TOKEN,
            }).encode("utf-8")
            request = Request(TOKEN_URL, data=body, method="POST",
                              headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                status, headers, raw = self.transport(request)
                value = response_object(raw)
                if status == 200:
                    token, ttl = value.get("access_token"), int(value.get("expires_in", 0))
                    if (not isinstance(token, str) or not token or re.search(r"\s", token)
                            or ttl <= 0 or value.get("token_type", "").lower() != "bearer"):
                        raise ValueError()
                    if "scope" in value and not SEND_SCOPES.intersection(value["scope"].split()):
                        return None, DeliveryResult("permanent_failure", status, "gmail_scope_missing")
                    self._token, self._expires = token, time.monotonic() + ttl
                    return token, None
                if value.get("error") == "invalid_grant":
                    return None, DeliveryResult("permanent_failure", status, "gmail_reauthorization_required")
                transient = (status == 429 or status >= 500
                             or value.get("error") in ("temporarily_unavailable", "server_error"))
                return None, DeliveryResult("retryable_failure" if transient else "permanent_failure", status,
                                            "gmail_auth_unavailable" if transient else "gmail_auth_rejected",
                                            retry_after_seconds(headers.get("Retry-After")))
            except Exception:
                # No message POST happened: retrying token acquisition is safe.
                return None, DeliveryResult("retryable_failure", code="gmail_auth_unavailable")

    def _invalidate_token(self, used_token):
        with self._lock:
            if self._token == used_token:
                self._token, self._expires = None, 0

    def send(self, message, subject, html):
        if self._test_transport and not getattr(settings, "LIBRARY_ISOLATED_TESTS", False):
            raise ImproperlyConfigured("A fake Gmail transport cannot escape isolated test settings.")
        if not self._test_transport:
            require_live_gmail()
            if not owns_event(message.event_type):
                raise ImproperlyConfigured("Django does not own this email event.")
        # Check before BOTH OAuth and send, including when a token is cached.
        if not recipient_allowed(message.recipient_email):
            return DeliveryResult("permanent_failure", code="recipient_not_allowlisted")
        account, sender, reply, name = gmail_identities()
        validate_email(message.recipient_email)
        if not isinstance(subject, str) or not subject or "\r" in subject or "\n" in subject:
            raise ValidationError("Invalid email subject.")
        mime = EmailMessage(policy=SMTP)
        mime["From"] = Address(display_name=name, addr_spec=sender)
        mime["To"] = Address(addr_spec=message.recipient_email)
        mime["Reply-To"] = Address(addr_spec=reply)
        mime["Subject"] = subject
        mime["Date"] = format_datetime(timezone.now())
        # Stable for diagnostics, NOT a promise of Gmail-side deduplication.
        mime["Message-ID"] = f"<{message.id}@{sender.rsplit('@', 1)[1]}>"
        mime.set_content(html, subtype="html", charset="utf-8")
        body = json.dumps({"raw": base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")}).encode("utf-8")
        token, error = self._access_token()
        if error:
            return error
        # Target the explicitly verified account; 'me' would conceal a grant for
        # the wrong Google account. Sender aliases need separate prior approval.
        request = Request(f"https://gmail.googleapis.com/gmail/v1/users/{quote(account, safe='')}/messages/send",
                          data=body, method="POST",
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            status, headers, raw = self.transport(request)
        except Exception:
            return DeliveryResult("uncertain", code="gmail_submission_unknown")
        value = response_object(raw)
        message_id = value.get("id")
        if status == 200 and isinstance(message_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,190}", message_id):
            return DeliveryResult("accepted", status, request_id="gmail:" + message_id)
        if status == 401:
            self._invalidate_token(token)
            # Worker backoff creates a recorded next attempt; no hidden replay.
            return DeliveryResult("retryable_failure", status, "gmail_token_rejected")
        error_value = value.get("error")
        errors = error_value.get("errors", []) if isinstance(error_value, dict) else []
        reasons = {item.get("reason") for item in errors if isinstance(item, dict)
                   and isinstance(item.get("reason"), str)} if isinstance(errors, list) else set()
        if status == 429 or (status == 403 and reasons.intersection(RATE_REASONS)):
            return DeliveryResult("retryable_failure", status, "gmail_rate_limited",
                                  retry_after_seconds(headers.get("Retry-After")))
        if status in (408, 504) or 200 <= status < 400:
            return DeliveryResult("uncertain", status, "gmail_submission_unknown")
        if status >= 500:
            # Only a structured, matching Gmail rejection is retried. A gateway
            # page/truncated response does not establish whether Gmail accepted.
            if isinstance(error_value, dict) and error_value.get("code") == status:
                return DeliveryResult("retryable_failure", status, "gmail_temporary_rejection",
                                      retry_after_seconds(headers.get("Retry-After")))
            return DeliveryResult("uncertain", status, "gmail_submission_unknown")
        return DeliveryResult("permanent_failure", status, "gmail_permanent_rejection")
