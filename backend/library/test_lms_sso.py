from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core import signing
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .lms_sso import COOKIE_SALT, SALT, cookie_name
from .models import LibrarySSORedemption
from .student_auth import AllowlistedStudent

SECRET = "synthetic-shared-library-secret-at-least-32-chars"


@override_settings(LIBRARY_SSO_SECRET=SECRET, LIBRARY_LMS_LOGIN_URL="https://lms.example.test/login", LIBRARY_SSO_COOKIE_SECURE=True)
class LibrarySSOTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        lookup = patch("library.lms_sso.fetch_allowlisted_student", return_value=AllowlistedStudent("learner@example.test", "Synthetic Learner"))
        self.lookup = lookup.start()
        self.addCleanup(lookup.stop)

    def start(self, client=None):
        response = (client or self.client).get("/api/auth/lms/start/")
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlsplit(response["Location"]).query)["library_state"][0]

    def assertion(self, browser_state, **overrides):
        claims = {"aud": "kbc-library", "state": browser_state, "account_id": 41,
                  "email": "learner@example.test", "role": "learner", "subject_type": "learner"}
        claims.update(overrides)
        return signing.dumps(claims, key=SECRET, salt=SALT)

    def exchange(self, assertion, client=None):
        return (client or self.client).post("/api/auth/lms/exchange/", {"assertion": assertion}, format="json")

    def test_start_sets_private_host_only_browser_cookie_and_fixed_destination(self):
        response = self.client.get("/api/auth/lms/start/?next=https://attacker.invalid&email=other@example.test")
        url = urlsplit(response["Location"])
        self.assertEqual((url.netloc, url.path), ("lms.example.test", "/login"))
        self.assertEqual(set(parse_qs(url.query)), {"library_state"})
        cookie = response.cookies[cookie_name()]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["domain"], "")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertFalse(LibrarySSORedemption.objects.exists())

    def test_valid_login_uses_signed_email_preserves_existing_account_and_returns_session(self):
        user = get_user_model().objects.create_user(username="learner@example.test", email="learner@example.test")
        state = self.start()
        response = self.client.post("/api/auth/lms/exchange/", {"assertion": self.assertion(state), "email": "attacker@example.test"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.lookup.assert_called_once_with("learner@example.test")
        self.assertEqual(get_user_model().objects.get(email="learner@example.test").pk, user.pk)
        self.assertEqual(response.data["user"]["email"], "learner@example.test")
        self.client.credentials(HTTP_AUTHORIZATION="Token " + response.data["token"])
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        self.assertEqual(response.cookies[cookie_name()]["max-age"], 0)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_replay_fails_even_if_browser_cookie_is_restored(self):
        assertion = self.assertion(self.start())
        cookie = self.client.cookies[cookie_name()].value
        self.assertEqual(self.exchange(assertion).status_code, 200)
        self.client.cookies[cookie_name()] = cookie
        self.assertEqual(self.exchange(assertion).status_code, 409)
        self.assertEqual(LibrarySSORedemption.objects.count(), 1)

    def test_other_browser_or_missing_cookie_cannot_redeem(self):
        assertion = self.assertion(self.start())
        other = APIClient()
        self.assertEqual(self.exchange(assertion, other).status_code, 400)
        self.start(other)
        self.assertEqual(self.exchange(assertion, other).status_code, 400)
        self.lookup.assert_not_called()

    def test_forged_signature_and_wrong_key_are_rejected(self):
        assertion = self.assertion(self.start())
        self.assertEqual(self.exchange(assertion + "x").status_code, 400)
        with override_settings(LIBRARY_SSO_SECRET="different-synthetic-key-at-least-32-characters"):
            self.assertEqual(self.exchange(assertion).status_code, 400)
        self.lookup.assert_not_called()

    def test_expired_assertion_and_browser_cookie_are_rejected(self):
        state = self.start()
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() - 121):
            expired = self.assertion(state)
        self.assertEqual(self.exchange(expired).status_code, 400)
        verifier = signing.loads(self.client.cookies[cookie_name()].value, salt=COOKIE_SALT)
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() - 601):
            self.client.cookies[cookie_name()] = signing.dumps(verifier, salt=COOKIE_SALT)
        self.assertEqual(self.exchange(self.assertion(state)).status_code, 400)
        self.lookup.assert_not_called()

    def test_wrong_audience_role_subject_identity_and_email_are_rejected(self):
        state = self.start()
        for claims in [{"aud": "other"}, {"role": "admin"}, {"subject_type": "staff"}, {"account_id": 0}, {"account_id": True}, {"email": "invalid"}, {"state": "a" * 64}]:
            with self.subTest(claims=claims):
                self.assertEqual(self.exchange(self.assertion(state, **claims)).status_code, 400)
        self.lookup.assert_not_called()

    def test_malformed_payloads_fail_without_account_creation(self):
        self.start()
        for value in [None, [], {}, "x" * 9000, ""]:
            self.assertEqual(self.exchange(value).status_code, 400)
        self.assertFalse(get_user_model().objects.exists())

    def test_unregistered_learner_is_denied(self):
        self.lookup.return_value = None
        self.assertEqual(self.exchange(self.assertion(self.start())).status_code, 403)
        self.assertFalse(get_user_model().objects.exists())

    def test_directory_failure_is_sanitized_and_can_retry(self):
        assertion = self.assertion(self.start())
        self.lookup.side_effect = RuntimeError("synthetic-secret")
        response = self.exchange(assertion)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("synthetic-secret", str(response.data))
        self.assertFalse(LibrarySSORedemption.objects.exists())
        self.lookup.side_effect = None
        self.assertEqual(self.exchange(assertion).status_code, 200)

    def test_existing_staff_and_inactive_accounts_cannot_be_promoted(self):
        user = get_user_model().objects.create_user(username="learner@example.test", email="learner@example.test", is_staff=True)
        assertion = self.assertion(self.start())
        self.assertEqual(self.exchange(assertion).status_code, 403)
        user.is_staff = False
        user.is_active = False
        user.save()
        self.assertEqual(self.exchange(assertion).status_code, 403)
        self.assertFalse(LibrarySSORedemption.objects.exists())

    def test_only_expired_redemptions_are_cleaned(self):
        LibrarySSORedemption.objects.create(state_hash="expired", expires_at=timezone.now() - timedelta(seconds=1))
        LibrarySSORedemption.objects.create(state_hash="live", expires_at=timezone.now() + timedelta(minutes=10))
        self.assertEqual(self.exchange(self.assertion(self.start())).status_code, 200)
        self.assertFalse(LibrarySSORedemption.objects.filter(pk="expired").exists())
        self.assertTrue(LibrarySSORedemption.objects.filter(pk="live").exists())

    @override_settings(LIBRARY_SSO_SECRET="")
    def test_missing_configuration_fails_closed(self):
        self.assertEqual(self.client.get("/api/auth/lms/start/").status_code, 503)
        self.assertEqual(self.exchange("invalid").status_code, 503)

    @override_settings(LIBRARY_LMS_LOGIN_URL="https://lms.example.test/login?next=https://attacker.invalid")
    def test_ambiguous_destination_configuration_is_rejected(self):
        self.assertEqual(self.client.get("/api/auth/lms/start/").status_code, 503)

    def test_exchange_requires_post_and_start_requires_get(self):
        self.assertEqual(self.client.get("/api/auth/lms/exchange/").status_code, 405)
        self.assertEqual(self.client.post("/api/auth/lms/start/").status_code, 403)  # CSRF middleware


