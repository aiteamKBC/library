from django.core.management.base import BaseCommand
from django.db.models import Count, Min, Q
from django.utils import timezone
from library.email_models import EmailOutbox
from library.models import Loan


class Command(BaseCommand):
    help = "Read-only email health summary, without recipient addresses, payloads or credentials."

    def handle(self, *args, **options):
        counts = dict(EmailOutbox.objects.values_list("status").annotate(total=Count("pk")))
        oldest = EmailOutbox.objects.filter(status__in=("pending", "retry_wait")).aggregate(at=Min("available_at"))["at"]
        missing_zone = Loan.objects.filter(status__in=("borrowed", "overdue"), returned_at__isnull=True).filter(
            Q(borrower__isnull=True) | Q(borrower__library_profile__time_zone__isnull=True) | Q(borrower__library_profile__time_zone="")).count()
        self.stdout.write(str({"statuses": counts, "active_loans_without_timezone": missing_zone,
                               "oldest_due_age_seconds": max(0, int((timezone.now() - oldest).total_seconds())) if oldest else 0}))
