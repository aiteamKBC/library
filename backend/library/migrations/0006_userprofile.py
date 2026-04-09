from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("library", "0005_alter_bookrequest_reason"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("student", "Student"), ("librarian", "Librarian"), ("admin", "Admin")], default="student", max_length=20)),
                ("phone_number", models.CharField(blank=True, max_length=30)),
                ("student_id_code", models.CharField(blank=True, max_length=40)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="library_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["user__username"],
            },
        ),
    ]
