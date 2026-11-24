import os

# Must precede the base-settings import: do not read .env or DATABASE_URL.
os.environ["LIBRARY_ISOLATED_TESTS"] = "1"
from .settings import *  # noqa: E402,F403

LIBRARY_ISOLATED_TESTS = True
if os.getenv("KBC_SYNTHETIC_SCHEMA_ONLY") == "1":
    TEST_RUNNER = "config.schema_test_runner.SchemaOnlyRunner"

# Keep automated tests isolated from the configured application database/services.
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
if os.getenv("KBC_SYNTHETIC_PG_PORT"):
    DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "HOST": "127.0.0.1",
        "PORT": os.environ["KBC_SYNTHETIC_PG_PORT"], "USER": "kbc_test_admin", "PASSWORD": "",
        "NAME": "kbc_phase3_tests", "TEST": {"NAME": "test_kbc_phase3_tests"}}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
N8N_LIBRARY_WEBHOOK_URL = ""
KBC_ALLOWLIST_DATABASE_URL = ""
KBC_LEARNERS_DATABASE_URL = ""
LIBRARY_LONDON_CUTOVER_AT = "2027-01-01T00:00:00Z"  # Synthetic test boundary only.
SECRET_KEY = "isolated-library-tests-only"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
# Phase 2 explicitly permits applying migrations on this in-memory test database.
