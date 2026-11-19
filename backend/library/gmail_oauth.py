"""One-time local OAuth bootstrap, isolated from Django/DB/workers and send APIs."""
import base64
import hashlib
import hmac
from html import escape
import json
import re
import secrets
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request
import webbrowser

from .email_transport import http_request
from .gmail_credential_store import CredentialStoreError, PROFILE_FILES, TEST_PROFILE, save_credentials

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REDIRECT_URI = "http://127.0.0.1:8765/oauth2/callback"
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
SCOPES = ("openid", "email", SEND_SCOPE)
# Native form POSTs under no-referrer send Origin:null. Keep a verifiable
# same-origin POST without putting the callback path/code in Referer.
CONFIRMATION_REFERRER_POLICY = "origin"


class OAuthError(Exception):
    """Only static, safe codes may cross the CLI boundary."""


def load_client(path):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        value = document["web"]
        if (not isinstance(value, dict) or not re.fullmatch(r"[a-zA-Z0-9._-]+\.apps\.googleusercontent\.com", value.get("client_id", ""))
                or not isinstance(value.get("client_secret"), str) or not value["client_secret"]
                or REDIRECT_URI not in value.get("redirect_uris", [])
                or value.get("auth_uri", AUTH_URL) != AUTH_URL or value.get("token_uri", TOKEN_URL) != TOKEN_URL):
            raise ValueError()
        return {"client_id": value["client_id"], "client_secret": value["client_secret"]}
    except (OSError, ValueError, KeyError, TypeError):
        raise OAuthError("approved_web_client_and_exact_redirect_required") from None


def oauth_http_request(request):
    return http_request(request, read_error_body=True)


def json_request(request, transport=oauth_http_request):
    try:
        status, _, raw = transport(request)
        value = json.loads(raw)
        if status != 200:
            code = value.get("error") if isinstance(value, dict) else None
            if code in ("invalid_client", "invalid_grant", "redirect_uri_mismatch", "access_denied",
                        "invalid_scope", "unauthorized_client", "admin_policy_enforced", "org_internal"):
                raise OAuthError("google_oauth_" + code)
            raise ValueError()
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except OAuthError:
        raise
    except Exception:
        raise OAuthError("google_oauth_request_failed_no_email_was_sent") from None


def verify_identity(access_token, *, expected_account=None, expected_sub=None, transport=oauth_http_request):
    if not isinstance(access_token, str) or not access_token or re.search(r"\s", access_token):
        raise OAuthError("google_access_token_invalid")
    value = json_request(Request(USERINFO_URL, headers={"Authorization": "Bearer " + access_token}), transport)
    email, sub = value.get("email"), value.get("sub")
    if (value.get("email_verified") is not True or not isinstance(email, str) or not isinstance(sub, str) or not sub
            or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+", email)
            or (expected_account is not None and email.casefold() != expected_account.casefold())
            or (expected_sub is not None and sub != expected_sub)):
        raise OAuthError("google_account_identity_mismatch")
    return email, sub


