from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0011_loan_requested_from"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="loan_type",
            field=models.CharField(
                choices=[("borrow", "Borrow Request"), ("notify", "Notification Registration")],
                default="borrow",
                max_length=10,
            ),
        ),
    ]
