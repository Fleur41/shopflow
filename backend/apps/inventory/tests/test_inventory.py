import threading
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AppendOnlyError, AuditLog
from apps.catalog.models import (
    Product,
    ProductIdentifier,
    ProductPriceHistory,
    TaxRate,
    UnitOfMeasure,
)
from apps.inventory import services
from apps.inventory.models import InventoryMovement, StockLevel
from apps.organizations.models import Role
from apps.organizations.testing import (
    add_staff,
    add_store,
    client_for,
    context_for,
    create_business,
)

pytestmark = pytest.mark.django_db


def _business():
    registered = create_business()
    org = registered.organization
    pcs = UnitOfMeasure.objects.for_org(org).get(code="PCS")
    kg = UnitOfMeasure.objects.for_org(org).get(code="KG")
    vat = TaxRate.objects.for_org(org).get(name="VAT 16%")

    def product(name, sku, unit=pcs, **fields):
        return Product.objects.create(
            organization=org,
            sku=sku,
            name=name,
            unit=unit,
            tax_rate=vat,
            selling_price="100",
            **fields,
        )

    branch = add_store(org, "BR2", "Branch 2")
    cashier = add_staff(org, email="c@duka-a.example", stores=[registered.store])
    return SimpleNamespace(
        organization=org,
        store=registered.store,
        branch=branch,
        membership=registered.membership,
        owner=client_for(registered.user, org),
        manager=client_for(
            add_staff(
                org, email="m@duka-a.example", template=Role.Template.MANAGER, all_stores=True
            ).user,
            org,
        ),
        cashier=client_for(cashier.user, org),
        sugar=product("Sugar 1kg", "SUGAR", default_reorder_level=Decimal(5)),
        rice=product("Rice (loose)", "RICE", unit=kg),
        delivery=product("Delivery", "DELIVERY", track_inventory=False, etims_product_type="3"),
    )


@pytest.fixture
def biz(db):
    return _business()


def _url(biz, path="", store=None):
    return f"/api/v1/stores/{(store or biz.store).pk}/{path}"


def _post(client, url, body, key=None):
    return client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))


def _opening(biz, product, quantity, unit_cost=None, client=None):
    line = {"product_id": str(product.pk), "quantity": str(quantity)}
    if unit_cost is not None:
        line["unit_cost"] = str(unit_cost)
    return _post(
        client or biz.owner,
        _url(biz, "inventory/opening-balance/"),
        {"client_txn_id": str(uuid.uuid4()), "lines": [line]},
    )


def _adjust(biz, reason, lines, note="", client=None, txn=None, key=None):
    return _post(
        client or biz.owner,
        _url(biz, "inventory/adjustments/"),
        {
            "client_txn_id": txn or str(uuid.uuid4()),
            "reason_code": reason,
            "note": note,
            "lines": lines,
        },
        key=key,
    )


def _level(biz, product, store=None):
    return StockLevel.objects.for_org(biz.organization).get(
        store=store or biz.store, product=product
    )


# --- Opening balances and adjustments ------------------------------------------------


def test_opening_balance_sets_stock_and_cost_once(biz):
    response = _opening(biz, biz.sugar, 20, unit_cost="150")
    assert response.status_code == 201, response.json()
    assert response.json()["reason_code"] == "OPENING_BALANCE"
    level = _level(biz, biz.sugar)
    assert (level.quantity_on_hand, level.average_cost) == (Decimal(20), Decimal(150))
    movement = InventoryMovement.objects.for_org(biz.organization).get(product=biz.sugar)
    assert (movement.movement_type, movement.quantity_before, movement.quantity_after) == (
        "OPENING",
        0,
        20,
    )

    again = _opening(biz, biz.sugar, 5)
    assert again.status_code == 422
    assert again.json()["errors"][0]["code"] == "OPENING_BALANCE_EXISTS"


def test_a_count_records_the_difference(biz):
    _opening(biz, biz.sugar, 20)
    response = _adjust(
        biz, "COUNT_CORRECTION", [{"product_id": str(biz.sugar.pk), "counted_quantity": "17"}]
    )
    assert response.status_code == 201, response.json()
    assert response.json()["lines"][0]["quantity_delta"] == "-3.000"
    assert _level(biz, biz.sugar).quantity_on_hand == 17
    movements = InventoryMovement.objects.for_org(biz.organization).filter(product=biz.sugar)
    assert list(movements.order_by("seq").values_list("seq", "quantity_after")) == [
        (1, Decimal(20)),
        (2, Decimal(17)),
    ]
    assert AuditLog.objects.filter(action="stock_adjustment.created").count() == 2


