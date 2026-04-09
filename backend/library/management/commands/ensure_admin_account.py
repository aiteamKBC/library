import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from library.models import UserProfile, ensure_user_profile


class Command(BaseCommand):
    help = "Ensure that a library admin account exists."

    def handle(self, *args, **options):
        username = os.getenv("LIBRARY_ADMIN_USERNAME", "admin")
        password = os.getenv("LIBRARY_ADMIN_PASSWORD", "admin2025")
        email = os.getenv("LIBRARY_ADMIN_EMAIL", "admin@kbc.local")
        first_name = os.getenv("LIBRARY_ADMIN_FIRST_NAME", "Library")
        last_name = os.getenv("LIBRARY_ADMIN_LAST_NAME", "Admin")

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": True,
            },
        )

        if created or not user.check_password(password):
            user.set_password(password)

        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.is_staff = True
        user.save()

        profile = ensure_user_profile(user)
        profile.role = UserProfile.Role.ADMIN
        profile.save(update_fields=["role", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Library admin account is ready for username '{username}'"))
