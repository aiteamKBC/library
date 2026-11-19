"""Current-user Windows DPAPI vault outside the repository. No plaintext fallback."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path


class CredentialStoreError(Exception):
    pass


TEST_PROFILE = "ai-team-test"
PROFILE_FILES = {"library": "gmail.dpapi", TEST_PROFILE: "gmail-ai-team-test.dpapi"}


def default_vault_path(profile="library"):
    if profile not in PROFILE_FILES:
        raise CredentialStoreError("Unknown Google credential profile.")
    local = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not local:
        raise CredentialStoreError("A Windows current-user vault is required on this machine.")
    return Path(local) / "KBC-Library" / "oauth" / PROFILE_FILES[profile]


def checked_path(path):
    path = Path(path).expanduser().resolve()
    repository = Path(__file__).resolve().parents[2]
    if path.is_relative_to(repository) or any((p / ".git").exists() for p in (path.parent, *path.parents)):
        raise CredentialStoreError("OAuth secrets must be stored outside every Git working tree.")
    return path


def _crypt(data, *, decrypt=False):
    if os.name != "nt":
        raise CredentialStoreError("DPAPI is unavailable; no plaintext fallback is allowed.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    def blob(raw):
        buffer = ctypes.create_string_buffer(raw)
        return buffer, Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))

    source_buffer, source = blob(data)
    entropy_buffer, entropy = blob(b"KBC-Library:GoogleOAuth:v1")
    output = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; deliberately NOT LOCAL_MACHINE.
    if not operation(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 1, ctypes.byref(output)):
        raise CredentialStoreError("The current Windows user could not access the OAuth vault.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(output.data)


def save_credentials(path, credentials):
    path = checked_path(path)
    # Protect before creating anything. Access tokens are deliberately excluded.
    permitted = {"client_id", "client_secret", "refresh_token", "account_email", "account_sub",
                 "sender", "reply_to", "sender_name", "scopes", "verified_at", "redirect_uri", "n8n_identity_confirmed",
                 "profile_name", "credential_usage", "production_sender_approved"}
    if set(credentials) - permitted:
        raise CredentialStoreError("Unsupported credential fields; access tokens must not be persisted.")
    encoded = _crypt(json.dumps(credentials, ensure_ascii=False).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise CredentialStoreError("An OAuth vault already exists; it will not be overwritten.") from None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"KBC-GMAIL-DPAPI-1\n" + encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise CredentialStoreError("The encrypted OAuth vault could not be saved.") from None


def load_credentials(path):
    path = checked_path(path)
    try:
        raw = path.read_bytes()
        prefix = b"KBC-GMAIL-DPAPI-1\n"
        if not raw.startswith(prefix):
            raise ValueError()
        value = json.loads(_crypt(raw[len(prefix):], decrypt=True))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, ValueError, TypeError):
        raise CredentialStoreError("The encrypted OAuth vault could not be read.") from None


def settings_from_vault(path):
    value = load_credentials(path)
    if value.get("credential_usage") == "test_only" or value.get("profile_name") == TEST_PROFILE:
        raise CredentialStoreError("Test-only Google authorization cannot configure the application sender.")
    fields = {"CLIENT_ID": "client_id", "CLIENT_SECRET": "client_secret", "REFRESH_TOKEN": "refresh_token",
              "ACCOUNT_EMAIL": "account_email", "SENDER": "sender", "REPLY_TO": "reply_to", "SENDER_NAME": "sender_name"}
    return {"LIBRARY_GMAIL_" + key: value.get(source, "") for key, source in fields.items()}
