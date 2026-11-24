from dataclasses import dataclass
from hashlib import sha256
import json

import psycopg
from psycopg import sql
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from .models import UserProfile, ensure_user_profile

User = get_user_model()

ALLOWLIST_CACHE_TTL_SECONDS = 300
ALLOWLIST_CACHE_MISS = "__missing__"


@dataclass(frozen=True)
class AllowlistedStudent:
    email: str
    full_name: str


def split_full_name(full_name: str) -> tuple[str, str]:
    normalized = " ".join(full_name.strip().split())
    if not normalized:
        return "", ""
    first_name, _, last_name = normalized.partition(" ")
    return first_name, last_name


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def fetch_allowlisted_student(email: str) -> AllowlistedStudent | None:
    normalized_email = normalize_email(email)
    if not normalized_email:
        return None

    database_url = getattr(settings, "KBC_LEARNERS_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("KBC learner directory is not configured.")

    schema_name = getattr(settings, "KBC_LEARNERS_SCHEMA", "Learner").strip() or "Learner"
    table_name = getattr(settings, "KBC_LEARNERS_TABLE", "learners").strip() or "learners"
    email_column = getattr(settings, "KBC_LEARNERS_EMAIL_COLUMN", "email").strip() or "email"
    name_column = getattr(settings, "KBC_LEARNERS_NAME_COLUMN", "full_name").strip() or "full_name"
    # Separate directory sources and legacy cached admissions. Do not put the
    # connection URL, credentials or student email in cache keys.
    identity = json.dumps([database_url, schema_name, table_name, email_column, name_column, normalized_email])
    cache_key = f"library:learners:v1:{sha256(identity.encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if cached is not None:
        if cached == ALLOWLIST_CACHE_MISS:
            return None
        return AllowlistedStudent(**cached)

    query = sql.SQL(
        """
        select {name_column}, {email_column}
        from {schema_name}.{table_name}
        where lower(trim(cast({email_column} as text))) = %s
        limit 1
        """
    ).format(
        name_column=sql.Identifier(name_column),
        email_column=sql.Identifier(email_column),
        schema_name=sql.Identifier(schema_name),
        table_name=sql.Identifier(table_name),
    )

    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '5s'")
                cursor.execute(query, [normalized_email])
                row = cursor.fetchone()
    except psycopg.Error:
        # Keep connection strings and server diagnostics out of API responses.
        raise RuntimeError("KBC learner directory is unavailable.") from None

    if not row:
        cache.set(cache_key, ALLOWLIST_CACHE_MISS, ALLOWLIST_CACHE_TTL_SECONDS)
        return None

    full_name = str(row[0] or "").strip()
    stored_email = normalize_email(str(row[1] or normalized_email))
    student = AllowlistedStudent(
        email=stored_email or normalized_email,
        full_name=full_name,
    )
    cache.set(cache_key, {"email": student.email, "full_name": student.full_name}, ALLOWLIST_CACHE_TTL_SECONDS)
    return student


def sync_student_account_from_allowlist(student: AllowlistedStudent) -> User:
    normalized_email = normalize_email(student.email)
    user = (
        User.objects.filter(email__iexact=normalized_email).first()
        or User.objects.filter(username__iexact=normalized_email).first()
    )
    first_name, last_name = split_full_name(student.full_name or normalized_email)

    if user is None:
        user = User.objects.create_user(
            username=normalized_email,
            email=normalized_email,
            password=None,
            first_name=first_name,
            last_name=last_name,
        )
    else:
        profile = ensure_user_profile(user)
        if user.is_superuser or user.is_staff or profile.role in {UserProfile.Role.ADMIN, UserProfile.Role.LIBRARIAN}:
            raise ValueError("This account uses the library admin portal.")
        user.email = normalized_email
        if not User.objects.filter(username__iexact=normalized_email).exclude(pk=user.pk).exists():
            user.username = normalized_email
        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=["username", "email", "first_name", "last_name"])

    profile = ensure_user_profile(user)
    profile.role = UserProfile.Role.STUDENT
    profile.save(update_fields=["role", "updated_at"])
    return user
