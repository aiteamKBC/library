"""Dedicated one-message harness. Default is OFFLINE; --send-once uses the authorized grant.

No .env/application settings import. Fresh owned PostgreSQL cluster only. Existing
EmailOutbox, EmailWorker and GmailClient perform the send. No scheduler or retry.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import uuid
from unittest.mock import patch

from library.gmail_test_safety import SCENARIOS, TOKEN_URL, USERINFO_URL, SingleSendGuard, SingleTestError, first_test_marker, validate_grant

DBNAME = "kbc_first_gmail_test"
DBUSER = "kbc_test_admin"


def forbidden(*args, **kwargs):
    raise SingleTestError("external_database_or_secondary_mail_transport_forbidden")


def run_child(options):
    scenario = SCENARIOS[options.scenario]
    root = Path(options.root).resolve(strict=True)
    if (not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.name.startswith("kbc-first-gmail-test-")
            or json.loads((root / "run.json").read_text())["nonce"] != options.nonce
            or not (root / "data" / "PG_VERSION").is_file() or not 1024 <= options.port <= 65535):
        raise SingleTestError("fresh_local_cluster_required")
    env_names = ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LOCALAPPDATA", "PYTHONTZPATH")
    retained = {name:os.environ[name] for name in env_names if name in os.environ}
    os.environ.clear()
    os.environ.update(retained)  # In particular: no DATABASE_URL, SMTP, webhook or app flags.
    if options.send_once:
        marker = first_test_marker(scenario)
        if marker.exists():
            raise SingleTestError("first_real_test_already_attempted_no_resend")
        from library.gmail_credential_store import default_vault_path, load_credentials
        grant = load_credentials(default_vault_path(scenario.profile))
        validate_grant(grant, scenario)
    else:
        marker = root / "synthetic-send.attempted"
        grant = {"client_id":"synthetic", "client_secret":"synthetic", "refresh_token":"synthetic",
                 "account_email":scenario.sender, "account_sub":"synthetic-account", "sender":scenario.sender}

    from django.conf import settings
    settings.configure(SECRET_KEY="synthetic-one-message-only", USE_TZ=True, TIME_ZONE="UTC",
        INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth", "library"],
        DATABASES={"default":{"ENGINE":"django.db.backends.postgresql", "HOST":"127.0.0.1", "PORT":str(options.port),
                              "NAME":DBNAME, "USER":DBUSER, "PASSWORD":"", "CONN_MAX_AGE":0}},
        CACHES={"default":{"BACKEND":"django.core.cache.backends.locmem.LocMemCache"}},
        TEMPLATES=[{"BACKEND":"django.template.backends.django.DjangoTemplates", "APP_DIRS":True}],
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
        N8N_LIBRARY_WEBHOOK_URL="", KBC_ALLOWLIST_DATABASE_URL="", LIBRARY_ISOLATED_TESTS=False,
        LIBRARY_EMAIL_PROVIDER="gmail", LIBRARY_EMAIL_ENQUEUE_ENABLED=False, LIBRARY_EMAIL_WORKER_ENABLED=False,
        LIBRARY_EMAIL_SCHEDULER_ENABLED=False, LIBRARY_GMAIL_SEND_ENABLED=False, LIBRARY_GMAIL_CREDENTIALS_APPROVED=False,
        LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED=False, LIBRARY_EMAIL_OWNED_EVENTS=(),
        LIBRARY_EMAIL_RECIPIENT_ALLOWLIST=(scenario.recipient,), LIBRARY_EMAIL_MAX_ATTEMPTS=1, LIBRARY_EMAIL_LEASE_SECONDS=180,
        LIBRARY_GRAPH_SEND_ENABLED=False, LIBRARY_GRAPH_CREDENTIALS_APPROVED=False,
        LIBRARY_GMAIL_CLIENT_ID=grant["client_id"], LIBRARY_GMAIL_CLIENT_SECRET=grant["client_secret"],
        LIBRARY_GMAIL_REFRESH_TOKEN=grant["refresh_token"], LIBRARY_GMAIL_ACCOUNT_EMAIL=scenario.sender,
        LIBRARY_GMAIL_SENDER=scenario.sender, LIBRARY_GMAIL_REPLY_TO=scenario.sender, LIBRARY_GMAIL_SENDER_NAME="",
        LIBRARY_EMAIL_N8N_COMPAT_ENABLED=False)
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    original_connect = psycopg.Connection.connect
    def owned_cluster_connect(conninfo="", **kwargs):
        values = conninfo_to_dict(conninfo, **{k:v for k,v in kwargs.items()
            if k not in ("autocommit","prepare_threshold","context","row_factory","cursor_factory")})
        if (values.get("host") != "127.0.0.1" or str(values.get("port")) != str(options.port)
                or values.get("hostaddr", "127.0.0.1") != "127.0.0.1" or values.get("service")
                or values.get("user") != DBUSER or values.get("dbname") != DBNAME or values.get("password", "")):
            forbidden()
        return original_connect(conninfo, **kwargs)

    result = {"mode":"live_authorized_single_message" if options.send_once else "offline_dry_run", "scenario":scenario.name,
              "sender":scenario.sender, "recipient":scenario.recipient, "subject":scenario.subject,
              "neon_used":False, "send_calls":0, "settings_disabled_after_test":False}
    connections = None
    worker = None
    try:
        with ExitStack() as stack:
            stack.enter_context(patch("psycopg.connect", owned_cluster_connect))
            stack.enter_context(patch("psycopg.Connection.connect", owned_cluster_connect))
            for target in ("django.core.mail.send_mail", "django.core.mail.send_mass_mail",
                           "django.core.mail.message.EmailMessage.send", "smtplib.SMTP", "smtplib.SMTP_SSL"):
                stack.enter_context(patch(target, forbidden))
            import django
            django.setup()
            from django.apps import apps
            from django.db import connection, connections as all_connections, transaction
            connections = all_connections
            with connection.cursor() as cursor:
                cursor.execute("SHOW data_directory")
                if Path(cursor.fetchone()[0]).resolve() != root / "data":
                    forbidden()
                cursor.execute("SELECT current_database()")
                if cursor.fetchone()[0] != DBNAME:
                    forbidden()
            if connection.introspection.table_names():
                raise SingleTestError("existing_database_tables_not_allowed")
            with connection.schema_editor() as editor:
                for model in apps.get_models():
                    if model._meta.managed and not model._meta.proxy:
                        editor.create_model(model)
            from django.contrib.auth import get_user_model
            from library.models import UserProfile
            from library.email_models import EmailOutbox, EmailAttempt
            from library.email_events import enqueue
            from library.email_worker import EmailWorker
            from library.email_templates import render_email
            import library.gmail_client as gmail_module
            from library.gmail_oauth import verify_identity
            now = datetime.now(timezone.utc)
            user = get_user_model().objects.create_user("ai-team-synthetic-test", email=scenario.recipient)
            # Synthetic fixture only. No date/timestamp is rendered in this email;
            # this is NOT a timezone choice for a real user or borrowing policy.
            UserProfile.objects.create(user=user, time_zone="Etc/UTC", time_zone_source="manual", time_zone_updated_at=now)

            message_id = uuid.uuid4()
            real_transport = gmail_module.gmail_http_request
            def offline_transport(request):
                if request.full_url == TOKEN_URL:
                    return 200, {}, b'{"access_token":"synthetic-token","expires_in":3600,"token_type":"Bearer"}'
                if request.full_url == USERINFO_URL:
                    return 200, {}, json.dumps({"email":scenario.sender,"email_verified":True,"sub":"synthetic-account"}).encode()
                if request.full_url == scenario.send_url:
                    return 200, {}, b'{"id":"synthetic-message-id","labelIds":["SENT"]}'
                forbidden()
            guard = SingleSendGuard(real_transport if options.send_once else offline_transport, marker, message_id, scenario=scenario)
            # A constrained wrapper around REAL HTTP; GmailClient itself is not
            # injected/faked and all normal live gates and allowlist still run.
            stack.enter_context(patch("library.gmail_client.gmail_http_request", guard))
            settings.LIBRARY_EMAIL_ENQUEUE_ENABLED = settings.LIBRARY_EMAIL_WORKER_ENABLED = True
            settings.LIBRARY_GMAIL_SEND_ENABLED = settings.LIBRARY_GMAIL_CREDENTIALS_APPROVED = True
            settings.LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED = True  # Isolated manual event only, no real n8n handoff.
            settings.LIBRARY_EMAIL_OWNED_EVENTS = ("manual_email",)
            worker = EmailWorker(worker_id="single-authorized-" + scenario.name + "-test")
            token, auth_error = worker.client._access_token()
            if auth_error:
                raise SingleTestError("preflight_" + auth_error.code)
            verify_identity(token, expected_account=scenario.sender, expected_sub=grant["account_sub"], transport=guard)
            with transaction.atomic():
                row = enqueue(event="manual_email", event_id=message_id, user=user, email=scenario.recipient, role="student",
                    logical_key="first-authorized-" + scenario.name + "-gmail-integration-test", payload={
                        "student_name":"AI Team", "book_title":"Gmail Integration Test", "manual_subject":scenario.subject,
                        "manual_message":"This is the single authorized KBC Library Gmail integration test.\n"
                            "Sent through Django EmailOutbox, EmailWorker and Gmail API.\n"
                            "No student records were used. Automated sending remains disabled outside this isolated test."})
            guard.message_id = str(row.pk)
            if (EmailOutbox.objects.count() != 1 or EmailAttempt.objects.exists() or row.status != "pending"
                    or row.recipient_email != scenario.recipient or settings.LIBRARY_EMAIL_RECIPIENT_ALLOWLIST != (scenario.recipient,)
                    or settings.LIBRARY_EMAIL_SCHEDULER_ENABLED or render_email(row)[0] != scenario.subject):
                raise SingleTestError("single_message_preflight_failed")
            print(json.dumps({"stage":"isolated_preflight_passed", "database":DBNAME, "database_host":"127.0.0.1",
                              "outbox_count":1, "allowlist":[scenario.recipient], "max_attempts":1, "scheduler_enabled":False}), flush=True)
            outcomes = worker.run_once(limit=1)  # ONLY invocation. Never retry, including retryable/uncertain.
            row.refresh_from_db()
            attempts = list(EmailAttempt.objects.filter(message=row).order_by("attempt_number"))
            result.update({"worker_outcomes":outcomes, "outbox_id":str(row.pk), "outbox_status":row.status,
                "attempt_count":len(attempts), "attempt_result":attempts[0].result if attempts else None,
                "http_status":attempts[0].http_status if attempts else None, "error_code":row.error_code,
                "provider_request_id":row.provider_request_id, "send_calls":guard.send_calls,
                "gmail_response":guard.response, "db_records_retained":True})
            if EmailOutbox.objects.count() != 1 or len(attempts) > 1 or guard.send_calls > 1:
                raise SingleTestError("single_message_postcondition_failed")
    except Exception as exc:
        result["error_code"] = str(exc) if isinstance(exc, SingleTestError) else "isolated_test_stopped_safe_error"
        # The durable attempted marker and database remain for investigation.
    finally:
        for name in ("LIBRARY_EMAIL_ENQUEUE_ENABLED", "LIBRARY_EMAIL_WORKER_ENABLED", "LIBRARY_EMAIL_SCHEDULER_ENABLED",
                     "LIBRARY_GMAIL_SEND_ENABLED", "LIBRARY_GMAIL_CREDENTIALS_APPROVED", "LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED"):
            setattr(settings, name, False)
        settings.LIBRARY_EMAIL_OWNED_EVENTS = settings.LIBRARY_EMAIL_RECIPIENT_ALLOWLIST = ()
        if worker:
            worker.client._invalidate_token(worker.client._token)
        for name in ("LIBRARY_GMAIL_CLIENT_ID", "LIBRARY_GMAIL_CLIENT_SECRET", "LIBRARY_GMAIL_REFRESH_TOKEN"):
            setattr(settings, name, "")
        if connections:
            connections.close_all()
        result["settings_disabled_after_test"] = True
        (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    return 0 if result.get("outbox_status") == "accepted" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin")
    parser.add_argument("--scenario", choices=tuple(SCENARIOS), default="ai-team", help="A fixed sender, recipient, subject and independent single-send fence.")
    parser.add_argument("--send-once", action="store_true", help="Use the explicitly authorized single-message budget.")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--root", help=argparse.SUPPRESS)
    parser.add_argument("--nonce", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.child:
        return run_child(options)
    if options.send_once and first_test_marker(SCENARIOS[options.scenario]).exists():
        raise SingleTestError("first_real_test_already_attempted_no_resend")
    pg_bin = Path(options.pg_bin).resolve(strict=True)
    for filename in ("initdb.exe", "pg_ctl.exe", "createdb.exe"):
        if not (pg_bin / filename).is_file():
            raise SingleTestError("installed_local_postgresql_binaries_required")
    root = Path(tempfile.mkdtemp(prefix="kbc-first-gmail-test-")).resolve()
    nonce = uuid.uuid4().hex
    (root / "run.json").write_text(json.dumps({"nonce":nonce,"live":options.send_once}))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0))
        port = probe.getsockname()[1]
    env = {name:os.environ[name] for name in ("SYSTEMROOT","WINDIR","PATH","TEMP","TMP","LANG","LOCALAPPDATA","PYTHONTZPATH") if name in os.environ}
    started = False
    def run(command, *, check=True):
        with (root / "local-process.log").open("ab") as log:
            completed = subprocess.run(command, env=env, cwd=Path(__file__).parent, stdout=log, stderr=log,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0), check=False)
        if check and completed.returncode:
            raise SingleTestError("isolated_local_process_failed_review_local_log")
        return completed.returncode
    try:
        run([str(pg_bin / "initdb.exe"),"-D",str(root / "data"),"-U",DBUSER,"--auth=trust","--encoding=UTF8","--locale=C"])
        run([str(pg_bin / "pg_ctl.exe"),"-D",str(root / "data"),"-l",str(root / "postgres.log"),
             "-o",f"-h 127.0.0.1 -p {port}","-w","start"])
        started = True
        run([str(pg_bin / "createdb.exe"),"-h","127.0.0.1","-p",str(port),"-U",DBUSER,DBNAME])
        code = run([sys.executable,"-B",str(Path(__file__).resolve()),"--child","--root",str(root),
                    "--nonce",nonce,"--port",str(port),"--scenario",options.scenario,*(["--send-once"] if options.send_once else [])], check=False)
        result_path = root / "result.json"
        print(result_path.read_text(encoding="utf-8") if result_path.exists() else '{"error":"child_stopped_before_result_no_automatic_retry"}')
        return code
    finally:
        if started:
            stopped = run([str(pg_bin / "pg_ctl.exe"),"-D",str(root / "data"),"-m","fast","-w","stop"],check=False) == 0
            print(json.dumps({"isolated_postgres_stopped":stopped, "test_records_directory":str(root)}), flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SingleTestError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    except Exception:
        print("single_gmail_test_stopped_no_automatic_retry", file=sys.stderr)
        raise SystemExit(2)
