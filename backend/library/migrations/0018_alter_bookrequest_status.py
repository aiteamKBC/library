from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0017_notificationlog"),
    ]

    operations = [
        migrations.AlterField(
            model_name="bookrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("ordered", "Ordered"),
                    ("cancelled", "Cancelled"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
