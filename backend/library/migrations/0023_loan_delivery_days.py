from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0022_remove_studentemailverification_library_stu_email_81cbc0_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="delivery_days",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
