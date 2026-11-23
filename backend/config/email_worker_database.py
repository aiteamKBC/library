"""Pure configuration validation; never opens a database connection."""
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured


def validate_direct_database(config):
    if (config.get("ENGINE") != "django.db.backends.postgresql"
            or not config.get("HOST") or "-pooler" in config["HOST"].lower()
            or config.get("OPTIONS", {}).get("pool")
            or config.get("ATOMIC_REQUESTS")):
        raise ImproperlyConfigured("Email execution requires a dedicated direct PostgreSQL connection; pooling is not supported.")


def worker_database(url, web_database):
    """Require an explicit direct URL for the same logical application database.

    A custom proxy cannot be identified by hostname: operators must verify that
    the endpoint is direct. Unknown URL options are rejected, not ignored.
    """
    try:
        parsed = urlparse(url or "")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (parsed.scheme not in ("postgres", "postgresql") or not parsed.hostname
                or not parsed.username or not parsed.path.strip("/") or parsed.fragment
                or set(query) - {"sslmode", "connect_timeout"}
                or any(len(values) != 1 for values in query.values())):
            raise ValueError()
        timeout = int(query.get("connect_timeout", ["10"])[0])
        if not 1 <= timeout <= 60:
            raise ValueError()
        sslmode = query.get("sslmode", ["require"])[0]
        if sslmode not in {"require", "verify-ca", "verify-full", "disable"}:
            raise ValueError()
        config = {"ENGINE": "django.db.backends.postgresql", "HOST": parsed.hostname,
                  "PORT": str(parsed.port or 5432), "NAME": unquote(parsed.path.lstrip("/")),
                  "USER": unquote(parsed.username), "PASSWORD": unquote(parsed.password or ""),
                  "OPTIONS": {"sslmode": sslmode, "connect_timeout": timeout},
                  "CONN_MAX_AGE": 0, "CONN_HEALTH_CHECKS": False, "ATOMIC_REQUESTS": False}
    except (ValueError, TypeError):
        raise ImproperlyConfigured("Set a valid LIBRARY_EMAIL_WORKER_DATABASE_URL (direct PostgreSQL).") from None
    validate_direct_database(config)
    if web_database.get("ENGINE") != config["ENGINE"] or web_database.get("NAME") != config["NAME"]:
        raise ImproperlyConfigured("Worker and web must target the same PostgreSQL database.")
    web_host = web_database.get("HOST", "").lower()
    if web_host.endswith(".neon.tech"):
        if config["HOST"] != web_host.replace("-pooler", "") or sslmode == "disable":
            raise ImproperlyConfigured("Worker must use the matching direct Neon endpoint with TLS.")
    return config
