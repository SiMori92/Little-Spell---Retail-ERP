"""Create the DatasetSettings singleton, as SAMPLE.

The row is created by MIGRATION rather than lazily on first read, so that a fresh
database is quarantined from the moment it exists rather than from the moment
somebody first loads a page.
"""

from django.db import migrations


def create_singleton(apps, schema_editor):
    DatasetSettings = apps.get_model("core", "DatasetSettings")
    DatasetSettings.objects.get_or_create(pk=1, defaults={"dataset_kind": "SAMPLE"})


def delete_singleton(apps, schema_editor):
    DatasetSettings = apps.get_model("core", "DatasetSettings")
    DatasetSettings.objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0003_audit_append_only")]

    operations = [migrations.RunPython(create_singleton, delete_singleton)]
