from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime


LONDON = ZoneInfo("Europe/London")
LEGACY_CAIRO = ZoneInfo("Africa/Cairo")


def validated_timezone(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValidationError({"timeZone": "A saved IANA timezone is required; no timezone has been assumed."})
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValidationError({"timeZone": "Use a valid IANA timezone, such as Africa/Cairo or America/New_York."}) from exc


def recipient_timezone_status(value):
    if value is None or value == "":
        return "missing"
    try:
        validated_timezone(value)
    except ValidationError:
        return "invalid"
    return "valid"


def validate_iana_timezone(value):
    validated_timezone(value)


def approved_utc_cutover(value, setting_name):
    try:
        cutover = value if isinstance(value, datetime) else parse_datetime(value)
    except (TypeError, ValueError):
        cutover = None
    if cutover is None or timezone.is_naive(cutover) or cutover.utcoffset() != timedelta(0):
        raise ValidationError({"delivery_days": f"An approved {setting_name} in UTC must be configured before confirming loans or recalculating return dates."})
    return cutover


def require_aware(instant):
    if not isinstance(instant, datetime) or timezone.is_naive(instant):
        raise ValidationError({"confirmed_at": "A reliable, timezone-aware timestamp is required."})
    return instant


def calculate_deadline(confirmed_at, calculation_timezone, delivery_days, borrowing_days=30):
    zone = validated_timezone(calculation_timezone)
    return timezone.localdate(require_aware(confirmed_at), timezone=zone) + timedelta(days=borrowing_days + delivery_days)


@dataclass(frozen=True)
class LoanTimezoneSnapshot:
    """Policy value object only. Persistence/activation requires the proposed schema."""
    policy: str
    calculation_timezone: str
    confirmed_at: datetime

    def __post_init__(self):
        if self.policy not in {"cairo_v1", "london_v1", "user_local_v1"}:
            raise ValidationError({"policy": "An explicit, verified loan policy is required."})
        validated_timezone(self.calculation_timezone)
        object.__setattr__(self, "confirmed_at", require_aware(self.confirmed_at).astimezone(dt_timezone.utc))
        fixed = {"cairo_v1": "Africa/Cairo", "london_v1": "Europe/London"}.get(self.policy)
        if fixed and fixed != self.calculation_timezone:
            raise ValidationError({"policy": "The calculation timezone does not match the historical policy."})

    def deadline(self, delivery_days):
        return calculate_deadline(self.confirmed_at, self.calculation_timezone, delivery_days)

    @classmethod
    def for_student(cls, saved_student_timezone):
        # Only a future transactional confirmation service may persist this.
        # The browser must never supply the authoritative confirmation instant.
        zone = validated_timezone(saved_student_timezone)
        return cls("user_local_v1", zone.key, timezone.now())


def london_today():
    # Existing persisted state uses the previous release's London operational day.
    # Browser/recipient timezones must never change that state. New policy cannot
    # activate until immutable per-loan timezone storage has been approved.
    return timezone.localdate(timezone.now(), timezone=LONDON)


def confirmation_timezone(confirmed_at):
    require_aware(confirmed_at)
    boundary = getattr(settings, "LIBRARY_LONDON_CUTOVER_AT", "")
    # The original application calendar was Cairo. An absent London boundary
    # means that no London transition is configured, not that we should invent
    # one or refuse new legacy confirmations. Persisted history is never inferred
    # through this selection: Loan retains saved dates and immutable snapshots.
    if boundary is None or boundary == "":
        return LEGACY_CAIRO
    # An explicitly configured but malformed boundary remains an error.
    cutover = approved_utc_cutover(boundary, "LIBRARY_LONDON_CUTOVER_AT")
    return LEGACY_CAIRO if confirmed_at < cutover else LONDON