@skipUnless(connection.vendor == "postgresql", "Requires the isolated PostgreSQL harness.")
@override_settings(LIBRARY_SSO_SECRET=SECRET, LIBRARY_LMS_LOGIN_URL="https://lms.example.test/login", LIBRARY_SSO_COOKIE_SECURE=True)
class LibrarySSOConcurrencyTests(TransactionTestCase):
    def test_simultaneous_redemption_issues_only_one_session(self):
        client = APIClient()
        response = client.get("/api/auth/lms/start/")
        state = parse_qs(urlsplit(response["Location"]).query)["library_state"][0]
        name = cookie_name()
        cookie = client.cookies[name].value
        assertion = signing.dumps({"aud": "kbc-library", "state": state, "account_id": 41,
                                  "email": "learner@example.test", "role": "learner", "subject_type": "learner"}, key=SECRET, salt=SALT)
        barrier = Barrier(2)

        def lookup(email):
            barrier.wait(timeout=10)
            return AllowlistedStudent(email, "Synthetic Learner")

        def exchange():
            try:
                browser = APIClient()
                browser.cookies[name] = cookie
                return browser.post("/api/auth/lms/exchange/", {"assertion": assertion}, format="json").status_code
            finally:
                connections.close_all()

        with patch("library.lms_sso.fetch_allowlisted_student", side_effect=lookup), ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: exchange(), range(2)))
        self.assertEqual(sorted(responses), [200, 409])
        self.assertEqual(LibrarySSORedemption.objects.count(), 1)
        self.assertEqual(get_user_model().objects.filter(email="learner@example.test").count(), 1)
