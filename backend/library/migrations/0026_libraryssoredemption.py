from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("library", "0025_active_loan_identity")]

    operations = [
        migrations.CreateModel(
            name="LibrarySSORedemption",
            fields=[
                ("state_hash", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
        ),
    ]
