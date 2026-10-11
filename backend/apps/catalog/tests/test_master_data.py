import pytest

from apps.audit.models import AuditLog
from apps.catalog.models import Brand, Category, TaxRate, UnitOfMeasure
from apps.common.errors import ApplicationError
from apps.organizations import master_data
from apps.organizations.testing import client_for, create_business

pytestmark = pytest.mark.django_db


def _create(client, path, body):
    response = client.post(f"/api/v1/{path}/", body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


# --- Creating --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body", "action"),
    [
        ("categories", {"name": "Drinks"}, "category.created"),
        ("brands", {"name": "Kensalt"}, "brand.created"),
        ("units", {"code": "kg", "name": "Kilogram", "allows_fraction": True}, "unit.created"),
        ("tax-rates", {"name": "VAT 16%", "rate": "0.16"}, "tax_rate.created"),
    ],
)
def test_owner_creates_entries_and_each_is_audited(owner_client, biz, path, body, action):
    created = _create(owner_client, path, body)

    assert (created["is_active"], created["version"]) == (True, 1)
    entry = AuditLog.objects.get(action=action, entity_id=created["id"])
    assert entry.actor == biz.user
    assert entry.changes == {field: [None, created[field]] for field in body}


def test_unit_codes_are_upper_cased_and_must_be_short_codes(owner_client):
    assert _create(owner_client, "units", {"code": " pcs ", "name": "Pieces"})["code"] == "PCS"

    response = owner_client.post("/api/v1/units/", {"code": "per-kg", "name": "X"})
    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/code"


@pytest.mark.parametrize("rate", ["-0.01", "1", "1.5"])
def test_tax_rates_are_fractions_below_one(owner_client, rate):
    response = owner_client.post("/api/v1/tax-rates/", {"name": "Bad", "rate": rate})

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/rate"


# --- Uniqueness --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "first", "second", "field"),
    [
        ("brands", {"name": "Kensalt"}, {"name": "KENSALT"}, "name"),
        ("units", {"code": "KG", "name": "Kilogram"}, {"code": "kg", "name": "Kilo"}, "code"),
        ("tax-rates", {"name": "VAT", "rate": "0.16"}, {"name": "vat", "rate": "0.08"}, "name"),
        ("categories", {"name": "Drinks"}, {"name": "drinks"}, "name"),
    ],
)
def test_names_and_codes_are_unique_ignoring_case(owner_client, path, first, second, field):
    _create(owner_client, path, first)

    response = owner_client.post(f"/api/v1/{path}/", second, format="json")

    assert response.status_code == 400
    error = response.json()["errors"][0]
    assert (error["pointer"], error["code"]) == (f"/{field}", "TAKEN")


def test_sibling_categories_need_distinct_names_but_cousins_may_share(owner_client):
    drinks = _create(owner_client, "categories", {"name": "Drinks"})
    food = _create(owner_client, "categories", {"name": "Food"})
    _create(owner_client, "categories", {"name": "Other", "parent": drinks["id"]})
    _create(owner_client, "categories", {"name": "Other", "parent": food["id"]})

    response = owner_client.post(
        "/api/v1/categories/", {"name": "OTHER", "parent": drinks["id"]}, format="json"
    )
    assert response.status_code == 400


def test_another_business_may_reuse_the_same_names(owner_client):
    other = create_business(email="owner@duka-b.example", name="Duka B")
    _create(owner_client, "brands", {"name": "Kensalt"})

    _create(client_for(other.user, other.organization), "brands", {"name": "Kensalt"})


def test_a_duplicate_that_slips_past_validation_is_still_refused_cleanly(owner_ctx):
    """Two requests racing with the same name: the database constraint decides."""
    master_data.create_entry(owner_ctx, Brand, name="Kensalt")

    with pytest.raises(ApplicationError) as raised:
        master_data.create_entry(owner_ctx, Brand, name="kensalt")

    assert (raised.value.status_code, raised.value.code) == (400, "VALIDATION_ERROR")
    assert raised.value.errors[0]["pointer"] == "/name"
    assert Brand.objects.for_org(owner_ctx.organization).count() == 1


# --- Updating ------------------------------------------------------------------------------


