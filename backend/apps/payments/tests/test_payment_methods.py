from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.audit.models import AuditLog
from apps.common.errors import ApplicationError
from apps.organizations.testing import add_staff, client_for, context_for, create_business
from apps.payments.models import PaymentMethod
from apps.payments.providers import PaymentRequest, PaymentStatus, get_provider
from apps.payments.services import create_payment_method

pytestmark = pytest.mark.django_db


@pytest.fixture
def biz(db):
    registered = create_business()
    return SimpleNamespace(
        organization=registered.organization,
        owner_ctx=context_for(registered.membership),
        owner=client_for(registered.user, registered.organization),
        cashier=client_for(
            add_staff(
                registered.organization,
                email="cashier@duka-a.example",
                stores=[registered.store],
            ).user,
            registered.organization,
        ),
    )


def _create(client, body):
    response = client.post("/api/v1/payment-methods/", body, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_new_businesses_start_with_cash_mpesa_and_card_in_till_order(biz):
    methods = biz.cashier.get("/api/v1/payment-methods/").json()["results"]

    assert [(m["code"], m["kind"], m["etims_payment_type"]) for m in methods] == [
        ("CASH", "CASH", "01"),
        ("MPESA", "MOBILE_MONEY", "06"),
        ("CARD", "CARD", "05"),
    ]
    assert [m["requires_reference"] for m in methods] == [False, True, False]
    assert {m["provider"] for m in methods} == {"MANUAL"}
    assert (
        AuditLog.objects.filter(
            organization=biz.organization, action="payment_method.created"
        ).count()
        == 3
    )


def test_owner_adds_a_method_with_defaults_from_its_kind(biz):
    created = _create(
        biz.owner, {"code": " bank ", "name": "Bank transfer", "kind": "BANK_TRANSFER"}
    )

    assert (created["code"], created["etims_payment_type"], created["position"]) == (
        "BANK",
        "07",
        4,
    )
    entry = AuditLog.objects.get(action="payment_method.created", entity_id=created["id"])
    assert entry.changes["code"] == [None, "BANK"]


def test_the_etims_type_can_be_chosen_but_credit_is_not_a_payment_method(biz):
    cheque = _create(
        biz.owner,
        {"code": "CHEQUE", "name": "Cheque", "kind": "OTHER", "etims_payment_type": "04"},
    )
    assert cheque["etims_payment_type"] == "04"

    response = biz.owner.post(
        "/api/v1/payment-methods/",
        {"code": "TAB", "name": "Tab", "kind": "OTHER", "etims_payment_type": "02"},
        format="json",
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == "/etims_payment_type"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"code": "cash", "name": "Cash 2", "kind": "OTHER"}, "code"),
        ({"code": "CASH2", "name": "m-pesa", "kind": "MOBILE_MONEY"}, "name"),
        ({"code": "TILL2", "name": "Second drawer", "kind": "CASH"}, "kind"),
        ({"code": "X", "name": "Too short", "kind": "OTHER"}, "code"),
        ({"code": "AIRTEL", "name": "Airtel", "kind": "OTHER", "provider": "DARAJA"}, "provider"),
    ],
)
def test_codes_and_names_are_unique_and_there_is_one_cash_method(biz, body, field):
    response = biz.owner.post("/api/v1/payment-methods/", body, format="json")

    assert response.status_code == 400
    assert response.json()["errors"][0]["pointer"] == f"/{field}"


def test_code_and_kind_are_fixed_but_the_rest_can_change(biz):
    mpesa = PaymentMethod.objects.for_org(biz.organization).get(code="MPESA")

    response = biz.owner.patch(
        f"/api/v1/payment-methods/{mpesa.pk}/",
        {"name": "M-Pesa Till", "position": 9, "code": "MP", "kind": "CASH", "version": 1},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["position"], body["code"], body["kind"], body["version"]) == (
        "M-Pesa Till",
        9,
        "MPESA",
        "MOBILE_MONEY",
        2,
    )
    assert AuditLog.objects.get(action="payment_method.updated").changes == {
        "name": ["M-Pesa", "M-Pesa Till"],
        "position": [2, 9],
    }


def test_inactive_methods_can_be_filtered_out(biz):
    card = PaymentMethod.objects.for_org(biz.organization).get(code="CARD")
    biz.owner.patch(
        f"/api/v1/payment-methods/{card.pk}/", {"is_active": False, "version": 1}, format="json"
    )

    active = biz.cashier.get("/api/v1/payment-methods/?is_active=true").json()["results"]

    assert [m["code"] for m in active] == ["CASH", "MPESA"]


def test_cashiers_can_read_methods_but_only_owners_change_them(biz):
    cash = PaymentMethod.objects.for_org(biz.organization).get(code="CASH")

    assert biz.cashier.get(f"/api/v1/payment-methods/{cash.pk}/").status_code == 200
    assert (
        biz.cashier.post(
            "/api/v1/payment-methods/", {"code": "X1", "name": "X", "kind": "OTHER"}
        ).status_code
        == 403
    )
    assert (
        biz.cashier.patch(
            f"/api/v1/payment-methods/{cash.pk}/", {"name": "X", "version": 1}
        ).status_code
        == 403
    )


def test_manual_provider_confirms_what_the_cashier_records():
    provider = get_provider("MANUAL")

    outcome = provider.initiate(PaymentRequest(Decimal("150.00"), "KES", reference="QK12ABC"))

    assert (outcome.status, outcome.reference) == (PaymentStatus.CONFIRMED, "QK12ABC")
    assert provider.confirm("QK12ABC").status == PaymentStatus.CONFIRMED
    assert provider.refund("QK12ABC", Decimal("150.00")).status == PaymentStatus.CONFIRMED


def test_a_second_cash_method_that_slips_past_validation_is_refused_cleanly(biz):
    """Two requests racing to add cash: the database constraint decides."""
    with pytest.raises(ApplicationError) as raised:
        create_payment_method(biz.owner_ctx, code="DRAWER2", name="Drawer 2", kind="CASH")

    assert (raised.value.status_code, raised.value.errors[0]["pointer"]) == (400, "/kind")
