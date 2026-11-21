"""Translate only known database identity violations at Django save boundaries."""
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction


DUPLICATE_MESSAGE = "You already have an active borrow or reservation request for this book."
IDENTITY_CONSTRAINTS = {"lib_loan_active_account", "lib_loan_active_email"}


def validate_loan_identity_write(method):
    @wraps(method)
    def save(instance, *args, **kwargs):
        # Catch OUTSIDE a savepoint, so API/Admin callers retain a usable
        # transaction and all source/outbox writes are rolled back together.
        using = kwargs.get("using") or (args[2] if len(args) > 2 else None) or instance._state.db or "default"
        try:
            with transaction.atomic(using=using):
                return method(instance, *args, **kwargs)
        except IntegrityError as exc:
            name = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
            if name in IDENTITY_CONSTRAINTS:
                raise ValidationError(DUPLICATE_MESSAGE) from exc
            if name == "lib_loan_active_identity":
                raise ValidationError("An active loan requires a linked student or a non-empty email address.") from exc
            raise
    return save
