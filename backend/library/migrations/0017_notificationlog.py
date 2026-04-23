from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0016_resource_edition"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notification_type", models.CharField(choices=[("due_soon", "Due Soon"), ("overdue", "Overdue")], max_length=30)),
                ("recipient_email", models.EmailField(blank=True, max_length=254)),
                ("sent_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("loan", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notification_logs", to="library.loan")),
            ],
            options={
                "db_table": "library_notification_log",
                "ordering": ["-sent_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="notificationlog",
            constraint=models.UniqueConstraint(fields=("loan", "notification_type"), name="library_notification_log_unique_loan_type"),
        ),
    ]
