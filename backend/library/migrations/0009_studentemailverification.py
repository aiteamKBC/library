from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0008_userprofile_auth_provider"),
    ]

    operations = [
        migrations.CreateModel(
            name="StudentEmailVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254)),
                ("code", models.CharField(max_length=6)),
                ("purpose", models.CharField(choices=[("sign_in", "Sign In")], default="sign_in", max_length=20)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
