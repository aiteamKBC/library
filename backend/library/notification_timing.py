"""Pure policy helpers, not an email scheduler, worker, queue, or delivery API."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as utc_timezone
import hashlib
import json

from django.core.exceptions import ValidationError

from .timezones import require_aware, validated_timezone


UTC = utc_timezone.utc


def format_recipient_timestamp(instant, recipient_timezone):
    return require_aware(instant).astimezone(validated_timezone(recipient_timezone)).strftime("%d %b %Y %H:%M %Z")


def local_reminder_window(day, recipient_timezone):
    if not isinstance(day, date) or isinstance(day, datetime):
        raise ValidationError({"due_date": "A calendar date is required."})
    zone = validated_timezone(recipient_timezone)
    wall_time = datetime.combine(day, time(9))
    # Select the first valid occurrence if local 09:00 is ambiguous; skip an
    # impossible local 09:00 rather than moving a reminder into another day.
    candidates = []
    for fold in (0, 1):
        instant = wall_time.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == wall_time:
            candidates.append(instant)
    if not candidates:
        return None
    expires = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return min(candidates), expires


@dataclass(frozen=True)
class ReminderPlan:
    event: str
    days_overdue: int
    local_day: date
    due_date: date
    deadline_revision: int
    recipient_timezone: str
    scheduled_at_utc: datetime
    expires_at_utc: datetime
    logical_key: str


def due_reminder(*, loan_id, recipient_key, recipient_role, due_date, deadline_revision,
                 recipient_timezone, now, status, returned_at=None, last_sent_days_overdue=None):
    require_aware(now)
    zone = validated_timezone(recipient_timezone)  # No silent London/UTC fallback.
    if status not in {"borrowed", "overdue"} or returned_at is not None or due_date is None:
        return None
    if not isinstance(due_date, date) or isinstance(due_date, datetime):
        raise ValidationError({"due_date": "A calendar date is required."})
    today = now.astimezone(zone).date()
    days = (today - due_date).days
    if last_sent_days_overdue is not None and days <= last_sent_days_overdue:
        return None  # Do not regress to an earlier reminder after travel.
    if days == 0:
        event = "due_today"
    elif days == 1 or (days >= 3 and days % 2 == 1):
        event = "overdue"
    else:
        return None
    window = local_reminder_window(today, recipient_timezone)
    if window is None or not window[0] <= now.astimezone(UTC) < window[1]:
        return None
    # Timezone and execution time are deliberately excluded. Travel/rescheduling
    # must not produce another message for the same logical reminder.
    identity = [str(loan_id), str(recipient_key), recipient_role, due_date.isoformat(), deadline_revision, event, days]
    logical_key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    return ReminderPlan(event, days, today, due_date, deadline_revision, recipient_timezone, *window, logical_key)


def reminder_is_current(plan, *, due_date, deadline_revision, recipient_timezone, now, status, returned_at=None):
    require_aware(now)
    zone = validated_timezone(recipient_timezone)
    return (
        status in {"borrowed", "overdue"} and returned_at is None
        and plan.due_date == due_date and plan.deadline_revision == deadline_revision
        and plan.recipient_timezone == recipient_timezone
        and plan.local_day == now.astimezone(zone).date()
        and plan.scheduled_at_utc <= now.astimezone(UTC) < plan.expires_at_utc
    )
