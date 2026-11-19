"""Local OAuth bootstrap. Reads Google-only fields without Django/DB startup or mail.

Run --check first. The library profile preserves the original n8n identity rules.
The explicit ai-team-test profile authorizes a separate test account only.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from library.gmail_credential_store import (CredentialStoreError, default_vault_path,
    load_credentials, checked_path, PROFILE_FILES, TEST_PROFILE)
from library.gmail_oauth import (OAuthError, OAuthSession, REDIRECT_URI, authorize, load_client,
    verify_identity)
from library.gmail_oauth_config import GoogleConfigError, resolve_google_config


def verify_refresh(credentials):
    # This is a dedicated process: do not initialize the real application's DB,
    # settings module, .env or mail routing just to verify an OAuth grant.
    from django.conf import settings
    if settings.configured:
        raise OAuthError("run_oauth_bootstrap_in_a_dedicated_process")
    settings.configure(LIBRARY_ISOLATED_TESTS=False,
        LIBRARY_GMAIL_CLIENT_ID=credentials["client_id"],
        LIBRARY_GMAIL_CLIENT_SECRET=credentials["client_secret"],
        LIBRARY_GMAIL_REFRESH_TOKEN=credentials["refresh_token"],
        LIBRARY_GMAIL_SEND_ENABLED=False, LIBRARY_EMAIL_WORKER_ENABLED=False,
        LIBRARY_EMAIL_ENQUEUE_ENABLED=False, LIBRARY_EMAIL_SCHEDULER_ENABLED=False,
        LIBRARY_GRAPH_SEND_ENABLED=False)
    from library.gmail_client import GmailClient
    client = GmailClient()
    token, error = client._access_token()
    if error:
        raise OAuthError("gmail_client_refresh_verification_failed_" + error.code)
    try:
        verify_identity(token, expected_account=credentials["account_email"], expected_sub=credentials["account_sub"])
    finally:
        client._invalidate_token(token)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Local readiness only; no network or browser.")
    mode.add_argument("--authorize", action="store_true", help="Open Google Sign-In and verify a new independent grant. Never sends mail.")
    mode.add_argument("--verify", action="store_true", help="Refresh saved authorization and verify identity. Never sends mail.")
    parser.add_argument("--profile", choices=tuple(PROFILE_FILES), default="library",
                        help="ai-team-test uses a separate test-only vault, never the application's sender.")
    parser.add_argument("--timeout-minutes", type=int, default=10, help="Local session lifetime, 1-60 minutes (default 10).")
    parser.add_argument("--client-file", help="Approved Google WEB client JSON outside Git; never pass secrets as arguments.")
    parser.add_argument("--env-file", default=str(Path(__file__).with_name(".env")), help="Read only Google OAuth fields from this existing file.")
    parser.add_argument("--expected-account", help="Optional exact Google identity. Test profiles do not inherit the library account.")
    parser.add_argument("--discover-account", action="store_true", help="Verify Google's selected identity, then require local confirmation before saving.")
    parser.add_argument("--no-browser", action="store_true", help="Print a local sign-in link for manual opening; never prints Google codes/tokens.")
    parser.add_argument("--sender", default=None, help="Only the verified original n8n From, if known. Empty stays unconfigured.")
    parser.add_argument("--reply-to", default=None, help="Only an approved explicit Reply-To. Empty retains existing fallback policy.")
    options = parser.parse_args(argv)
    try:
        if not 1 <= options.timeout_minutes <= 60:
            raise OAuthError("google_oauth_timeout_minutes_must_be_between_1_and_60")
        vault = default_vault_path(options.profile)
        is_test = options.profile == TEST_PROFILE
        config, sources = resolve_google_config(env_path=options.env_file)
        if config["redirect_uri"] and config["redirect_uri"] != REDIRECT_URI:
            raise OAuthError("configured_google_redirect_uri_must_match_exact_callback")
        client_path = options.client_file or os.getenv("LIBRARY_GMAIL_OAUTH_CLIENT_FILE")
        client = load_client(checked_path(client_path)) if client_path else None
        env_client = {key: config[key] for key in ("client_id", "client_secret")} if config["client_id"] else None
        if client and env_client and client != env_client:
            raise OAuthError("google_oauth_client_file_and_env_conflict")
        client = client or env_client
        expected_account = options.expected_account or (None if is_test else config["account_email"] or None)
        if is_test and (options.sender is not None or options.reply_to is not None):
            raise OAuthError("test_profile_uses_only_the_confirmed_test_account_identity")
        if is_test:
            sender, reply_to = "", ""
        else:
            sender = config["sender"] if options.sender is None else options.sender
            reply_to = config["reply_to"] if options.reply_to is None else options.reply_to
        if options.authorize:
            if client is None:
                raise OAuthError("approved_google_oauth_client_file_required")
            if not expected_account and not options.discover_account and not is_test:
                raise OAuthError("use_expected_account_or_explicit_discover_account")
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError
            for email in (expected_account, sender, reply_to):
                if email:
                    try:
                        validate_email(email)
                    except ValidationError:
                        raise OAuthError("invalid_account_sender_or_reply_to") from None
            if vault.exists():
                raise OAuthError("existing_google_grant_will_not_be_overwritten")
            session = OAuthSession(client, expected_account, sender=sender, reply_to=reply_to, profile=options.profile,
                                   timeout_seconds=options.timeout_minutes * 60)
            print("Opening Google Sign-In. Complete consent in the browser; sending stays disabled.", flush=True)
            account = authorize(session, vault, verify_refresh=verify_refresh, open_browser=not options.no_browser)
            saved = load_credentials(vault)
            print(json.dumps({"authorization": "verified_and_encrypted", "account_email": account,
                              "profile": options.profile, "credential_usage": saved.get("credential_usage", "library"),
                              "sending_enabled": False, "sender_configured": bool(saved.get("sender"))}))
        elif options.verify:
            saved = load_credentials(vault)
            if is_test != (saved.get("credential_usage") == "test_only"):
                raise OAuthError("saved_google_authorization_profile_mismatch")
            verify_refresh(saved)
            print(json.dumps({"refresh_and_identity": "verified", "account_email": saved["account_email"],
                              "profile": options.profile, "sending_enabled": False}))
        else:
            print(json.dumps({"client_available_locally": client is not None, "encrypted_grant_present": vault.exists(),
                              "profile": options.profile, "test_sender_only": is_test,
                              "client_id_sources": sources["client_id"], "client_secret_sources": sources["client_secret"],
                              "required_redirect_uri": REDIRECT_URI, "sending_enabled": False,
                              "redirect_registration_verified": False,
                              "next_action": "google_sign_in_and_consent" if client else "google_cloud_authorized_web_client_required"}))
        return 0
    except (OAuthError, CredentialStoreError, GoogleConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        # Exception/HTTP representations can contain codes, URLs or secrets.
        print("oauth_setup_failed_no_email_was_sent", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
