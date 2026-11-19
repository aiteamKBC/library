"""Fixed integration-test envelopes and a durable one-POST budget per test."""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import re
from threading import Lock
from urllib.parse import quote

ADDRESS = "aiteam.kbc@gmail.com"
SUBJECT = "KBC Library — Gmail Integration Test"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/aiteam.kbc%40gmail.com/messages/send"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


@dataclass(frozen=True)
class TestScenario:
    name: str
    sender: str
    recipient: str
    subject: str
    profile: str
    marker_name: str

    @property
    def send_url(self):
        return f"https://gmail.googleapis.com/gmail/v1/users/{quote(self.sender, safe='')}/messages/send"


AI_TEAM_TEST = TestScenario("ai-team", ADDRESS, ADDRESS, SUBJECT, "ai-team-test",
                           "first-gmail-integration-test.attempted")
CHARLY_TEST = TestScenario("charly", "student@kentbusinesscollege.org", ADDRESS,
                          "KBC Library — Email Integration Test", "library",
                          "first-charly-gmail-integration-test.attempted")
SCENARIOS = {item.name: item for item in (AI_TEAM_TEST, CHARLY_TEST)}


class SingleTestError(RuntimeError):
    pass


def first_test_marker(scenario=AI_TEAM_TEST):
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise SingleTestError("local_test_storage_unavailable")
    return Path(local) / "KBC-Library" / "email-tests" / scenario.marker_name


def validate_grant(grant, scenario=AI_TEAM_TEST):
    if scenario == CHARLY_TEST:
        if (grant.get("credential_usage", "library") != "library"
                or grant.get("profile_name", "library") != "library"
                or grant.get("n8n_identity_confirmed") is not True
                or grant.get("account_email", "").casefold() != scenario.sender
                or grant.get("sender", "").casefold() != scenario.sender
                or "https://www.googleapis.com/auth/gmail.send" not in grant.get("scopes", [])
                or not grant.get("account_sub")
                or not all(grant.get(k) for k in ("client_id", "client_secret", "refresh_token"))):
            raise SingleTestError("confirmed_charly_library_grant_required")
        return
    if (grant.get("credential_usage") != "test_only" or grant.get("profile_name") != "ai-team-test"
            or grant.get("production_sender_approved") is not False
            or grant.get("account_email", "").casefold() != ADDRESS or grant.get("sender", "").casefold() != ADDRESS
            or not grant.get("account_sub") or not all(grant.get(k) for k in ("client_id", "client_secret", "refresh_token"))):
        raise SingleTestError("authorized_ai_team_test_grant_required")


def validate_send_request(request, scenario=AI_TEAM_TEST):
    if request.full_url != scenario.send_url or request.get_method() != "POST":
        raise SingleTestError("unauthorized_gmail_endpoint")
    body = json.loads(request.data)
    if set(body) != {"raw"}:
        raise SingleTestError("unexpected_gmail_payload")
    mime = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(body["raw"]))
    for header in ("To", "From", "Reply-To"):
        expected = scenario.recipient if header == "To" else scenario.sender
        values = mime.get_all(header, [])
        if len(values) != 1 or len(values[0].addresses) != 1 or values[0].addresses[0].addr_spec.casefold() != expected:
            raise SingleTestError("unauthorized_test_mailbox")
    if mime.get_all("Cc") or mime.get_all("Bcc") or mime.get_all("Resent-To") or mime.get_all("Resent-Bcc"):
        raise SingleTestError("extra_recipients_not_authorized")
    if len(mime.get_all("Subject", [])) != 1 or str(mime["Subject"]) != scenario.subject:
        raise SingleTestError("unauthorized_test_subject")
    if mime.get_content_type() != "text/html":
        raise SingleTestError("html_worker_template_required")


class SingleSendGuard:
    def __init__(self, transport, marker, message_id, *, scenario=AI_TEAM_TEST):
        self.transport, self.marker, self.message_id = transport, Path(marker), str(message_id)
        self.scenario = scenario
        self.send_calls = 0
        self.response = {}
        self._lock = Lock()

    def __call__(self, request):
        if request.full_url == TOKEN_URL and request.get_method() == "POST":
            return self.transport(request)
        if request.full_url == USERINFO_URL and request.get_method() == "GET":
            return self.transport(request)
        validate_send_request(request, self.scenario)
        with self._lock:
            if self.send_calls:
                raise SingleTestError("single_message_budget_already_used")
            self.marker.parent.mkdir(parents=True, exist_ok=True)
            # Written/fsynced BEFORE HTTP. Crash/timeout never permits another POST.
            try:
                fd = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                raise SingleTestError("first_real_test_already_attempted_no_resend") from None
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"message_id":self.message_id, "attempt_started_at":datetime.now(timezone.utc).isoformat(),
                           "scenario":self.scenario.name, "sender":self.scenario.sender,
                           "recipient":self.scenario.recipient, "subject":self.scenario.subject}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            self.send_calls += 1
        status, headers, raw = self.transport(request)
        self.response = {"http_status":status}
        if status == 200:
            try:
                value = json.loads(raw)
                message_id = value.get("id")
                if isinstance(message_id, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,190}", message_id):
                    self.response["gmail_message_id"] = message_id
                labels = value.get("labelIds", [])
                if isinstance(labels, list):
                    self.response["system_labels"] = [x for x in labels if x in ("INBOX", "SENT", "UNREAD", "SPAM")]
            except (ValueError, TypeError, AttributeError):
                pass  # The existing GmailClient determines accepted/uncertain.
        return status, headers, raw