def test_updates_need_the_current_version_and_bump_it(owner_client):
    brand = _create(owner_client, "brands", {"name": "Kensalt"})
    url = f"/api/v1/brands/{brand['id']}/"

    assert owner_client.patch(url, {"name": "Kensalt Ltd"}).status_code == 400  # no version
    response = owner_client.patch(url, {"name": "Kensalt Ltd", "version": 1})
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert AuditLog.objects.get(action="brand.updated").changes == {
        "name": ["Kensalt", "Kensalt Ltd"]
    }

    stale = owner_client.patch(url, {"name": "Overwritten", "version": 1})
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_VERSION"
    assert Brand.unscoped.get(pk=brand["id"]).name == "Kensalt Ltd"


def test_an_update_that_changes_nothing_keeps_the_version_and_is_not_audited(owner_client):
    brand = _create(owner_client, "brands", {"name": "Kensalt"})

    response = owner_client.patch(
        f"/api/v1/brands/{brand['id']}/", {"name": "Kensalt", "version": 1}
    )

    assert response.json()["version"] == 1
    assert not AuditLog.objects.filter(action="brand.updated").exists()


def test_entries_are_deactivated_not_deleted(owner_client):
    unit = _create(owner_client, "units", {"code": "PCS", "name": "Pieces"})
    url = f"/api/v1/units/{unit['id']}/"

    assert owner_client.delete(url).status_code == 403  # no such action: fails closed
    response = owner_client.patch(url, {"is_active": False, "version": 1})
    assert response.json()["is_active"] is False
    assert UnitOfMeasure.unscoped.filter(pk=unit["id"]).exists()


def test_a_tax_rates_rate_cannot_be_changed_after_creation(owner_client):
    vat = _create(owner_client, "tax-rates", {"name": "VAT", "rate": "0.16"})

    response = owner_client.patch(
        f"/api/v1/tax-rates/{vat['id']}/", {"name": "VAT standard", "rate": "0.08", "version": 1}
    )

    assert response.status_code == 200
    assert (response.json()["name"], response.json()["rate"]) == ("VAT standard", "0.1600")
    assert str(TaxRate.unscoped.get(pk=vat["id"]).rate) == "0.1600"


def test_renaming_into_an_existing_name_is_refused(owner_client):
    _create(owner_client, "brands", {"name": "Kensalt"})
    other = _create(owner_client, "brands", {"name": "Other"})

    response = owner_client.patch(
        f"/api/v1/brands/{other['id']}/", {"name": "kensalt", "version": 1}
    )

    assert response.status_code == 400


# --- Category tree -------------------------------------------------------------------------


def test_a_category_cannot_move_inside_itself_or_its_subcategories(owner_client):
    drinks = _create(owner_client, "categories", {"name": "Drinks"})
    soda = _create(owner_client, "categories", {"name": "Soda", "parent": drinks["id"]})
    diet = _create(owner_client, "categories", {"name": "Diet", "parent": soda["id"]})
    url = f"/api/v1/categories/{drinks['id']}/"

    for parent in (drinks, soda, diet):
        response = owner_client.patch(url, {"parent": parent["id"], "version": 1}, format="json")
        assert response.status_code == 422
        assert response.json()["code"] == "CATEGORY_CYCLE"
    assert Category.unscoped.get(pk=drinks["id"]).parent_id is None


def test_a_category_can_move_to_another_branch_or_to_the_top(owner_client):
    drinks = _create(owner_client, "categories", {"name": "Drinks"})
    food = _create(owner_client, "categories", {"name": "Food"})
    soda = _create(owner_client, "categories", {"name": "Soda", "parent": drinks["id"]})
    url = f"/api/v1/categories/{soda['id']}/"

    moved = owner_client.patch(url, {"parent": food["id"], "version": 1}, format="json")
    assert moved.json()["parent"] == food["id"]
    assert AuditLog.objects.get(action="category.updated").changes == {
        "parent": [drinks["id"], food["id"]]
    }

    top = owner_client.patch(url, {"parent": None, "version": 2}, format="json")
    assert top.json()["parent"] is None


