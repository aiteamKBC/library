"""Only for managed email commands; web settings and DATABASE_URL stay unchanged."""
import os

from .settings import *  # noqa: F401,F403
from .email_worker_database import worker_database

DATABASES = {"default": worker_database(
    os.environ.get("LIBRARY_EMAIL_WORKER_DATABASE_URL"), DATABASES["default"])}
LIBRARY_EMAIL_WORKER_DIRECT = True