def test_reasons_check_direction_and_other_needs_a_note(biz):
    _opening(biz, biz.sugar, 5)
    line = [{"product_id": str(biz.sugar.pk), "quantity_delta": "2"}]
    damaged = _adjust(biz, "DAMAGED", line)
    assert damaged.status_code == 400
    assert damaged.json()["errors"][0]["code"] == "WRONG_DIRECTION"

    other = _adjust(biz, "OTHER", line)
    assert other.status_code == 400
    assert other.json()["errors"][0]["pointer"] == "/note"

    found = _adjust(biz, "OTHER", line, note="Delivered twice")
    assert found.status_code == 201
    assert _level(biz, biz.sugar).quantity_on_hand == 7


def test_stock_cannot_go_negative_unless_allowed(biz):
    _opening(biz, biz.sugar, 2)
    line = [{"product_id": str(biz.sugar.pk), "quantity_delta": "-5"}]
    response = _adjust(biz, "DAMAGED", line)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "INSUFFICIENT_STOCK"
    assert body["errors"][0]["meta"] == {
        "product_id": str(biz.sugar.pk),
        "product_name": "Sugar 1kg",
        "available": "2",
        "requested": "5",
    }
    assert _level(biz, biz.sugar).quantity_on_hand == 2  # nothing written

    StockLevel.objects.for_org(biz.organization).filter(product=biz.sugar).update(
        allow_negative=True
    )
    assert _adjust(biz, "DAMAGED", line).status_code == 201
    assert _level(biz, biz.sugar).quantity_on_hand == -3


def test_whole_units_unless_the_unit_allows_fractions(biz):
    sugar = _adjust(biz, "FOUND", [{"product_id": str(biz.sugar.pk), "quantity_delta": "1.5"}])
    assert sugar.status_code == 400
    assert sugar.json()["errors"][0]["code"] == "FRACTION_NOT_ALLOWED"
    rice = _adjust(biz, "FOUND", [{"product_id": str(biz.rice.pk), "quantity_delta": "1.25"}])
    assert rice.status_code == 201
    assert _level(biz, biz.rice).quantity_on_hand == Decimal("1.25")


def test_services_and_duplicate_lines_are_refused(biz):
    service = _adjust(biz, "FOUND", [{"product_id": str(biz.delivery.pk), "quantity_delta": "1"}])
    assert service.status_code == 400
    line = {"product_id": str(biz.sugar.pk), "quantity_delta": "1"}
    assert _adjust(biz, "FOUND", [line, line]).status_code == 400


def test_adjustments_need_an_idempotency_key_and_replay(biz):
    body = {
        "client_txn_id": str(uuid.uuid4()),
        "reason_code": "FOUND",
        "lines": [{"product_id": str(biz.sugar.pk), "quantity_delta": "1"}],
    }
    missing = biz.owner.post(_url(biz, "inventory/adjustments/"), body, format="json")
    assert missing.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    key = str(uuid.uuid4())
    first = _post(biz.owner, _url(biz, "inventory/adjustments/"), body, key=key)
    replay = _post(biz.owner, _url(biz, "inventory/adjustments/"), body, key=key)
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == first.json()
    # The same transaction under a new key (e.g. a re-sent offline queue) changes nothing.
    again = _post(biz.owner, _url(biz, "inventory/adjustments/"), body)
    assert again.json()["id"] == first.json()["id"]
    assert _level(biz, biz.sugar).quantity_on_hand == 1


def test_cashiers_cannot_adjust_and_only_see_their_stores(biz):
    line = [{"product_id": str(biz.sugar.pk), "quantity_delta": "1"}]
    assert _adjust(biz, "FOUND", line, client=biz.cashier).status_code == 403
    assert biz.cashier.get(_url(biz, "inventory/")).status_code == 200
    assert biz.cashier.get(_url(biz, "inventory/", store=biz.branch)).status_code == 404


def test_movements_are_append_only(biz):
    _opening(biz, biz.sugar, 3)
    movement = InventoryMovement.objects.for_org(biz.organization).get()
    with pytest.raises(AppendOnlyError):
        movement.save()
    with pytest.raises(Exception, match="append-only"), transaction.atomic():
        InventoryMovement.unscoped.filter(pk=movement.pk).update(quantity=4)


# --- Lists, lookup and settings ----------------------------------------------------------


def test_inventory_list_shows_status_and_filters(biz):
    _opening(biz, biz.sugar, 3)  # at or below its reorder level of 5 → low
    _opening(biz, biz.rice, 0)
    rows = biz.owner.get(_url(biz, "inventory/")).json()["results"]
    by_name = {row["name"]: row for row in rows}
    assert set(by_name) == {"Sugar 1kg", "Rice (loose)"}  # services have no stock
    assert by_name["Sugar 1kg"]["stock_status"] == "low"
    assert by_name["Sugar 1kg"]["effective_reorder_level"] == "5.000"
    assert by_name["Rice (loose)"]["stock_status"] == "out"

    low = biz.owner.get(_url(biz, "inventory/?stock_status=low")).json()["results"]
    assert [row["name"] for row in low] == ["Sugar 1kg"]
    # Another store has none of it.
    branch = biz.owner.get(_url(biz, "inventory/", store=biz.branch)).json()["results"]
    assert {row["stock_status"] for row in branch} == {"out"}


