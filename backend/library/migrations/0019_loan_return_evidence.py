from django.db import migrations, models

import library.models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0018_alter_bookrequest_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="loan",
            name="return_evidence",
            field=models.FileField(blank=True, upload_to=library.models.loan_return_evidence_upload_to),
        ),
    ]
