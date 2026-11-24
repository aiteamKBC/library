"""Short-lived LMS assertions, bound to the initiating browser and used once.

Activation (operator configuration, not applied by this code change):
* Set the same dedicated random LIBRARY_SSO_SECRET (at least 32 characters) in
  both backends. Never use either application's main SECRET_KEY or VITE_*.
* Library: set LIBRARY_LMS_LOGIN_URL to the LMS's HTTPS /login page.
* LMS: LIBRARY_SSO_CALLBACK_URL defaults to the Library's /auth/lms/callback.
* Apply Library migration 0026 through the normal reviewed release process.
* Serve /api and the callback under the same Library origin; HTTPS and secure
  cookies are required in production. Local HTTP only: explicitly set
  LIBRARY_SSO_COOKIE_SECURE=false and use loopback URLs.

This establishes a normal Library session. It does not implement shared logout
or replace the existing standalone Library sign-in policy.
"""
from datetime import timedelta
from hashlib import sha256
import secrets
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.http import require_GET
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import LibrarySSORedemption
from .student_auth import fetch_allowlisted_student, sync_student_account_from_allowlist

SALT = "kbc-library-sso-v1"
COOKIE_SALT = "kbc-library-sso-browser-v1"
ASSERTION_AGE = 120
BROWSER_AGE = 600


def cookie_name():
    return "__Host-kbc_library_sso" if settings.LIBRARY_SSO_COOKIE_SECURE else "kbc_library_sso_local"


def private(response):
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def configured():
    url = urlsplit(settings.LIBRARY_LMS_LOGIN_URL)
    safe_url = (url.scheme == "https" or (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}))
    return len(settings.LIBRARY_SSO_SECRET) >= 32 and safe_url and url.netloc and not (url.query or url.fragment or url.username or url.password)


@require_GET
def start(request):
    if not configured():
        return private(JsonResponse({"detail": "LMS sign-in is not configured."}, status=503))
    verifier = secrets.token_hex(32)
    state = sha256(verifier.encode()).hexdigest()
    response = private(HttpResponseRedirect(settings.LIBRARY_LMS_LOGIN_URL + "?" + urlencode({"library_state": state})))
    # Host-only, HttpOnly cookie survives the top-level LMS round-trip. The LMS
    # sees only its hash, so a copied assertion cannot log in another browser.
    response.set_cookie(cookie_name(), signing.dumps(verifier, salt=COOKIE_SALT),
                        max_age=BROWSER_AGE, secure=settings.LIBRARY_SSO_COOKIE_SECURE,
                        httponly=True, samesite="Lax", path="/")
    return response


class ExchangeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not configured():
            return private(Response({"detail": "LMS sign-in is not configured."}, status=503))
        try:
            if not isinstance(request.data, dict):
                raise ValueError
            assertion = request.data.get("assertion", "")
            if not isinstance(assertion, str) or not 1 <= len(assertion) <= 8192:
                raise ValueError
            claims = signing.loads(assertion, key=settings.LIBRARY_SSO_SECRET,
                                   salt=SALT, max_age=ASSERTION_AGE, fallback_keys=[])
            verifier = signing.loads(request.COOKIES.get(cookie_name(), ""),
                                     salt=COOKIE_SALT, max_age=BROWSER_AGE, fallback_keys=[])
            if not isinstance(verifier, str) or not isinstance(claims, dict):
                raise ValueError
            state = sha256(verifier.encode()).hexdigest()
            if (claims.get("aud") != "kbc-library" or claims.get("role") != "learner"
                    or claims.get("subject_type") != "learner"
                    or type(claims.get("account_id")) is not int or claims["account_id"] <= 0
                    or not isinstance(claims.get("state"), str)
                    or not constant_time_compare(claims["state"], state)):
                raise ValueError
            email = claims.get("email")
            if not isinstance(email, str):
                raise ValueError
            validate_email(email)
        except (signing.BadSignature, ValueError, TypeError, ValidationError):
            return private(Response({"detail": "This LMS sign-in has expired or is invalid. Please open Library from the LMS again."}, status=400))

        try:
            student = fetch_allowlisted_student(email)
        except RuntimeError:
            return private(Response({"detail": "The learner directory is temporarily unavailable. Please try again."}, status=503))
        if student is None:
            return private(Response({"detail": "This learner is not registered for Library access."}, status=403))

        try:
            with transaction.atomic():
                # The primary key arbitrates races between all server workers.
                LibrarySSORedemption.objects.create(state_hash=state, expires_at=timezone.now() + timedelta(seconds=BROWSER_AGE))
                user = sync_student_account_from_allowlist(student)
                if not user.is_active:
                    raise ValueError("This Library account is inactive.")
                from .views import build_auth_session_payload
                payload = build_auth_session_payload(user)
                # Bound cleanup work; keep spent states longer than any valid cookie.
                expired = list(LibrarySSORedemption.objects.filter(expires_at__lt=timezone.now()).values_list("pk", flat=True)[:100])
                LibrarySSORedemption.objects.filter(pk__in=expired).delete()
        except IntegrityError:
            return private(Response({"detail": "This sign-in could not be completed. Please open Library from the LMS again."}, status=409))
        except ValueError:
            return private(Response({"detail": "This account cannot use learner sign-in."}, status=403))

        response = private(Response(payload))
        response.delete_cookie(cookie_name(), path="/", samesite="Lax")
        return response
