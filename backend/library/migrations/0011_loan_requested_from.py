from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0010_remove_userprofile_auth_provider_and_delete_studentemailverification"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="requested_from",
            field=models.DateField(blank=True, null=True),
        ),
    ]
