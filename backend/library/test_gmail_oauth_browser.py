"""Real Chromium form POST + DPAPI regression using synthetic data, loopback only.

External browser traffic is forced through a closed loopback proxy. A fresh
temporary browser profile never reads the user's cookies/accounts. No Google
OAuth/send APIs, real credential files or application database are used.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from threading import Thread
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs

from django.test import SimpleTestCase

from .gmail_credential_store import load_credentials, save_credentials
from .gmail_oauth import CONFIRMATION_REFERRER_POLICY, OAuthError, OAuthSession, confirm_discovered_account
from .test_gmail_oauth import CLIENT, GRANT

CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


@skipUnless(CHROME.is_file(), "Requires local Windows Chrome and DPAPI; no package installation.")
class GoogleConfirmationBrowserTests(SimpleTestCase):
    def test_native_post_origin_sender_optional_and_identity_checkbox_required(self):
        cases = (("no-referrer", True, "google_account_confirmation_origin_invalid"),
                 (CONFIRMATION_REFERRER_POLICY, True, None),
                 (CONFIRMATION_REFERRER_POLICY, False, "discovered_google_account_confirmation_required"))
        for referrer_policy, checkbox, expected_error in cases:
            with self.subTest(policy=referrer_policy, checkbox=checkbox), \
                    tempfile.TemporaryDirectory(prefix="kbc-synthetic-confirm-browser-") as directory:
                root = Path(directory).resolve()
                self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
                vault = root / "synthetic.dpapi"
                session, observed = OAuthSession(CLIENT), {}

                class Handler(BaseHTTPRequestHandler):
                    def setup(self):
                        self.request.settimeout(3)
                        super().setup()

                    def log_message(self, *args):
                        pass

                    def respond(self, status, content, *, page=False):
                        self.send_response(status)
                        self.send_header("Content-Length", str(len(content)))
                        if page:
                            self.send_header("Content-Type", "text/html; charset=utf-8")
                            self.send_header("Referrer-Policy", referrer_policy)
                        self.end_headers()
                        self.wfile.write(content)

                    def do_GET(self):
                        if self.path == "/favicon.ico":
                            self.respond(404, b"")
                            return
                        checked = " checked" if checkbox else ""
                        content = (f'<form method="post" action="/confirm">'
                                   f'<input type="hidden" name="state" value="{session.confirm_state}">'
                                   f'<input type="checkbox" name="same_n8n_account" value="yes"{checked}>'
                                   '<input type="checkbox" name="same_n8n_sender" value="yes">'
                                   '</form><script>document.forms[0].submit()</script>').encode()
                        self.respond(200, content, page=True)

                    def do_POST(self):
                        form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                        observed["origin"] = self.headers.get("Origin")
                        observed["referrer_query_leaked"] = "?" in self.headers.get("Referer", "")
                        try:
                            credentials = confirm_discovered_account(session, GRANT, form,
                                host=self.headers.get("Host"), origin=self.headers.get("Origin"))
                            save_credentials(vault, credentials)
                            observed["saved"] = True
                            self.respond(200, b"Synthetic authorization encrypted; no email sent.")
                        except OAuthError as exc:
                            observed["error"] = str(exc)
                            self.respond(400, b"Synthetic confirmation rejected.")

                class Server(ThreadingHTTPServer):
                    daemon_threads = True

                    def handle_error(self, *args):
                        observed["server_error"] = True

                server = Server(("127.0.0.1", 0), Handler)
                origin = f"http://127.0.0.1:{server.server_port}"
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with patch("library.gmail_oauth.REDIRECT_URI", origin + "/callback"):
                        command = [str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                            "--no-default-browser-check", "--disable-background-networking", "--disable-component-update",
                            "--disable-sync", "--disable-extensions", "--disable-default-apps",
                            "--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=127.0.0.1",
                            "--user-data-dir=" + str(root / "browser-profile"), "--timeout=10000", "--dump-dom",
                            origin + "/callback?code=SYNTHETIC-NOT-REAL"]
                        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                                timeout=20, creationflags=0x08000000)
                    self.assertEqual(result.returncode, 0)
                    self.assertNotIn("server_error", observed)
                    self.assertFalse(observed["referrer_query_leaked"])
                    if expected_error:
                        self.assertEqual(observed["error"], expected_error)
                        self.assertFalse(vault.exists())
                    else:
                        self.assertEqual(observed["origin"], origin)
                        self.assertTrue(observed["saved"])
                        credentials = load_credentials(vault)
                        self.assertTrue(credentials["n8n_identity_confirmed"])
                        self.assertEqual(credentials["sender"], "")
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
