from django.db import migrations


DEFAULT_COPY_COUNT = 3


def ensure_three_copies_per_resource(apps, schema_editor):
    Resource = apps.get_model("library", "Resource")
    BookCopy = apps.get_model("library", "BookCopy")

    for resource in Resource.objects.all().iterator():
        existing_accessions = set(
            BookCopy.objects.filter(resource_id=resource.pk).values_list("accession_number", flat=True)
        )
        for number in range(1, DEFAULT_COPY_COUNT + 1):
            accession_number = f"{resource.pk}-{number:03d}"
            if accession_number in existing_accessions:
                continue
            BookCopy.objects.create(
                resource_id=resource.pk,
                accession_number=accession_number,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0013_alter_loan_status"),
    ]

    operations = [
        migrations.RunPython(ensure_three_copies_per_resource, migrations.RunPython.noop),
    ]
