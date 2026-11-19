"""SELECT-only readiness checklist; never links users or assigns timezones."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from library.models import Loan, UserProfile
from library.timezones import recipient_timezone_status


class Command(BaseCommand):
    help = "Read-only technical timezone checklist for requested borrow loans; no student names or email addresses."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--expected-borrow-count", type=int)
        parser.add_argument("--require-ready", action="store_true")

    def handle(self, *args, **options):
        expected = options["expected_borrow_count"]
        if expected is not None and expected < 0:
            raise CommandError("Expected borrow count must not be negative.")
        rows = list(Loan.objects.filter(status="requested").select_related("borrower__library_profile").order_by("pk"))
        checklist = []
        notify = other = 0
        for loan in rows:
            if loan.loan_type != "borrow":
                if loan.loan_type == "notify":
                    notify += 1
                else:
                    other += 1
                continue
            blockers = []
            if loan.borrower_id is None:
                blockers.append("ACCOUNT_NOT_LINKED")
            else:
                user = loan.borrower
                if not user.is_active:
                    blockers.append("ACCOUNT_INACTIVE")
                try:
                    profile = user.library_profile
                except UserProfile.DoesNotExist:
                    blockers.append("PROFILE_MISSING")
                else:
                    status = recipient_timezone_status(profile.time_zone)
                    if status != "valid":
                        blockers.append("TIMEZONE_" + status.upper())
                    elif (profile.time_zone_source not in {"manual", "browser"}
                          or profile.time_zone_updated_at is None or timezone.is_naive(profile.time_zone_updated_at)):
                        blockers.append("TIMEZONE_PROVENANCE_MISSING")
            checklist.append({"loan_id": loan.pk, "ready": not blockers, "blockers": blockers})
        ready = sum(item["ready"] for item in checklist)
        count_matches = expected is None or len(checklist) == expected
        result = {"requested_total": len(rows), "requested_borrow": len(checklist), "requested_notify": notify,
                  "other_requested": other, "expected_borrow_count": expected, "count_matches": count_matches,
                  "ready": ready, "blocked": len(checklist) - ready, "loans": checklist}
        self.stdout.write(json.dumps(result, indent=2))
        if options["require_ready"] and (not count_matches or ready != len(checklist)):
            raise CommandError("Timezone cutover checklist is not ready. No data was changed.")
