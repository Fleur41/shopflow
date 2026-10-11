from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    """Fuzzy product search (docs/DATABASE.md §1). pg_trgm is a trusted
    extension, so the schema owner can create it without superuser rights."""

    dependencies = [("catalog", "0002_etims_codes")]
    operations = [TrigramExtension()]
