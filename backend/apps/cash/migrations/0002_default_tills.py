"""Give every existing store a till, as new stores get at creation."""

from django.db import migrations


def add_tills(apps, schema_editor):
    Store = apps.get_model("organizations", "Store")
    Till = apps.get_model("cash", "Till")
    with_tills = Till.unscoped.values("store_id")
    Till.unscoped.bulk_create(
        Till(organization_id=store.organization_id, store=store, name="Till 1")
        for store in Store.unscoped.exclude(pk__in=with_tills)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("cash", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_tills, migrations.RunPython.noop),
    ]
