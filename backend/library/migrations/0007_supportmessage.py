from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0006_userprofile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportMessage",
            fields=[
                ("id", models.CharField(max_length=50, primary_key=True, serialize=False)),
                ("full_name", models.CharField(max_length=120)),
                ("email", models.EmailField(max_length=254)),
                ("course", models.CharField(blank=True, max_length=160)),
                ("subject", models.CharField(max_length=120)),
                ("message", models.TextField()),
                ("status", models.CharField(choices=[("new", "New"), ("in_progress", "In Progress"), ("resolved", "Resolved")], default="new", max_length=20)),
                ("submitted_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("internal_notes", models.TextField(blank=True)),
                ("requester", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="support_messages", to=settings.AUTH_USER_MODEL)),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resolved_support_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-submitted_at"],
            },
        ),
    ]
