"""Read only Google OAuth fields; never initializes Django or imports DB settings."""
import os
from pathlib import Path
import re


class GoogleConfigError(ValueError):
    pass


ALIASES = {
    "client_id": ("LIBRARY_GMAIL_CLIENT_ID", "GOOGLE_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_ID", "CLIENT ID"),
    "client_secret": ("LIBRARY_GMAIL_CLIENT_SECRET", "GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_CLIENT_SECRET", "CLIENT SECRET"),
    "redirect_uri": ("LIBRARY_GMAIL_REDIRECT_URI", "GOOGLE_REDIRECT_URI", "GOOGLE_OAUTH_REDIRECT_URI"),
    "account_email": ("LIBRARY_GMAIL_ACCOUNT_EMAIL",),
    "sender": ("LIBRARY_GMAIL_SENDER",),
    "reply_to": ("LIBRARY_GMAIL_REPLY_TO",),
}
KNOWN = {alias for aliases in ALIASES.values() for alias in aliases}


def read_google_env(path):
    values = {}
    path = Path(path)
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().upper()
        if name not in KNOWN:
            continue  # Do not return DATABASE_URL, n8n or Microsoft credentials.
        value = value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1:].strip() and not value[end + 1:].lstrip().startswith("#")):
                raise GoogleConfigError("google_oauth_env_quoting_invalid")
            value = value[1:end]
        else:
            value = value.split(" #", 1)[0].rstrip()
        if name in values and values[name] != value:
            raise GoogleConfigError("conflicting_google_oauth_settings")
        values[name] = value
    return values


def resolve_google_config(*, env_path=None, environment=None):
    file_values = read_google_env(env_path) if env_path is not None else {}
    environment = os.environ if environment is None else environment
    process = {name.upper(): value for name, value in environment.items() if name.upper() in KNOWN}
    result, source_names = {}, {}
    for field, aliases in ALIASES.items():
        candidates = [(alias, source[alias]) for source in (file_values, process) for alias in aliases if source.get(alias)]
        unique = {value for _, value in candidates}
        if len(unique) > 1:
            raise GoogleConfigError("conflicting_google_oauth_settings")
        result[field] = next(iter(unique), "")
        source_names[field] = sorted({alias for alias, _ in candidates})
    if result["client_id"] and not re.fullmatch(r"[a-zA-Z0-9._-]+\.apps\.googleusercontent\.com", result["client_id"]):
        raise GoogleConfigError("google_client_id_format_invalid")
    if any(re.search(r"\s", result[key]) for key in ("client_id", "client_secret")):
        raise GoogleConfigError("google_oauth_credential_whitespace_invalid")
    if bool(result["client_id"]) != bool(result["client_secret"]):
        raise GoogleConfigError("google_client_id_and_secret_pair_required")
    return result, source_names