def test_new_subcategories_need_an_active_parent(owner_client):
    drinks = _create(owner_client, "categories", {"name": "Drinks"})
    owner_client.patch(
        f"/api/v1/categories/{drinks['id']}/", {"is_active": False, "version": 1}, format="json"
    )

    response = owner_client.post(
        "/api/v1/categories/", {"name": "Soda", "parent": drinks["id"]}, format="json"
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/parent"


# --- Listing ------------------------------------------------------------------------------


def test_lists_filter_by_active_state_search_and_parent(owner_client):
    drinks = _create(owner_client, "categories", {"name": "Drinks"})
    _create(owner_client, "categories", {"name": "Soda", "parent": drinks["id"]})
    old = _create(owner_client, "categories", {"name": "Old stock"})
    owner_client.patch(
        f"/api/v1/categories/{old['id']}/", {"is_active": False, "version": 1}, format="json"
    )

    def names(query):
        response = owner_client.get(f"/api/v1/categories/?{query}")
        assert response.status_code == 200, response.json()
        return [c["name"] for c in response.json()["results"]]

    assert names("") == ["Drinks", "Old stock", "Soda"]
    assert names("is_active=true") == ["Drinks", "Soda"]
    assert names("is_active=false") == ["Old stock"]
    assert names("search=SOD") == ["Soda"]
    assert names("parent=none") == ["Drinks", "Old stock"]
    assert names(f"parent={drinks['id']}") == ["Soda"]
    assert owner_client.get("/api/v1/categories/?parent=nope").status_code == 400
    assert owner_client.get("/api/v1/categories/?is_active=maybe").status_code == 400


def test_units_are_listed_by_code_and_searchable_by_code_or_name(owner_client):
    _create(owner_client, "units", {"code": "PCS", "name": "Pieces"})
    _create(owner_client, "units", {"code": "KG", "name": "Kilogram"})

    listed = owner_client.get("/api/v1/units/").json()["results"]
    assert [u["code"] for u in listed] == ["KG", "PCS"]
    searched = owner_client.get("/api/v1/units/?search=piece").json()["results"]
    assert [u["code"] for u in searched] == ["PCS"]


# --- Permissions --------------------------------------------------------------------------


def test_cashiers_can_read_the_catalog_but_not_change_it(owner_client, cashier_client):
    brand = _create(owner_client, "brands", {"name": "Kensalt"})

    assert cashier_client.get("/api/v1/brands/").status_code == 200
    assert cashier_client.get(f"/api/v1/brands/{brand['id']}/").status_code == 200
    assert cashier_client.post("/api/v1/brands/", {"name": "New"}).status_code == 403
    assert (
        cashier_client.patch(
            f"/api/v1/brands/{brand['id']}/", {"name": "X", "version": 1}
        ).status_code
        == 403
    )


# --- eTIMS codes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "tax_type", "ok"),
    [("0.16", "B", True), ("0", "A", True), ("0", "C", True), ("0.08", "E", True),
     ("0.16", "E", False), ("0", "B", False)],
)  # fmt: skip
def test_a_tax_type_must_match_its_rate(owner_client, rate, tax_type, ok):
    response = owner_client.post(
        "/api/v1/tax-rates/", {"name": "VAT", "rate": rate, "etims_tax_type": tax_type}
    )

    assert response.status_code == (201 if ok else 400)
    if not ok:
        assert response.json()["errors"][0]["pointer"] == "/etims_tax_type"


def test_the_tax_type_can_be_set_later_and_is_checked_against_the_fixed_rate(owner_client):
    vat = _create(owner_client, "tax-rates", {"name": "VAT", "rate": "0.16"})
    url = f"/api/v1/tax-rates/{vat['id']}/"

    assert owner_client.patch(url, {"etims_tax_type": "A", "version": 1}).status_code == 400
    response = owner_client.patch(url, {"etims_tax_type": "B", "version": 1})
    assert response.json()["etims_tax_type"] == "B"


def test_units_take_a_kra_quantity_unit_from_the_list(owner_client):
    kg = _create(
        owner_client, "units", {"code": "KG", "name": "Kilogram", "etims_quantity_unit": "KG"}
    )
    assert kg["etims_quantity_unit"] == "KG"

    response = owner_client.post(
        "/api/v1/units/", {"code": "BOX", "name": "Box", "etims_quantity_unit": "BOXES"}
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/etims_quantity_unit"
