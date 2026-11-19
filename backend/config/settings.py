import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


# The isolated test entry point sets this before importing any Django settings.
# Never load a real .env or parse a configured database URL in that mode.
ISOLATED_TESTS = os.getenv("LIBRARY_ISOLATED_TESTS") == "1"
if not ISOLATED_TESTS:
    load_env_file(ENV_FILE)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def database_config() -> dict[str, object]:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        # Allow overriding the DB path via env var so the file can live
        # outside OneDrive/Dropbox sync folders (sync hooks add ~700 ms
        # of overhead to every SQLite read on Windows).
        db_path = os.getenv("SQLITE_DB_PATH") or str(BASE_DIR / "db.sqlite3")
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": db_path,
        }

    parsed = urlparse(database_url)
    engine_map = {
        "postgres": "django.db.backends.postgresql",
        "postgresql": "django.db.backends.postgresql",
    }
    engine = engine_map.get(parsed.scheme)
    if not engine:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")

    query = parse_qs(parsed.query)
    config: dict[str, object] = {
        "ENGINE": engine,
        "NAME": unquote((parsed.path or "").lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }

    sslmode = query.get("sslmode", [None])[0]
    if sslmode and sslmode != "disable":
        config["OPTIONS"] = {"sslmode": sslmode}

    return config


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-kbc-library-dev-key")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "library",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
    if ISOLATED_TESTS else database_config()
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/London"
# Retained for legacy operational dates and Resource.date_added's existing
# default. This is not a viewer/recipient timezone. API DateTimes use UTC;
# React uses the viewer's device. Changing this default needs separate review
# of model defaults and the proposed policy metadata (no schema changes here).
USE_I18N = True
USE_TZ = True

# Independent opt-ins; no credentials are inherited from n8n/SMTP/Azure.
LIBRARY_EMAIL_PROVIDER = os.getenv("LIBRARY_EMAIL_PROVIDER", "gmail").strip().lower()
LIBRARY_EMAIL_ENQUEUE_ENABLED = os.getenv("LIBRARY_EMAIL_ENQUEUE_ENABLED", "false").lower() == "true"
LIBRARY_EMAIL_WORKER_ENABLED = os.getenv("LIBRARY_EMAIL_WORKER_ENABLED", "false").lower() == "true"
LIBRARY_EMAIL_SCHEDULER_ENABLED = os.getenv("LIBRARY_EMAIL_SCHEDULER_ENABLED", "false").lower() == "true"
LIBRARY_GRAPH_SEND_ENABLED = os.getenv("LIBRARY_GRAPH_SEND_ENABLED", "false").lower() == "true"
LIBRARY_GRAPH_CREDENTIALS_APPROVED = os.getenv("LIBRARY_GRAPH_CREDENTIALS_APPROVED", "false").lower() == "true"
LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED = os.getenv("LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED", "false").lower() == "true"
# Staged template/recipient parity only; never enables a transport or sending.
LIBRARY_EMAIL_N8N_COMPAT_ENABLED = os.getenv("LIBRARY_EMAIL_N8N_COMPAT_ENABLED", "false").lower() == "true"
LIBRARY_EMAIL_OWNED_EVENTS = tuple(x.strip() for x in os.getenv("LIBRARY_EMAIL_OWNED_EVENTS", "").split(",") if x.strip())
LIBRARY_EMAIL_ADMIN_USER_IDS = tuple(x.strip() for x in os.getenv("LIBRARY_EMAIL_ADMIN_USER_IDS", "").split(",") if x.strip())
# Exact mailboxes only; an empty list denies every Graph recipient.
LIBRARY_EMAIL_RECIPIENT_ALLOWLIST = tuple(x.strip() for x in os.getenv("LIBRARY_EMAIL_RECIPIENT_ALLOWLIST", "").split(",") if x.strip())
LIBRARY_GRAPH_TENANT_ID = os.getenv("LIBRARY_GRAPH_TENANT_ID", "")
LIBRARY_GRAPH_CLIENT_ID = os.getenv("LIBRARY_GRAPH_CLIENT_ID", "")
LIBRARY_GRAPH_CLIENT_SECRET = os.getenv("LIBRARY_GRAPH_CLIENT_SECRET", "")
LIBRARY_GRAPH_SENDER = os.getenv("LIBRARY_GRAPH_SENDER", "")
# Optional Entra USER object ID for the sender mailbox when SMTP address != UPN.
# Not the application/client ID or the enterprise application's object ID.
LIBRARY_GRAPH_MAILBOX_ID = os.getenv("LIBRARY_GRAPH_MAILBOX_ID", "")
LIBRARY_GRAPH_REPLY_TO = os.getenv("LIBRARY_GRAPH_REPLY_TO", "")
LIBRARY_GMAIL_SEND_ENABLED = env_bool("LIBRARY_GMAIL_SEND_ENABLED", False)
LIBRARY_GMAIL_CREDENTIALS_APPROVED = env_bool("LIBRARY_GMAIL_CREDENTIALS_APPROVED", False)
LIBRARY_GMAIL_CLIENT_ID = os.getenv("LIBRARY_GMAIL_CLIENT_ID", "")
LIBRARY_GMAIL_CLIENT_SECRET = os.getenv("LIBRARY_GMAIL_CLIENT_SECRET", "")
LIBRARY_GMAIL_REFRESH_TOKEN = os.getenv("LIBRARY_GMAIL_REFRESH_TOKEN", "")
# Explicit Google account and verified From identity (may be an approved send-as).
LIBRARY_GMAIL_ACCOUNT_EMAIL = os.getenv("LIBRARY_GMAIL_ACCOUNT_EMAIL", "")
LIBRARY_GMAIL_SENDER = os.getenv("LIBRARY_GMAIL_SENDER", "")
LIBRARY_GMAIL_SENDER_NAME = os.getenv("LIBRARY_GMAIL_SENDER_NAME", "")
LIBRARY_GMAIL_REPLY_TO = os.getenv("LIBRARY_GMAIL_REPLY_TO", "")
# Accept the existing Google-only aliases without changing .env or credentials.
if not ISOLATED_TESTS:
    from library.gmail_oauth_config import resolve_google_config
    _google_config, _google_sources = resolve_google_config()
    if _google_config["client_id"]:
        LIBRARY_GMAIL_CLIENT_ID = _google_config["client_id"]
        LIBRARY_GMAIL_CLIENT_SECRET = _google_config["client_secret"]
    del _google_config, _google_sources
# Optional encrypted current-user vault. It changes credential values only, never
# live gates, provider, event ownership, recipients or scheduling. No .env edit.
LIBRARY_GMAIL_CREDENTIALS_FILE = os.getenv("LIBRARY_GMAIL_CREDENTIALS_FILE", "")
if LIBRARY_GMAIL_CREDENTIALS_FILE and not ISOLATED_TESTS:
    from library.gmail_credential_store import settings_from_vault
    _gmail_vault_values = settings_from_vault(LIBRARY_GMAIL_CREDENTIALS_FILE)
    for _gmail_name, _gmail_value in _gmail_vault_values.items():
        if globals().get(_gmail_name) and globals()[_gmail_name] != _gmail_value:
            raise ValueError("Conflicting Gmail vault and runtime configuration; review before startup.")
        globals()[_gmail_name] = _gmail_value
    del _gmail_vault_values, _gmail_name, _gmail_value
LIBRARY_EMAIL_LEASE_SECONDS = 180
LIBRARY_EMAIL_MAX_ATTEMPTS = 5
# Optional proven London transition. Empty retains the original Cairo calendar
# for new legacy confirmations; no historical transition date is invented.
LIBRARY_LONDON_CUTOVER_AT = os.getenv("LIBRARY_LONDON_CUTOVER_AT", "")
LIBRARY_USER_LOCAL_POLICY_ENABLED = env_bool("LIBRARY_USER_LOCAL_POLICY_ENABLED", False)
LIBRARY_USER_LOCAL_CUTOVER_AT = os.getenv("LIBRARY_USER_LOCAL_CUTOVER_AT", "")

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
)

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 30)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "KBC Library <library@kbc.ac.uk>")
SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://127.0.0.1:3000")
KBC_ALLOWLIST_DATABASE_URL = os.getenv("KBC_ALLOWLIST_DATABASE_URL", "")
KBC_ALLOWLIST_SCHEMA = os.getenv("KBC_ALLOWLIST_SCHEMA", "public")
KBC_ALLOWLIST_TABLE = os.getenv("KBC_ALLOWLIST_TABLE", "kbc_users_data")
KBC_ALLOWLIST_EMAIL_COLUMN = os.getenv("KBC_ALLOWLIST_EMAIL_COLUMN", "Email")
KBC_ALLOWLIST_NAME_COLUMN = os.getenv("KBC_ALLOWLIST_NAME_COLUMN", "FullName")
N8N_LIBRARY_WEBHOOK_URL = os.getenv(
    "N8N_LIBRARY_WEBHOOK_URL",
    "https://n8n.srv943390.hstgr.cloud/webhook/library",
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ]
}