def test_lookup_finds_barcodes_with_pack_size_then_skus(biz):
    ProductIdentifier.objects.create(
        organization=biz.organization, product=biz.sugar, value="6161000000017", is_primary=True
    )
    ProductIdentifier.objects.create(
        organization=biz.organization, product=biz.sugar, value="6161000000024", pack_quantity=12
    )
    _opening(biz, biz.sugar, 30)

    single = biz.cashier.get(_url(biz, "products/lookup/?code=6161000000017")).json()
    assert (single["name"], single["pack_quantity"], single["quantity_on_hand"]) == (
        "Sugar 1kg",
        "1.000",
        "30.000",
    )
    carton = biz.cashier.get(_url(biz, "products/lookup/?code=6161000000024")).json()
    assert carton["pack_quantity"] == "12.000"
    by_sku = biz.cashier.get(_url(biz, "products/lookup/?code=sugar")).json()
    assert by_sku["product_id"] == str(biz.sugar.pk)
    assert by_sku["tax_rate"] == "0.1600"
    service = biz.cashier.get(_url(biz, "products/lookup/?code=DELIVERY")).json()
    assert service["quantity_on_hand"] is None
    assert biz.cashier.get(_url(biz, "products/lookup/?code=nope")).status_code == 404


def test_store_settings_need_the_right_permission_per_field(biz):
    url = _url(biz, f"inventory/{biz.sugar.pk}/")
    row = biz.manager.get(url).json()
    assert row["version"] == 1

    levels = biz.manager.patch(url, {"version": 1, "reorder_level": "8"}, format="json")
    assert levels.status_code == 200, levels.json()
    assert levels.json()["reorder_level"] == "8.000"
    policy = biz.manager.patch(url, {"version": 2, "allow_negative": True}, format="json")
    assert policy.status_code == 403  # stores.manage_inventory_policy is the owner's
    assert (
        biz.cashier.patch(url, {"version": 2, "reorder_level": "1"}, format="json").status_code
        == 403
    )

    stale = biz.owner.patch(url, {"version": 1, "max_stock": "50"}, format="json")
    assert stale.json()["code"] == "STALE_VERSION"


def test_a_store_price_override_is_priced_at_the_till_and_kept_in_history(biz):
    url = _url(biz, f"inventory/{biz.sugar.pk}/")
    response = biz.owner.patch(url, {"version": 1, "selling_price_override": "95"}, format="json")
    assert response.json()["price"] == "95.0000"
    lookup = biz.owner.get(_url(biz, "products/lookup/?code=SUGAR")).json()
    assert lookup["price"] == "95.0000"
    other = biz.owner.get(_url(biz, "products/lookup/?code=SUGAR", store=biz.branch)).json()
    assert other["price"] == "100.0000"
    history = ProductPriceHistory.objects.get(product=biz.sugar, store=biz.store)
    assert (history.old_price, history.new_price) == (Decimal(100), Decimal(95))


def test_movement_history_filters_by_product(biz):
    _opening(biz, biz.sugar, 3)
    _opening(biz, biz.rice, 2)
    response = biz.owner.get(_url(biz, f"inventory/movements/?product={biz.sugar.pk}"))
    rows = response.json()["results"]
    assert [(r["product"]["name"], r["quantity"]) for r in rows] == [("Sugar 1kg", "3.000")]
    assert rows[0]["document"]["kind"] == "adjustment"
    assert rows[0]["document"]["reason_code"] == "OPENING_BALANCE"
    assert biz.cashier.get(_url(biz, "inventory/movements/")).status_code == 403


# --- Concurrency ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_removals_never_oversell():
    biz = _business()
    ctx = context_for(biz.membership)
    with transaction.atomic():
        services.create_adjustment(
            ctx,
            biz.store,
            client_txn_id=uuid.uuid4(),
            reason_code="OPENING_BALANCE",
            lines=[services.AdjustmentLineInput(product=biz.sugar, counted_quantity=Decimal(5))],
        )
    barrier = threading.Barrier(10)
    outcomes = []

    def remove_one():
        try:
            barrier.wait()
            services.create_adjustment(
                ctx,
                biz.store,
                client_txn_id=uuid.uuid4(),
                reason_code="DAMAGED",
                lines=[services.AdjustmentLineInput(product=biz.sugar, quantity_delta=Decimal(-1))],
                occurred_at=timezone.now(),
            )
            outcomes.append("ok")
        except services.InsufficientStock:
            outcomes.append("short")
        finally:
            connection.close()

    threads = [threading.Thread(target=remove_one) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["ok"] * 5 + ["short"] * 5
    level = _level(biz, biz.sugar)
    assert level.quantity_on_hand == 0
    movements = InventoryMovement.objects.for_org(biz.organization).filter(product=biz.sugar)
    assert sorted(movements.values_list("seq", flat=True)) == list(range(1, 7))
