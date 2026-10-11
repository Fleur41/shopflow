from types import SimpleNamespace

import pytest

from apps.audit.models import AuditLog
from apps.catalog.models import Product, TaxRate, UnitOfMeasure
from apps.organizations.models import Role
from apps.organizations.testing import add_staff, client_for, create_business
from apps.suppliers.models import ProductSupplier, Supplier, SupplierContact

pytestmark = pytest.mark.django_db


@pytest.fixture
def biz(db):
    registered = create_business()
    org = registered.organization
    unit = UnitOfMeasure.objects.for_org(org).get(code="PCS")
    vat = TaxRate.objects.for_org(org).get(name="VAT 16%")

    def product(name, sku):
        return Product.objects.create(
            organization=org, sku=sku, name=name, unit=unit, tax_rate=vat, selling_price="100"
        )

    return SimpleNamespace(
        organization=org,
        owner=client_for(registered.user, org),
        manager=client_for(
            add_staff(
                org, email="m@duka-a.example", template=Role.Template.MANAGER, all_stores=True
            ).user,
            org,
        ),
        cashier=client_for(
            add_staff(org, email="c@duka-a.example", stores=[registered.store]).user, org
        ),
        sugar=product("Sugar 1kg", "SUGAR"),
        salt=product("Salt 500g", "SALT"),
    )


def _create(client, **body):
    response = client.post("/api/v1/suppliers/", {"name": "Mumias Sugar", **body}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


# --- Suppliers --------------------------------------------------------------------------


def test_a_supplier_gets_a_code_and_tidy_contact_details(biz):
    mumias = _create(
        biz.owner, kra_pin="p051234567x", phone="+254 712 345-678", payment_terms_days=30
    )
    kensalt = _create(biz.owner, name="Kensalt")

    assert (mumias["code"], kensalt["code"]) == ("S00001", "S00002")
    assert (mumias["kra_pin"], mumias["phone"], mumias["payment_terms_days"]) == (
        "P051234567X",
        "+254712345678",
        30,
    )
    assert AuditLog.objects.filter(action="supplier.created", entity_id=mumias["id"]).exists()


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"kra_pin": "12345"}, "kra_pin"),
        ({"phone": "call me"}, "phone"),
        ({"email": "not-an-email"}, "email"),
        ({"payment_terms_days": 400}, "payment_terms_days"),
        ({"name": "mumias sugar"}, "name"),  # taken, ignoring case
    ],
)
def test_supplier_details_are_checked(biz, body, field):
    _create(biz.owner)

    response = biz.owner.post("/api/v1/suppliers/", {"name": "Other", **body}, format="json")

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == f"/{field}"


def test_suppliers_are_edited_with_a_version_and_keep_their_code(biz):
    mumias = _create(biz.owner)
    url = f"/api/v1/suppliers/{mumias['id']}/"

    response = biz.owner.patch(
        url, {"payment_terms_days": 14, "code": "X", "version": 1}, format="json"
    )

    assert response.status_code == 200
    assert (response.json()["payment_terms_days"], response.json()["code"]) == (14, "S00001")
    assert biz.owner.patch(url, {"name": "Stale", "version": 1}, format="json").status_code == 409


def test_suppliers_are_searchable(biz):
    _create(biz.owner, phone="0712345678")
    _create(biz.owner, name="Kensalt", kra_pin="P000000001A")

    def names(query):
        return [s["name"] for s in biz.owner.get(f"/api/v1/suppliers/?{query}").json()["results"]]

    assert names("") == ["Kensalt", "Mumias Sugar"]
    assert names("search=mumias") == ["Mumias Sugar"]
    assert names("search=0712") == ["Mumias Sugar"]
    assert names("search=P000000001A") == ["Kensalt"]


def test_managers_run_suppliers_and_cashiers_dont_see_them(biz):
    assert _create(biz.manager)["code"] == "S00001"
    assert biz.cashier.get("/api/v1/suppliers/").status_code == 403


# --- Contacts ---------------------------------------------------------------------------


def test_the_first_contact_is_primary_and_primary_can_move(biz):
    mumias = _create(biz.owner)
    url = f"/api/v1/suppliers/{mumias['id']}/contacts/"

    wanjiku = biz.owner.post(
        url, {"name": "Wanjiku", "role_title": "Sales", "phone": "0712 000 111"}
    ).json()
    otieno = biz.owner.post(url, {"name": "Otieno", "is_primary": True}).json()

    listed = biz.owner.get(url).json()
    assert [(c["name"], c["is_primary"]) for c in listed] == [("Otieno", True), ("Wanjiku", False)]
    assert wanjiku["phone"] == "0712000111"

    # Unticking the only primary is ignored: choose another instead.
    biz.owner.patch(f"{url}{otieno['id']}/", {"is_primary": False}, format="json")
    assert SupplierContact.objects.for_org(biz.organization).get(pk=otieno["id"]).is_primary

    assert biz.owner.delete(f"{url}{otieno['id']}/").status_code == 204
    assert [(c["name"], c["is_primary"]) for c in biz.owner.get(url).json()] == [("Wanjiku", True)]
    assert {
        "supplier.contact_added",
        "supplier.contact_removed",
    } <= set(AuditLog.objects.values_list("action", flat=True))


# --- Product links ------------------------------------------------------------------------


