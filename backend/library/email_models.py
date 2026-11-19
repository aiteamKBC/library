"""Durable email records. Nothing in this module queues or sends messages."""
import uuid
import re
from datetime import datetime, timezone as utc_timezone

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .timezones import validate_iana_timezone


def validate_email_record(instance):
    for field in instance._meta.fields:
        if isinstance(field, models.DateTimeField):
            value = getattr(instance, field.name)
            if value is not None:
                if not isinstance(value, datetime) or timezone.is_naive(value):
                    raise ValidationError({field.name: "An explicit timezone-aware timestamp is required."})
                setattr(instance, field.name, value.astimezone(utc_timezone.utc))
    if not isinstance(instance.error_summary, str):
        raise ValidationError({"error_summary": "A sanitized text summary is required."})
    if re.search(r"bearer\s+\S+|access_token\s*[:=]|client_secret\s*[:=]|password\s*[:=]", instance.error_summary, re.I):
        raise ValidationError({"error_summary": "Store a sanitized error code/summary, not credentials or provider response bodies."})


class EmailOutbox(models.Model):
    class Status(models.TextChoices):
        BLOCKED = "blocked", "Blocked: needs review"
        PENDING = "pending", "Pending"
        RETRY_WAIT = "retry_wait", "Retry waiting"
        CLAIMED = "claimed", "Claimed, not submitted"
        SUBMITTING = "submitting", "Submission in progress"
        ACCEPTED = "accepted", "Provider accepted (not proof of delivery)"
        FAILED = "failed", "Permanently failed"
        UNCERTAIN = "uncertain", "Uncertain: no automatic resubmission"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_id = models.UUIDField(db_index=True)
    event_type = models.CharField(max_length=64)
    message_kind = models.CharField(max_length=16, choices=[("event", "Immediate event"), ("reminder", "Scheduled reminder")])
    loan = models.ForeignKey("library.Loan", on_delete=models.SET_NULL, null=True, blank=True, related_name="email_messages")
    book_request = models.ForeignKey("library.BookRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="email_messages")
    source_type = models.CharField(max_length=20, blank=True)
    source_id = models.CharField(max_length=50, blank=True)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="library_email_messages")
    recipient_key = models.CharField(max_length=150)
    recipient_email = models.EmailField()
    recipient_role = models.CharField(max_length=20, choices=[("student", "Student"), ("admin", "Administration"), ("librarian", "Librarian"), ("external", "External recipient")])
    recipient_timezone = models.CharField(max_length=100, null=True, blank=True, validators=[validate_iana_timezone])
    template_key = models.CharField(max_length=100)
    template_version = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    payload = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    due_date_snapshot = models.DateField(null=True, blank=True)
    deadline_revision = models.PositiveBigIntegerField(null=True, blank=True)
    reminder_local_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BLOCKED)
    attempts_count = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now, help_text="UTC earliest submission or next retry time")
    expires_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    worker_id = models.CharField(max_length=100, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    provider_request_id = models.CharField(max_length=200, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_summary = models.CharField(max_length=500, blank=True, help_text="Sanitized summary only; never credentials, tokens or raw provider responses")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "library_email_outbox"
        indexes = [
            models.Index(fields=["status", "available_at"], name="lib_email_due_idx"),
            models.Index(fields=["status", "lease_expires_at"], name="lib_email_lease_idx"),
            models.Index(fields=["loan", "deadline_revision"], name="lib_email_deadline_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["blocked", "pending", "retry_wait", "claimed", "submitting", "accepted", "failed", "uncertain", "cancelled"]), name="lib_email_status_valid"),
            models.CheckConstraint(condition=Q(message_kind__in=["event", "reminder"]), name="lib_email_kind_valid"),
            models.CheckConstraint(condition=~Q(idempotency_key=""), name="lib_email_key_nonempty"),
            models.CheckConstraint(condition=~Q(recipient_key=""), name="lib_email_recipient_key"),
            models.CheckConstraint(condition=Q(template_version__gte=1), name="lib_email_template_version"),
            models.CheckConstraint(condition=~Q(loan__isnull=False, book_request__isnull=False), name="lib_email_one_source"),
            models.CheckConstraint(condition=(~Q(message_kind="reminder") | Q(due_date_snapshot__isnull=False,
                deadline_revision__isnull=False, reminder_local_date__isnull=False, expires_at__isnull=False)), name="lib_email_reminder_snapshot"),
            models.CheckConstraint(condition=(Q(status__in=["blocked", "failed", "uncertain", "cancelled"])
                | (Q(recipient_timezone__isnull=False) & ~Q(recipient_timezone=""))), name="lib_email_ready_timezone"),
            models.CheckConstraint(condition=(
                Q(status__in=["claimed", "submitting"], lease_token__isnull=False, lease_expires_at__isnull=False) & ~Q(worker_id="")
                | (~Q(status__in=["claimed", "submitting"]) & Q(lease_token__isnull=True, lease_expires_at__isnull=True, worker_id=""))
            ), name="lib_email_lease_consistent"),
            models.CheckConstraint(condition=~Q(status="accepted") | Q(accepted_at__isnull=False), name="lib_email_acceptance_time"),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and not self.source_id:
            if self.loan_id:
                self.source_type, self.source_id = "loan", self.loan_id
            elif self.book_request_id:
                self.source_type, self.source_id = "book_request", self.book_request_id
        # The database unique index is the concurrency arbiter on insertion.
        self.full_clean(validate_unique=not self._state.adding)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        validate_email_record(self)
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise ValidationError({"idempotency_key": "A non-empty logical message key is required."})
        if not isinstance(self.payload, dict):
            raise ValidationError({"payload": "Template payload must be a JSON object."})


class RetainedAttemptQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("Email attempt history requires a separately authorized retention process.")


class EmailAttempt(models.Model):
    objects = models.Manager.from_queryset(RetainedAttemptQuerySet)()
    message = models.ForeignKey(EmailOutbox, on_delete=models.PROTECT, related_name="attempts")
    attempt_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    result = models.CharField(max_length=20, choices=[("started", "Started"), ("accepted", "Accepted"),
        ("retryable_failure", "Retryable failure"), ("permanent_failure", "Permanent failure"), ("uncertain", "Uncertain")])
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(100), MaxValueValidator(599)])
    provider_request_id = models.CharField(max_length=200, blank=True)
    worker_id = models.CharField(max_length=100, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_summary = models.CharField(max_length=500, blank=True, help_text="Sanitized summary only; no raw responses or secrets")

    class Meta:
        db_table = "library_email_attempt"
        constraints = [
            models.UniqueConstraint(fields=["message", "attempt_number"], name="lib_email_attempt_number_unique"),
            models.CheckConstraint(condition=Q(attempt_number__gte=1), name="lib_email_attempt_positive"),
            models.CheckConstraint(condition=Q(http_status__isnull=True) | Q(http_status__gte=100, http_status__lte=599), name="lib_email_http_status"),
            models.CheckConstraint(condition=Q(result="started") | Q(finished_at__isnull=False), name="lib_email_attempt_finished"),
            models.CheckConstraint(condition=Q(finished_at__isnull=True) | Q(finished_at__gte=models.F("started_at")), name="lib_email_attempt_time_order"),
            models.CheckConstraint(condition=Q(result__in=["started", "accepted", "retryable_failure", "permanent_failure", "uncertain"]), name="lib_email_attempt_result"),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        validate_email_record(self)

    def delete(self, *args, **kwargs):
        raise ValidationError("Email attempt history is retained. Use a separately authorized retention process.")
