from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import send_mail


class Command(BaseCommand):
    help = "Send a test email using the current Django email settings."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Recipient email address")
        parser.add_argument(
            "--subject",
            default="KBC Library test email",
            help="Subject line for the test email",
        )
        parser.add_argument(
            "--message",
            default="This is a test email from the KBC Library project.",
            help="Plain text message body",
        )

    def handle(self, *args, **options):
        recipient = options["to"].strip()
        subject = options["subject"]
        message = options["message"]

        if not recipient:
            raise CommandError("You must provide a recipient with --to")

        self.stdout.write("Sending test email...")
        self.stdout.write(f"EMAIL_BACKEND={settings.EMAIL_BACKEND}")
        self.stdout.write(f"EMAIL_HOST={settings.EMAIL_HOST or '(not set)'}")
        self.stdout.write(f"EMAIL_PORT={settings.EMAIL_PORT}")
        self.stdout.write(f"DEFAULT_FROM_EMAIL={settings.DEFAULT_FROM_EMAIL}")

        sent_count = send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )

        if sent_count != 1:
            raise CommandError("The email backend did not confirm a successful send.")

        self.stdout.write(self.style.SUCCESS(f"Test email sent successfully to {recipient}"))