def test_linking_products_and_choosing_the_preferred_supplier(biz):
    mumias = _create(biz.owner)
    kabras = _create(biz.owner, name="Kabras Sugar")

    first = biz.owner.post(
        f"/api/v1/suppliers/{mumias['id']}/products/",
        {
            "product": str(biz.sugar.pk),
            "supplier_sku": "MS-1KG",
            "min_order_qty": "50",
            "lead_time_days": 3,
        },
        format="json",
    )
    assert first.status_code == 201, first.json()
    assert (first.json()["is_preferred"], first.json()["product_name"]) == (True, "Sugar 1kg")

    second = biz.owner.post(
        f"/api/v1/products/{biz.sugar.pk}/suppliers/",
        {"supplier": kabras["id"], "is_preferred": True},
        format="json",
    )
    assert second.status_code == 201

    links = biz.owner.get(f"/api/v1/products/{biz.sugar.pk}/suppliers/").json()
    assert [(link["supplier_name"], link["is_preferred"]) for link in links] == [
        ("Kabras Sugar", True),
        ("Mumias Sugar", False),
    ]


def test_a_supplier_is_linked_to_a_product_once(biz):
    mumias = _create(biz.owner)
    url = f"/api/v1/suppliers/{mumias['id']}/products/"
    biz.owner.post(url, {"product": str(biz.sugar.pk)}, format="json")

    again = biz.owner.post(url, {"product": str(biz.sugar.pk)}, format="json")

    assert again.status_code == 400
    assert again.json()["errors"][0]["code"] == "ALREADY_LINKED"


@pytest.mark.parametrize(
    ("body", "field"),
    [({"min_order_qty": "0"}, "min_order_qty"), ({"lead_time_days": 500}, "lead_time_days")],
)
def test_order_terms_are_checked(biz, body, field):
    mumias = _create(biz.owner)

    response = biz.owner.post(
        f"/api/v1/suppliers/{mumias['id']}/products/",
        {"product": str(biz.sugar.pk), **body},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == f"/{field}"


def test_a_link_is_edited_and_removed_but_never_moved(biz):
    mumias = _create(biz.owner)
    link = biz.owner.post(
        f"/api/v1/suppliers/{mumias['id']}/products/", {"product": str(biz.sugar.pk)}, format="json"
    ).json()
    url = f"/api/v1/product-suppliers/{link['id']}/"

    edited = biz.owner.patch(
        url, {"supplier_sku": "MS-1", "product": str(biz.salt.pk)}, format="json"
    )

    assert edited.status_code == 200
    assert (edited.json()["supplier_sku"], edited.json()["product"]) == ("MS-1", str(biz.sugar.pk))
    assert AuditLog.objects.get(action="supplier.product_link_updated").changes == {
        "product": [str(biz.sugar.pk), str(biz.sugar.pk)],
        "supplier_sku": ["", "MS-1"],
    }
    assert biz.owner.delete(url).status_code == 204
    assert not ProductSupplier.objects.for_org(biz.organization).exists()


def test_deactivated_suppliers_cannot_be_linked(biz):
    mumias = _create(biz.owner)
    Supplier.unscoped.filter(pk=mumias["id"]).update(is_active=False)

    response = biz.owner.post(
        f"/api/v1/products/{biz.sugar.pk}/suppliers/", {"supplier": mumias["id"]}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/supplier"


def test_products_can_be_listed_by_supplier(biz):
    mumias = _create(biz.owner)
    biz.owner.post(
        f"/api/v1/suppliers/{mumias['id']}/products/", {"product": str(biz.sugar.pk)}, format="json"
    )

    names = [
        p["name"]
        for p in biz.owner.get(f"/api/v1/products/?supplier={mumias['id']}").json()["results"]
    ]

    assert names == ["Sugar 1kg"]


def test_editing_a_contact_is_audited(biz):
    mumias = _create(biz.owner)
    url = f"/api/v1/suppliers/{mumias['id']}/contacts/"
    wanjiku = biz.owner.post(url, {"name": "Wanjiku"}).json()
    otieno = biz.owner.post(url, {"name": "Otieno"}).json()

    renamed = biz.owner.patch(
        f"{url}{otieno['id']}/", {"role_title": "Accounts", "is_primary": True}, format="json"
    )

    assert renamed.status_code == 200
    assert [(c["name"], c["is_primary"]) for c in biz.owner.get(url).json()] == [
        ("Otieno", True),
        ("Wanjiku", False),
    ]
    assert AuditLog.objects.get(action="supplier.contact_updated").changes == {
        "role_title": ["", "Accounts"],
        "is_primary": [False, True],
    }
    assert wanjiku["is_primary"] is True  # was primary until Otieno took over


def test_making_another_supplier_preferred_moves_the_star(biz):
    mumias = _create(biz.owner)
    kabras = _create(biz.owner, name="Kabras Sugar")
    biz.owner.post(
        f"/api/v1/products/{biz.sugar.pk}/suppliers/", {"supplier": mumias["id"]}, format="json"
    )
    kabras_link = biz.owner.post(
        f"/api/v1/products/{biz.sugar.pk}/suppliers/", {"supplier": kabras["id"]}, format="json"
    ).json()
    assert kabras_link["is_preferred"] is False

    biz.owner.patch(
        f"/api/v1/product-suppliers/{kabras_link['id']}/", {"is_preferred": True}, format="json"
    )

    preferred = ProductSupplier.objects.for_org(biz.organization).get(is_preferred=True)
    assert (
        preferred.supplier_id
        == Supplier.objects.for_org(biz.organization).get(code=kabras["code"]).pk
    )
