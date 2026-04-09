from django.db import migrations, models


def set_auth_provider_for_existing_users(apps, schema_editor):
    UserProfile = apps.get_model("library", "UserProfile")
    for profile in UserProfile.objects.select_related("user").all():
        password_value = getattr(profile.user, "password", "") or ""
        provider = "kbc_sso" if password_value.startswith("!") else "local"
        if profile.auth_provider != provider:
            profile.auth_provider = provider
            profile.save(update_fields=["auth_provider"])


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0007_supportmessage"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="auth_provider",
            field=models.CharField(choices=[("local", "Local"), ("kbc_sso", "KBC SSO")], default="local", max_length=20),
        ),
        migrations.RunPython(set_auth_provider_for_existing_users, migrations.RunPython.noop),
    ]
