import threading
from types import SimpleNamespace

import pytest
from django.db import IntegrityError, connection, transaction

from apps.audit.models import AuditLog
from apps.catalog import products
from apps.catalog.models import (
    Brand,
    Category,
    Product,
    ProductIdentifier,
    ProductPriceHistory,
    TaxRate,
    UnitOfMeasure,
)
from apps.organizations.catalog import CASHIER, ROLE_TEMPLATES
from apps.organizations.models import Role, RolePermission
from apps.organizations.testing import add_staff, client_for, context_for, create_business

pytestmark = pytest.mark.django_db

EAN13 = "5901234123457"
EAN8 = "96385074"
UPC_A = "036000291452"


@pytest.fixture
def lookups(biz):
    org = biz.organization
    return SimpleNamespace(
        pieces=UnitOfMeasure.objects.for_org(org).get(code="PCS"),
        kg=UnitOfMeasure.objects.for_org(org).get(code="KG"),
        vat=TaxRate.objects.for_org(org).get(name="VAT 16%"),
        exempt=TaxRate.objects.for_org(org).get(name="Exempt"),
    )


@pytest.fixture
def clerk_client(biz):
    """May add and edit products, but not change prices."""
    clerk_role = Role.objects.create(
        organization=biz.organization, name="Stock clerk", template=Role.Template.CUSTOM
    )
    RolePermission.objects.bulk_create(
        RolePermission(role=clerk_role, permission_id=code)
        for code in ROLE_TEMPLATES[CASHIER][2] | {"products.manage"}
    )
    clerk = add_staff(biz.organization, email="clerk@duka-a.example", role_obj=clerk_role)
    return client_for(clerk.user, biz.organization)


def _body(lookups, **fields):
    return {
        "name": "Milk 500ml",
        "unit": str(lookups.pieces.pk),
        "tax_rate": str(lookups.vat.pk),
        "selling_price": "60.00",
        **fields,
    }


def _create(client, lookups, **fields):
    response = client.post("/api/v1/products/", _body(lookups, **fields), format="json")
    assert response.status_code == 201, response.json()
    return response.json()


# --- Creating -----------------------------------------------------------------------------


def test_a_product_gets_a_generated_sku_its_first_price_and_an_audit_entry(
    owner_client, biz, lookups
):
    milk = _create(owner_client, lookups)
    bread = _create(owner_client, lookups, name="Bread")

    assert (milk["sku"], bread["sku"]) == ("P000001", "P000002")
    assert (milk["version"], milk["track_inventory"], milk["etims_product_type"]) == (1, True, "2")
    history = ProductPriceHistory.objects.get(product_id=milk["id"])
    assert (history.old_price, str(history.new_price), history.changed_by) == (
        None,
        "60.0000",
        biz.user,
    )
    assert AuditLog.objects.get(action="product.created", entity_id=milk["id"]).changes["sku"] == [
        None,
        "P000001",
    ]


def test_generated_skus_continue_after_the_highest_one(owner_client, lookups):
    _create(owner_client, lookups, sku="P000041")
    _create(owner_client, lookups, sku="SUGAR-1KG", name="Sugar")

    assert _create(owner_client, lookups, name="Salt")["sku"] == "P000042"


def test_products_can_be_created_with_their_barcodes(owner_client, lookups):
    milk = _create(
        owner_client,
        lookups,
        identifiers=[{"value": f" {EAN13} "}, {"value": UPC_A, "pack_quantity": "12"}],
    )

    codes = [(i["value"], i["pack_quantity"], i["is_primary"]) for i in milk["identifiers"]]
    assert sorted(codes) == [(UPC_A, "12.000", False), (EAN13, "1.000", True)]


