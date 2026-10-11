"""Give businesses created before payment methods existed the sign-up defaults.

The values are copied here rather than imported, so this migration keeps
meaning the same if the defaults change later.
"""

from django.db import migrations

DEFAULTS = [
    # code, name, kind, requires_reference, etims_payment_type
    ("CASH", "Cash", "CASH", False, "01"),
    ("MPESA", "M-Pesa", "MOBILE_MONEY", True, "06"),
    ("CARD", "Card", "CARD", False, "05"),
]


def add_defaults(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    PaymentMethod = apps.get_model("payments", "PaymentMethod")
    with_methods = PaymentMethod.unscoped.values("organization_id")
    for organization in Organization.objects.exclude(pk__in=with_methods):
        PaymentMethod.unscoped.bulk_create(
            PaymentMethod(
                organization=organization,
                code=code,
                name=name,
                kind=kind,
                requires_reference=requires_reference,
                etims_payment_type=etims_type,
                position=position,
            )
            for position, (code, name, kind, requires_reference, etims_type) in enumerate(
                DEFAULTS, start=1
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(add_defaults, migrations.RunPython.noop),
    ]
