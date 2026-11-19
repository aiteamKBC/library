from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import UserProfile
from .timezones import validated_timezone


def save_own_timezone(user, value, *, source, observed_at=None, explicit=False):
    zone = validated_timezone(value).key
    observed_at = observed_at or timezone.now()  # Server time only, never a posted timestamp.
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        UserProfile.objects.get_or_create(user=user)
        profile = UserProfile.objects.select_for_update().get(user=user)
        if not explicit and profile.time_zone_source == "manual":
            return profile, "manual_preserved"
        if profile.time_zone_updated_at and observed_at < profile.time_zone_updated_at:
            return profile, "stale_ignored"
        profile.time_zone = zone
        profile.time_zone_source = source
        profile.time_zone_updated_at = observed_at
        profile.full_clean()
        profile.save(update_fields=["time_zone", "time_zone_source", "time_zone_updated_at", "updated_at"])
        return profile, "saved"