@pytest.mark.parametrize("value", ["5901234123458", "96385075", "036000291453"])
def test_a_mistyped_barcode_is_caught_by_its_check_digit(owner_client, lookups, value):
    response = owner_client.post(
        "/api/v1/products/", _body(lookups, identifiers=[{"value": value}]), format="json"
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/identifiers/0/value"


def test_codes_without_a_check_digit_are_accepted(owner_client, lookups):
    milk = _create(
        owner_client,
        lookups,
        identifiers=[{"value": "ABC-123"}, {"value": "12345", "kind": "ALIAS"}, {"value": EAN8}],
    )

    assert len(milk["identifiers"]) == 3


def test_services_never_track_stock(owner_client, lookups):
    delivery = _create(owner_client, lookups, name="Delivery", etims_product_type="3")
    assert delivery["track_inventory"] is False

    response = owner_client.post(
        "/api/v1/products/",
        _body(lookups, name="Repair", etims_product_type="3", track_inventory=True),
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/track_inventory"


def test_deactivated_lookups_cannot_be_chosen_for_new_products(owner_client, lookups):
    TaxRate.unscoped.filter(pk=lookups.exempt.pk).update(is_active=False)

    response = owner_client.post(
        "/api/v1/products/", _body(lookups, tax_rate=str(lookups.exempt.pk)), format="json"
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/tax_rate"


def test_another_businesses_lookups_look_like_they_dont_exist(owner_client, lookups):
    other = create_business(email="owner@duka-b.example", name="Duka B")
    their_unit = UnitOfMeasure.objects.for_org(other.organization).get(code="PCS")

    response = owner_client.post(
        "/api/v1/products/", _body(lookups, unit=str(their_unit.pk)), format="json"
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "DOES_NOT_EXIST"


# --- Codes are unique across SKUs and identifiers ------------------------------------------


def test_one_code_finds_one_product(owner_client, lookups):
    _create(owner_client, lookups, sku="MILK-500", identifiers=[{"value": EAN13}])

    cases = [
        (_body(lookups, sku="milk-500"), "/sku"),  # same SKU, ignoring case
        (_body(lookups, sku=EAN13), "/sku"),  # a SKU equal to another product's barcode
        (_body(lookups, identifiers=[{"value": EAN13}]), "/identifiers/0/value"),
        (_body(lookups, identifiers=[{"value": "MILK-500"}]), "/identifiers/0/value"),
    ]
    for body, pointer in cases:
        response = owner_client.post("/api/v1/products/", body, format="json")
        assert response.status_code == 400, body
        assert response.json()["errors"][0]["pointer"] == pointer
    assert Product.unscoped.count() == 1


def test_the_same_code_cannot_be_added_twice_to_one_product(owner_client, lookups):
    milk = _create(owner_client, lookups, identifiers=[{"value": EAN13}])

    response = owner_client.post(
        f"/api/v1/products/{milk['id']}/identifiers/", {"value": EAN13}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "CODE_IN_USE"


# --- Updating and prices --------------------------------------------------------------------


def test_a_price_change_is_audited_and_kept_in_price_history(owner_client, lookups):
    milk = _create(owner_client, lookups)

    response = owner_client.patch(
        f"/api/v1/products/{milk['id']}/", {"selling_price": "65.00", "version": 1}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    history = owner_client.get(f"/api/v1/products/{milk['id']}/price-history/").json()["results"]
    assert [(h["old_price"], h["new_price"]) for h in history] == [
        ("60.0000", "65.0000"),
        (None, "60.0000"),
    ]
    assert AuditLog.objects.get(action="product.updated").changes == {
        "selling_price": ["60.0000", "65.0000"]
    }


def test_changing_a_price_needs_its_own_permission(owner_client, clerk_client, lookups):
    milk = _create(owner_client, lookups)
    url = f"/api/v1/products/{milk['id']}/"

    refused = clerk_client.patch(url, {"selling_price": "1.00", "version": 1}, format="json")
    assert refused.status_code == 403
    assert refused.json()["errors"][0]["meta"]["permission"] == "products.change_price"

    renamed = clerk_client.patch(
        url, {"name": "Milk 0.5L", "selling_price": "60.00", "version": 1}, format="json"
    )
    assert renamed.status_code == 200  # the same price isn't a price change
    assert ProductPriceHistory.objects.filter(product_id=milk["id"]).count() == 1


def test_changing_a_price_needs_two_step_verification(owner_client, biz, lookups):
    milk = _create(owner_client, lookups)
    unverified = client_for(biz.user, biz.organization, mfa=False)

    response = unverified.patch(
        f"/api/v1/products/{milk['id']}/", {"selling_price": "70.00", "version": 1}, format="json"
    )

    assert response.status_code == 403
    assert response.json()["code"] == "MFA_ENROLLMENT_REQUIRED"


def test_a_product_keeps_a_lookup_that_was_deactivated_later(owner_client, lookups):
    milk = _create(owner_client, lookups, tax_rate=str(lookups.exempt.pk))
    TaxRate.unscoped.filter(pk=lookups.exempt.pk).update(is_active=False)

    response = owner_client.patch(
        f"/api/v1/products/{milk['id']}/",
        {"name": "Milk 0.5L", "tax_rate": str(lookups.exempt.pk), "version": 1},
        format="json",
    )

    assert response.status_code == 200


def test_every_change_moves_the_sync_cursor(owner_client, lookups):
    milk = _create(owner_client, lookups, identifiers=[{"value": EAN13}])
    before = Product.unscoped.get(pk=milk["id"]).row_version

    owner_client.patch(f"/api/v1/products/{milk['id']}/", {"name": "Milk", "version": 1})

    assert before > 0
    assert Product.unscoped.get(pk=milk["id"]).row_version > before
    assert ProductIdentifier.unscoped.get().row_version > 0


def test_price_history_cannot_be_rewritten(owner_client, lookups):
    _create(owner_client, lookups)

    with (
        pytest.raises(IntegrityError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("UPDATE catalog_productpricehistory SET new_price = 0")


# --- Identifiers ----------------------------------------------------------------------------


def test_identifiers_can_be_added_made_primary_and_removed(owner_client, lookups):
    milk = _create(owner_client, lookups, identifiers=[{"value": EAN13}])
    url = f"/api/v1/products/{milk['id']}/identifiers/"

    carton = owner_client.post(url, {"value": UPC_A, "pack_quantity": "12", "is_primary": True})
    assert carton.status_code == 201
    listed = owner_client.get(url).json()
    assert {i["value"]: i["is_primary"] for i in listed} == {EAN13: False, UPC_A: True}

    assert owner_client.delete(f"{url}{carton.json()['id']}/").status_code == 204
    assert [(i["value"], i["is_primary"]) for i in owner_client.get(url).json()] == [(EAN13, True)]
    assert list(
        AuditLog.objects.filter(entity_id=milk["id"], action__startswith="product_identifier")
        .order_by("occurred_at")
        .values_list("action", flat=True)
    ) == [
        "product_identifier.added",
        "product_identifier.added",
        "product_identifier.removed",
    ]


def test_cashiers_can_look_up_products_but_not_change_them(owner_client, cashier_client, lookups):
    milk = _create(owner_client, lookups, identifiers=[{"value": EAN13}])
    url = f"/api/v1/products/{milk['id']}/"

    assert cashier_client.get(url).status_code == 200
    assert cashier_client.get(f"{url}identifiers/").status_code == 200
    assert cashier_client.get(f"{url}price-history/").status_code == 200
    assert cashier_client.post(f"{url}identifiers/", {"value": EAN8}).status_code == 403
    assert cashier_client.patch(url, {"name": "X", "version": 1}).status_code == 403
    assert (
        cashier_client.post("/api/v1/products/", _body(lookups), format="json").status_code == 403
    )


# --- Searching ------------------------------------------------------------------------------


def test_products_are_found_by_name_typo_sku_or_barcode(owner_client, biz, lookups):
    drinks = Category.objects.create(organization=biz.organization, name="Drinks")
    brand = Brand.objects.create(organization=biz.organization, name="Brookside")
    _create(
        owner_client,
        lookups,
        name="Brookside Milk 500ml",
        sku="MILK-500",
        category=str(drinks.pk),
        brand=str(brand.pk),
        identifiers=[{"value": EAN13}],
    )
    _create(owner_client, lookups, name="Sugar 1kg", unit=str(lookups.kg.pk))
    _create(owner_client, lookups, name="Old soap", is_active=False)

    def names(query):
        response = owner_client.get(f"/api/v1/products/?{query}")
        assert response.status_code == 200, response.json()
        return [p["name"] for p in response.json()["results"]]

    assert names("") == ["Brookside Milk 500ml", "Old soap", "Sugar 1kg"]
    assert names("search=milk") == ["Brookside Milk 500ml"]
    assert names("search=suger") == ["Sugar 1kg"]  # a typo still finds it
    assert names("search=milk-500") == ["Brookside Milk 500ml"]
    assert names(f"search={EAN13}") == ["Brookside Milk 500ml"]
    assert names(f"barcode={EAN13}") == ["Brookside Milk 500ml"]
    assert names("sku=milk-500") == ["Brookside Milk 500ml"]
    assert names(f"category={drinks.pk}") == ["Brookside Milk 500ml"]
    assert names(f"brand={brand.pk}") == ["Brookside Milk 500ml"]
    assert names("is_active=false") == ["Old soap"]
    assert owner_client.get("/api/v1/products/?category=drinks").status_code == 400


# --- Concurrency ----------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_products_created_at_the_same_time_get_different_skus():
    business = create_business()
    ctx = context_for(business.membership)
    org = business.organization
    unit = UnitOfMeasure.objects.for_org(org).get(code="PCS")
    tax_rate = TaxRate.objects.for_org(org).get(name="VAT 16%")
    barrier = threading.Barrier(4)
    errors: list[BaseException] = []

    def create(name: str) -> None:
        try:
            barrier.wait()
            products.create_product(
                ctx, name=name, unit=unit, tax_rate=tax_rate, selling_price="1.00"
            )
        except BaseException as exc:  # reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=create, args=(f"Item {i}",)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    skus = sorted(Product.objects.for_org(org).values_list("sku", flat=True))
    assert skus == ["P000001", "P000002", "P000003", "P000004"]
