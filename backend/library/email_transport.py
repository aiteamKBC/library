"""Provider-neutral transport results and bounded HTTPS helpers; no IO on import."""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPRedirectHandler


@dataclass(frozen=True)
class DeliveryResult:
    outcome: str  # accepted / retryable_failure / permanent_failure / uncertain
    http_status: int | None = None
    code: str = ""
    retry_after: int = 0
    request_id: str = ""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a token or replay a message POST.


def http_request(request, *, read_error_body=False):
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            return response.status, response.headers, response.read(1024 * 1024)
    except HTTPError as exc:
        try:
            # Gmail uses a small reason/code allowlist. Never log/persist this body.
            raw = exc.read(65536) if read_error_body else b""
            return exc.code, exc.headers, raw
        finally:
            exc.close()


def retry_after_seconds(value, now=None):
    if not value:
        return 0
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try:
            target = parsedate_to_datetime(value)
            return max(0, int((target - (now or datetime.now(timezone.utc))).total_seconds()))
        except (ValueError, TypeError, OverflowError):
            return 0


def safe_request_id(headers):
    value = headers.get("request-id", "")
    return value if re.fullmatch(r"[a-zA-Z0-9-]{1,100}", value) else ""
