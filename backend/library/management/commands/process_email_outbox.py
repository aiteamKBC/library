from collections import Counter
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ImproperlyConfigured
from library.email_worker import EmailWorker


class Command(BaseCommand):
    help = "Process a bounded outbox batch. All live delivery gates must be explicitly enabled."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 10000:
            raise CommandError("limit must be between 1 and 10000")
        try:
            counts = Counter(EmailWorker().run_once(limit=options["limit"]))
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(dict(counts)))
