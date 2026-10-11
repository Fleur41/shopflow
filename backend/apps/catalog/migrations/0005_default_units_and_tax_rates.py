"""Give businesses created before products existed the sign-up defaults.

The values are copied here rather than imported, so this migration keeps
meaning the same if the defaults change later.
"""

from decimal import Decimal

from django.db import migrations

UNITS = [("PCS", "Pieces", False, "U"), ("KG", "Kilogram", True, "KG"), ("L", "Litre", True, "LTR")]
KENYA_TAX_RATES = [
    ("VAT 16%", Decimal("0.16"), "B"),
    ("VAT 8%", Decimal("0.08"), "E"),
    ("Zero-rated", Decimal("0"), "C"),
    ("Exempt", Decimal("0"), "A"),
]


def add_defaults(apps, schema_editor):
    Organization = apps.get_model("organizations", "Organization")
    UnitOfMeasure = apps.get_model("catalog", "UnitOfMeasure")
    TaxRate = apps.get_model("catalog", "TaxRate")
    for organization in Organization.objects.all():
        units = UnitOfMeasure.unscoped.filter(organization=organization)
        if not units.exists():
            UnitOfMeasure.unscoped.bulk_create(
                UnitOfMeasure(organization=organization, code=code, name=name,
                              allows_fraction=fraction, etims_quantity_unit=kra_unit)
                for code, name, fraction, kra_unit in UNITS
            )  # fmt: skip
        if not TaxRate.unscoped.filter(organization=organization).exists():
            rates = (
                KENYA_TAX_RATES
                if organization.base_currency == "KES"
                else [("No tax", Decimal("0"), "")]
            )
            TaxRate.unscoped.bulk_create(
                TaxRate(organization=organization, name=name, rate=rate, etims_tax_type=tax_type)
                for name, rate, tax_type in rates
            )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0004_products")]
    operations = [migrations.RunPython(add_defaults, migrations.RunPython.noop)]
