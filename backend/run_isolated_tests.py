"""Run synthetic SQLite tests without loading .env, networking, or sending mail."""
import os
import socket
import sys
from contextlib import ExitStack
from unittest.mock import patch


def forbidden(*args, **kwargs):
    raise AssertionError("External connections and email delivery are forbidden in isolated tests.")


def forbidden_migration(*args, **kwargs):
    raise AssertionError("Migration execution is forbidden in schema-only test mode.")


def main():
    schema_only = "--schema-only" in sys.argv
    if schema_only:
        sys.argv.remove("--schema-only")
        if "--makemigrations" in sys.argv:
            raise ValueError("Schema-only mode does not permit migration commands.")
    pg_port = None
    if "--postgres-port" in sys.argv:
        index = sys.argv.index("--postgres-port")
        pg_port = str(int(sys.argv[index + 1]))
        if not 1024 <= int(pg_port) <= 65535:
            raise ValueError("Synthetic PostgreSQL port must be an unprivileged local port.")
        del sys.argv[index:index + 2]
    # Drop inherited application configuration, including database/mail credentials.
    retained = {name: os.environ[name] for name in (
        "SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "TZ", "PYTHONTZPATH",
    ) if name in os.environ}
    os.environ.clear()
    os.environ.update(retained)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.test_settings"
    os.environ["LIBRARY_ISOLATED_TESTS"] = "1"
    if pg_port:
        os.environ["KBC_SYNTHETIC_PG_PORT"] = pg_port
    if schema_only:
        os.environ["KBC_SYNTHETIC_SCHEMA_ONLY"] = "1"
    with ExitStack() as stack:
        for target in (
            "socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex",
            "socket.socket.sendto", "socket.getaddrinfo",
            "django.core.mail.send_mail", "django.core.mail.send_mass_mail",
            "django.core.mail.message.EmailMessage.send",
            "django.core.mail.backends.smtp.EmailBackend.send_messages",
        ):
            stack.enter_context(patch(target, forbidden))
        if pg_port:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict
            original_connect = psycopg.Connection.connect

            def synthetic_connect(conninfo="", **kwargs):
                values = conninfo_to_dict(conninfo, **{k: v for k, v in kwargs.items()
                                                      if k not in ("autocommit", "prepare_threshold", "context", "row_factory", "cursor_factory")})
                if (values.get("host") != "127.0.0.1" or str(values.get("port")) != pg_port
                        or values.get("hostaddr", "127.0.0.1") != "127.0.0.1" or values.get("service")
                        or values.get("user") != "kbc_test_admin" or values.get("password", "")
                        or values.get("dbname") not in ("postgres", "kbc_phase3_tests", "test_kbc_phase3_tests")):
                    forbidden()
                return original_connect(conninfo, **kwargs)
            stack.enter_context(patch("psycopg.connect", synthetic_connect))
            stack.enter_context(patch("psycopg.Connection.connect", synthetic_connect))
        else:
            stack.enter_context(patch("psycopg.connect", forbidden))
            stack.enter_context(patch("psycopg.Connection.connect", forbidden))
        import django
        django.setup()
        if schema_only:
            stack.enter_context(patch("django.db.migrations.executor.MigrationExecutor.migrate", forbidden_migration))
        stack.enter_context(patch("library.views.send_library_webhook", forbidden))
        from django.core.management import execute_from_command_line
        if sys.argv[1:2] == ["--makemigrations"]:
            execute_from_command_line([sys.argv[0], "makemigrations", "library", "--noinput", *sys.argv[2:]])
        else:
            execute_from_command_line([sys.argv[0], "test", *(sys.argv[1:] or ["library"]), "--noinput"])


if __name__ == "__main__":
    main()
