from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from library.email_receiver import inherited_socket, receive_and_process


class Command(BaseCommand):
    help = "Consume inherited wake datagrams, run bounded delivery in this process, and exit."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-batches", type=int, default=5)
        parser.add_argument("--max-signals", type=int, default=256)
        parser.add_argument("--recover-if-idle", action="store_true",
                            help="Permit the same socket service to run from a recovery timer with an empty socket.")

    def handle(self, *args, **options):
        try:
            with inherited_socket(settings.LIBRARY_EMAIL_WAKE_SOCKET) as channel:
                result = receive_and_process(channel, limit=options["limit"], max_batches=options["max_batches"],
                                             max_signals=options["max_signals"],
                                             recover_if_idle=options["recover_if_idle"])
        except (ImproperlyConfigured, ValueError, OSError):
            raise CommandError("Email activation failed; check socket/direct-database configuration and recovery.") from None
        self.stdout.write(str(result))
