from django.core.management.base import BaseCommand, CommandError
from library.email_scheduler import schedule_reminders


class Command(BaseCommand):
    help = "Queue only today's eligible recipient-local 09:00 reminders; disabled by default."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 10000:
            raise CommandError("limit must be between 1 and 10000")
        self.stdout.write(str(schedule_reminders(limit=options["limit"])))
