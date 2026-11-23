"""App-only Graph transport. No network at import; no hidden sendMail retries."""
import json
import threading
import time
from urllib.parse import quote, urlencode
from urllib.request import Request

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import validate_email

from .email_policy import require_live_graph, owns_event, recipient_rejection, graph_mailbox_target
# Keep existing imports/tests/API compatible while the worker is provider-neutral.
from .email_transport import DeliveryResult as GraphResult, http_request, retry_after_seconds, safe_request_id


class GraphClient:
    provider = "graph"

    def __init__(self, transport=None):
        if transport is not None and not getattr(settings, "LIBRARY_ISOLATED_TESTS", False):
            raise ImproperlyConfigured("A fake Graph transport is restricted to isolated tests.")
        self.transport = transport or http_request
        self._test_transport = transport is not None
        self._token = None
        self._expires = 0
        self._lock = threading.Lock()

    def _access_token(self):
        with self._lock:
            if self._token and self._expires > time.monotonic() + 60:
                return self._token, None
            tenant = quote(settings.LIBRARY_GRAPH_TENANT_ID, safe="")
            body = urlencode({"grant_type": "client_credentials", "client_id": settings.LIBRARY_GRAPH_CLIENT_ID,
                              "client_secret": settings.LIBRARY_GRAPH_CLIENT_SECRET,
                              "scope": "https://graph.microsoft.com/.default"}).encode()
            req = Request(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", data=body,
                          headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
            try:
                status, headers, raw = self.transport(req)
                if status == 200:
                    value = json.loads(raw)
                    token, ttl = value["access_token"], int(value["expires_in"])
                    if not isinstance(token, str) or not token or ttl <= 0:
                        raise ValueError()
                    self._token, self._expires = token, time.monotonic() + ttl
                    return token, None
                transient = status == 429 or status >= 500
                return None, GraphResult("retryable_failure" if transient else "permanent_failure", status,
                                         "graph_auth_rejected", retry_after_seconds(headers.get("Retry-After")))
            except Exception:
                # No message has been submitted yet; retrying authentication is safe.
                return None, GraphResult("retryable_failure", code="graph_auth_unavailable")

    def send(self, message, subject, html):
        if self._test_transport and not getattr(settings, "LIBRARY_ISOLATED_TESTS", False):
            raise ImproperlyConfigured("A fake Graph transport cannot escape isolated test settings.")
        if not self._test_transport:
            require_live_graph()
            if not owns_event(message.event_type):
                raise ImproperlyConfigured("Django does not own this email event.")
        # Must precede token acquisition as well as sendMail, even with a fake
        # transport. Do not replace the recipient with a test address.
        rejection = recipient_rejection(message.recipient_email, message=message)
        if rejection:
            return GraphResult("permanent_failure", code=rejection)
        sender = settings.LIBRARY_GRAPH_SENDER
        validate_email(sender)
        validate_email(message.recipient_email)
        mailbox_target = graph_mailbox_target()
        reply_to = settings.LIBRARY_GRAPH_REPLY_TO or sender
        validate_email(reply_to)  # Validate before even acquiring an access token.
        token, error = self._access_token()
        if error:
            return error
        body = {"message": {"subject": subject, "body": {"contentType": "HTML", "content": html},
                            "toRecipients": [{"emailAddress": {"address": message.recipient_email}}]},
                "saveToSentItems": True}
        body["message"]["replyTo"] = [{"emailAddress": {"address": reply_to}}]
        request = Request(f"https://graph.microsoft.com/v1.0/users/{quote(mailbox_target, safe='')}/sendMail",
                          data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {token}",
                          "Content-Type": "application/json", "client-request-id": str(message.id)}, method="POST")
        try:
            status, headers, _ = self.transport(request)
        except Exception:
            return GraphResult("uncertain", code="graph_submission_unknown")
        trace = safe_request_id(headers)
        if status == 202:
            return GraphResult("accepted", status, request_id=trace)
        if status == 429 or status >= 500:
            return GraphResult("retryable_failure", status, "graph_temporary_rejection",
                               retry_after_seconds(headers.get("Retry-After")), trace)
        if status == 401:
            self._token = None
            return GraphResult("retryable_failure", status, "graph_token_rejected", request_id=trace)
        if status == 408 or 200 <= status < 300:
            return GraphResult("uncertain", status, "graph_submission_unknown", request_id=trace)
        return GraphResult("permanent_failure", status, "graph_permanent_rejection", request_id=trace)
