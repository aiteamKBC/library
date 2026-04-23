from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0014_ensure_three_copies_per_resource"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="return_condition",
            field=models.CharField(
                blank=True,
                choices=[
                    ("good", "Good / Intact"),
                    ("worn", "Worn / Used"),
                    ("damaged", "Damaged"),
                    ("torn", "Torn"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="loan",
            name="return_condition_notes",
            field=models.TextField(blank=True),
        ),
    ]