class OAuthSession:
    def __init__(self, client, expected_account=None, *, sender="", reply_to="", sender_name="", profile="library", timeout_seconds=600):
        if profile not in PROFILE_FILES:
            raise OAuthError("unsupported_google_credential_profile")
        if type(timeout_seconds) is not int or not 60 <= timeout_seconds <= 3600:
            raise OAuthError("google_oauth_session_timeout_invalid")
        self.timeout_seconds = timeout_seconds
        self.profile = profile
        self.test_account = profile == TEST_PROFILE
        self.client, self.expected_account = client, expected_account
        self.sender, self.reply_to, self.sender_name = sender, reply_to, sender_name
        self.state = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(64)
        self.started = time.monotonic()
        self.used = False
        self.confirm_state = secrets.token_urlsafe(32)

    def expired(self):
        return time.monotonic() - self.started >= self.timeout_seconds

    def authorization_url(self):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        parameters = {"client_id": self.client["client_id"], "redirect_uri": REDIRECT_URI,
            "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline",
            "prompt": "consent select_account", "include_granted_scopes": "false", "state": self.state,
            "code_challenge": challenge, "code_challenge_method": "S256"}
        if self.expected_account:
            parameters["login_hint"] = self.expected_account
        return AUTH_URL + "?" + urlencode(parameters)

    def callback_code(self, target, host):
        uri = urlsplit(target)
        expected = urlsplit(REDIRECT_URI)
        params = parse_qs(uri.query, keep_blank_values=True)
        states = params.get("state", [])
        if (self.used or self.expired() or uri.scheme or uri.netloc or uri.fragment
                or host != expected.netloc or uri.path != expected.path or len(states) != 1
                or not hmac.compare_digest(states[0], self.state)):
            raise OAuthError("oauth_callback_state_redirect_or_expiry_invalid")
        self.used = True
        if "error" in params:
            raise OAuthError("google_consent_not_granted")
        codes = params.get("code", [])
        if len(codes) != 1 or not codes[0]:
            raise OAuthError("oauth_callback_code_invalid")
        return codes[0]

    def exchange_and_verify(self, code, *, transport=oauth_http_request):
        if not self.used:
            raise OAuthError("oauth_callback_must_be_validated_before_exchange")
        token = json_request(Request(TOKEN_URL, data=urlencode({**self.client, "code": code,
            "code_verifier": self.verifier, "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"), transport)
        if (not isinstance(token.get("refresh_token"), str) or not token["refresh_token"]
                or token.get("token_type", "").lower() != "bearer"
                or SEND_SCOPE not in token.get("scope", "").split()):
            raise OAuthError("google_offline_gmail_send_grant_missing")
        email, sub = verify_identity(token.get("access_token"), expected_account=self.expected_account, transport=transport)
        return {**self.client, "refresh_token": token["refresh_token"], "account_email": email, "account_sub": sub,
                "sender": self.sender, "reply_to": self.reply_to, "sender_name": self.sender_name,
                "scopes": token["scope"].split(), "verified_at": datetime.now(timezone.utc).isoformat(), "redirect_uri": REDIRECT_URI}


def confirm_discovered_account(session, credentials, form, *, host, origin):
    expected = urlsplit(REDIRECT_URI)
    nonce = form.get("state", [])
    if host != expected.netloc:
        raise OAuthError("google_account_confirmation_host_invalid")
    if origin != "http://" + expected.netloc:
        raise OAuthError("google_account_confirmation_origin_invalid")
    if session.expired():
        raise OAuthError("google_account_confirmation_session_expired")
    if len(nonce) != 1 or not hmac.compare_digest(nonce[0], session.confirm_state):
        raise OAuthError("google_account_confirmation_state_invalid")
    if session.test_account:
        if form.get("confirm_test_account") != ["yes"]:
            raise OAuthError("google_test_account_confirmation_required")
        if "same_n8n_account" in form or "same_n8n_sender" in form:
            raise OAuthError("n8n_identity_confirmation_is_not_valid_for_test_profile")
        return {**credentials, "sender": credentials["account_email"], "reply_to": "", "sender_name": "",
                "n8n_identity_confirmed": False, "profile_name": TEST_PROFILE, "credential_usage": "test_only",
                "production_sender_approved": False}
    if form.get("same_n8n_account") != ["yes"]:
        raise OAuthError("discovered_google_account_confirmation_required")
    confirmed = {**credentials, "n8n_identity_confirmed": True}
    if form.get("same_n8n_sender") == ["yes"]:
        if confirmed.get("sender") and confirmed["sender"].casefold() != confirmed["account_email"].casefold():
            raise OAuthError("sender_confirmation_conflicts_with_existing_sender")
        confirmed["sender"] = confirmed["account_email"]
    return confirmed


def confirmation_page(session, credentials):
    """The test profile never asks an owner to assert an n8n/production identity."""
    account = escape(credentials["account_email"])
    start = (f'<!doctype html><html><meta charset="utf-8"><title>Confirm Google account</title>'
             f'<h1>Google account verified</h1><p>{account}</p>'
             '<form method="post" action="/oauth2/confirm">'
             f'<input type="hidden" name="state" value="{session.confirm_state}">')
    if session.test_account:
        body = ('<p>AI Team test account. No email has been sent. Production sender remains unchanged.</p>'
                '<p><label><input type="checkbox" name="confirm_test_account" value="yes" required>'
                ' I authorize this AI Team account as a TEST SENDER ONLY.</label></p>'
                '<p>Authorization will be encrypted in the separate AI Team test profile.</p>')
    else:
        body = ('<p>No email has been sent. Confirm the original library identity before saving.</p>'
                '<p><label><input type="checkbox" name="same_n8n_account" value="yes" required>'
                ' This is the SAME Google account used by Charly Account in n8n.</label></p>'
                '<p><label><input type="checkbox" name="same_n8n_sender" value="yes">'
                ' This address also matches the From of previous n8n library emails. Use it as Sender.</label></p>'
                '<p>Leave the second box unchecked if an alias was used or you are unsure.</p>')
    return start + body + '<button type="submit">Confirm and save encrypted authorization</button></form></html>'


def authorize(session, vault, *, verify_refresh, open_browser=True):
    """The ONLY listener is loopback. Never logs callback paths, codes or tokens."""
    result = {}
    pending = {}
    phase = {"current": "awaiting_google_consent"}

    def progress(value):
        phase["current"] = value
        print(json.dumps({"oauth_stage": value}), flush=True)

    def finish(credentials):
        progress("refresh_verification")
        verify_refresh(credentials)
        progress("encrypted_credential_storage")
        save_credentials(vault, credentials)
        result["account"] = credentials["account_email"]
        progress("authorization_saved")

    def safe_error(exc):
        result["error"] = (str(exc) if isinstance(exc, OAuthError) else "oauth_credential_storage_failed"
                           if isinstance(exc, CredentialStoreError) else "oauth_authorization_not_completed_nothing_enabled")
        print(json.dumps({"oauth_stage": phase["current"], "error_code": result["error"]}), flush=True)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(5)
            super().setup()

        def log_message(self, *args):
            pass

        def respond(self, status, content, kind="text/plain; charset=utf-8", *, referrer_policy="no-referrer"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", referrer_policy)
            self.send_header("Content-Security-Policy", "default-src 'none'; form-action 'self'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.path == "/favicon.ico":
                self.send_error(404)
                return
            if self.path == "/oauth2/start" and self.headers.get("Host") == urlsplit(REDIRECT_URI).netloc:
                self.send_response(302)
                self.send_header("Location", session.authorization_url())
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            try:
                code = session.callback_code(self.path, self.headers.get("Host", ""))
                progress("code_exchange_and_identity_verification")
                credentials = session.exchange_and_verify(code)
                if session.expected_account is None or session.test_account:
                    pending["credentials"] = credentials
                    print(json.dumps({"google_identity_verified": True, "account_email": credentials["account_email"],
                                      "profile": session.profile,
                                      "awaiting_local_account_confirmation": True}), flush=True)
                    page = confirmation_page(session, credentials)
                    progress("awaiting_local_account_confirmation")
                    self.respond(200, page.encode("utf-8"), "text/html; charset=utf-8",
                                 referrer_policy=CONFIRMATION_REFERRER_POLICY)
                    return
                finish({**credentials, "n8n_identity_confirmed": True})
                content = b"Google authorization verified and encrypted locally. Email sending remains disabled. You may close this tab."
                status = 200
            except Exception as exc:
                safe_error(exc)
                content = b"Authorization was not completed. No email was sent. Return to the local terminal."
                status = 400
            self.respond(status, content)

        def do_POST(self):
            try:
                progress("confirmation_request_validation")
                if self.path != "/oauth2/confirm" or "credentials" not in pending:
                    raise OAuthError("google_account_confirmation_not_pending")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2048 or self.headers.get("Content-Type") != "application/x-www-form-urlencoded":
                    raise OAuthError("invalid_google_account_confirmation_request")
                form = parse_qs(self.rfile.read(length).decode("ascii"), keep_blank_values=True)
                progress("account_confirmation_validation")
                expected = urlsplit(REDIRECT_URI)
                nonce = form.get("state", [])
                print(json.dumps({"confirmation_checks": {
                    "host_matches": self.headers.get("Host") == expected.netloc,
                    "origin_matches": self.headers.get("Origin") == "http://" + expected.netloc,
                    "origin_is_null": self.headers.get("Origin") == "null",
                    "state_matches": len(nonce) == 1 and hmac.compare_digest(nonce[0], session.confirm_state),
                    "session_expired": session.expired(),
                    "account_checkbox_confirmed": form.get("same_n8n_account") == ["yes"],
                    "sender_checkbox_confirmed": form.get("same_n8n_sender") == ["yes"],
                    "test_account_checkbox_confirmed": form.get("confirm_test_account") == ["yes"],
                }}), flush=True)
                credentials = confirm_discovered_account(session, pending["credentials"], form,
                    host=self.headers.get("Host", ""), origin=self.headers.get("Origin", ""))
                finish(credentials)
                pending.clear()
                self.respond(200, b"Authorization verified, refreshed and encrypted. Email sending remains disabled.")
            except Exception as exc:
                pending.clear()
                safe_error(exc)
                self.respond(400, b"Confirmation failed. No email was sent and no sending was enabled.")

    class LoopbackServer(HTTPServer):
        def handle_error(self, request, client_address):
            result["error"] = "oauth_local_callback_failed"

    with LoopbackServer(("127.0.0.1", 8765), Handler) as server:
        server.timeout = 1
        manual_url = "http://127.0.0.1:8765/oauth2/start"
        browser_opened = False
        if open_browser:
            try:
                browser_opened = webbrowser.open(manual_url, new=1)
            except Exception:
                pass
        print(json.dumps({"browser_open_requested": bool(browser_opened), "local_sign_in_url": manual_url,
                          "redirect_uri": REDIRECT_URI, "session_timeout_minutes": session.timeout_seconds // 60,
                          "profile": session.profile, "sending_enabled": False}), flush=True)
        while not result and not session.expired():
            server.handle_request()
    if "account" not in result:
        raise OAuthError(result.get("error", "google_sign_in_or_consent_required"))
    return result["account"]
