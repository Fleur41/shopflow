"""``make seed``: a demo business built through the real services."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.api.serializers import gtin_check_digit_ok
from apps.catalog.models import Product, ProductIdentifier, ProductPriceHistory
from apps.common.management.commands.seed_demo import (
    CUSTOMERS,
    PRICE_CHANGES,
    PRODUCTS,
    SALES,
    STOCK_OVERRIDES,
    SUPPLIERS,
)
from apps.customers.models import CustomerAccount
from apps.inventory.models import StockLevel
from apps.organizations.models import Membership, Organization, Store
from apps.sales.models import Sale
from apps.suppliers.models import ProductSupplier, Supplier

pytestmark = pytest.mark.django_db


def test_seeds_a_demo_business_once(settings):
    settings.DEBUG = True
    call_command("seed_demo")
    call_command("seed_demo")  # a second run changes nothing

    org = Organization.objects.get(name="Mama Njeri Supermarket")
    assert Store.objects.for_org(org).count() == 2
    assert Membership.objects.for_org(org).count() == 3
    cashier = Membership.objects.for_org(org).get(user__email="cashier@demo.example")
    assert not cashier.all_stores
    assert [s.code for s in cashier.stores.all()] == ["WST"]

    assert Product.objects.for_org(org).count() == len(PRODUCTS) >= 50
    barcodes = list(ProductIdentifier.objects.for_org(org).values_list("value", flat=True))
    assert len(barcodes) == sum(1 for row in PRODUCTS if row[2])  # branded items
    assert all(gtin_check_digit_ok(code) for code in barcodes)
    for name in PRICE_CHANGES:
        product = Product.objects.for_org(org).get(name=name)
        assert ProductPriceHistory.objects.filter(product=product).count() == 2
    delivery = Product.objects.for_org(org).get(name="Delivery within 5km")
    assert not delivery.track_inventory

    assert Supplier.objects.for_org(org).count() == len(SUPPLIERS)
    supplied = {name for row in SUPPLIERS for name in row[7]}
    links = ProductSupplier.objects.for_org(org)
    assert links.filter(is_preferred=True).count() == len(supplied)
    assert links.count() == sum(len(row[7]) for row in SUPPLIERS)

    # Stock in both stores, with some items low or out.
    main = Store.objects.for_org(org).get(code="MAIN")
    levels = StockLevel.objects.for_org(org).filter(store=main)
    stocked = sum(1 for row in PRODUCTS if row[1] != "Services")
    assert levels.count() == stocked
    butter = levels.get(product__name="Butter 250g")
    assert butter.quantity_on_hand == STOCK_OVERRIDES["Butter 250g"]

    # Customers, one owing from before, one from a sample credit sale.
    accounts = CustomerAccount.objects.for_org(org)
    assert accounts.count() == len(CUSTOMERS)
    assert accounts.filter(balance__gt=0).count() == 3
    assert Sale.objects.for_org(org).count() == len(SALES)


def test_refuses_without_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_demo")
    assert not Organization.objects.exists()
