from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0009_studentemailverification"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="userprofile",
            name="auth_provider",
        ),
        migrations.DeleteModel(
            name="StudentEmailVerification",
        ),
    ]
