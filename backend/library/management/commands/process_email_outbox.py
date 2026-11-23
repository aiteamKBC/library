from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ImproperlyConfigured
from library.email_execution import drain_outbox


class Command(BaseCommand):
    requires_system_checks = []
    help = "Drain bounded outbox batches and recover leases, then exit. Also suitable for recovery timers."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-batches", type=int, default=5)

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 10000:
            raise CommandError("limit must be between 1 and 10000")
        if not 1 <= options["max_batches"] <= 100:
            raise CommandError("max-batches must be between 1 and 100")
        try:
            result = drain_outbox(limit=options["limit"], max_batches=options["max_batches"])
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(result))
