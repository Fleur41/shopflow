"""BOLA/IDOR suite (docs/SECURITY.md §4).

Business B's owner, who holds every permission in B, calls every endpoint
that takes an ID, for every method, using business A's IDs. Each call must
return 404, and nothing in A may change. New endpoints with path parameters
fail here until they are registered in TARGETS.
"""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.accounts.models import AuthSession
from apps.audit.models import AuditLog
from apps.catalog.models import Brand, Category, TaxRate, UnitOfMeasure
from apps.organizations.models import Invitation, Membership, Role, Store
from apps.organizations.testing import add_staff, add_store, client_for, create_business, role

from .routes import api_routes

pytestmark = pytest.mark.django_db

# Path template → how to fill it with business A's objects.
TARGETS = {
    "api/v1/stores/<uuid:store_id>/": lambda a: {"store_id": a.store.pk},
    "api/v1/roles/<uuid:role_id>/": lambda a: {"role_id": a.cashier_role.pk},
    "api/v1/members/<uuid:member_id>/": lambda a: {"member_id": a.cashier.pk},
    "api/v1/members/<uuid:member_id>/suspend/": lambda a: {"member_id": a.cashier.pk},
    "api/v1/members/<uuid:member_id>/reactivate/": lambda a: {"member_id": a.cashier.pk},
    "api/v1/auth/sessions/<uuid:session_id>/": lambda a: {"session_id": a.session.pk},
    "api/v1/invitations/<uuid:invitation_id>/revoke/": lambda a: {"invitation_id": a.invitation.pk},
    "api/v1/categories/<uuid:entry_id>/": lambda a: {"entry_id": a.category.pk},
    "api/v1/brands/<uuid:entry_id>/": lambda a: {"entry_id": a.brand.pk},
    "api/v1/units/<uuid:entry_id>/": lambda a: {"entry_id": a.unit.pk},
    "api/v1/tax-rates/<uuid:entry_id>/": lambda a: {"entry_id": a.tax_rate.pk},
}

# Catalog lookups of business A, compared before and after the attack.
CATALOG_MODELS = (Category, Brand, UnitOfMeasure, TaxRate)

# A body that passes validation for any endpoint, so lookups (not validators) decide.
BODY = {
    "name": "Taken over",
    "description": "",
    "reason": "Testing cross-tenant access",
    "version": 1,
    "permissions": [],
    "is_active": False,
}


@pytest.fixture
def world():
    a = create_business(email="owner@duka-a.example", name="Duka A")
    b = create_business(email="owner@duka-b.example", name="Duka B")
    store = add_store(a.organization, "BR2")
    cashier = add_staff(a.organization, email="cashier@duka-a.example", stores=[store])
    session = client_for(a.user, a.organization)  # creates an AuthSession for A's owner
    invitation = Invitation.objects.create(
        organization=a.organization,
        email="invitee@example.com",
        role=role(a.organization, Role.Template.CASHIER),
        all_stores=True,
        invited_by=a.user,
        token_hash="0" * 64,
        expires_at=timezone.now() + timedelta(days=7),
    )
    org = a.organization
    return SimpleNamespace(
        a=SimpleNamespace(
            organization=a.organization,
            store=store,
            cashier=cashier,
            cashier_role=role(a.organization, Role.Template.CASHIER),
            session=AuthSession.objects.get(user=a.user),
            invitation=invitation,
            client=session,
            category=Category.objects.create(organization=org, name="Drinks"),
            brand=Brand.objects.create(organization=org, name="Kensalt"),
            unit=UnitOfMeasure.objects.create(organization=org, code="PCS", name="Pieces"),
            tax_rate=TaxRate.objects.create(organization=org, name="VAT", rate="0.16"),
        ),
        b_client=client_for(b.user, b.organization),
    )


def _snapshot(organization):
    return {
        "audit": AuditLog.objects.filter(organization=organization).count(),
        "stores": sorted(
            Store.objects.for_org(organization).values_list("pk", "name", "is_active")
        ),
        "roles": sorted(Role.objects.for_org(organization).values_list("pk", "name")),
        "members": sorted(
            Membership.objects.for_org(organization).values_list("pk", "status", "version")
        ),
        "sessions": sorted(
            AuthSession.objects.filter(organization=organization).values_list("pk", "revoked_at")
        ),
        "invitations": sorted(
            Invitation.objects.for_org(organization).values_list("pk", "revoked_at", "accepted_at")
        ),
        **{
            model.audit_name: sorted(
                model.objects.for_org(organization).values_list("pk", "is_active", "version")
            )
            for model in CATALOG_MODELS
        },
    }


def test_every_route_with_an_id_is_covered():
    missing = {r.path for r in api_routes() if r.has_path_params} - set(TARGETS)

    assert not missing, f"Register these routes in TARGETS: {sorted(missing)}"


def test_other_businesses_get_404_and_change_nothing(world):
    before = _snapshot(world.a.organization)
    failures = []

    for route in api_routes():
        if not route.has_path_params:
            continue
        url = route.url(**TARGETS[route.path](world.a))
        for method in route.methods:
            response = getattr(world.b_client, method.lower())(url, BODY, format="json")
            if response.status_code != 404:
                failures.append(f"{method} {url} -> {response.status_code}")

    assert not failures, "Cross-tenant access not refused:\n" + "\n".join(failures)
    assert _snapshot(world.a.organization) == before
    assert world.a.client.get("/api/v1/organization/").status_code == 200  # A's session intact


def test_list_endpoints_never_include_another_businesses_records(world):
    a_ids = {
        str(pk)
        for pk in [
            *Store.objects.for_org(world.a.organization).values_list("pk", flat=True),
            *Role.objects.for_org(world.a.organization).values_list("pk", flat=True),
            *Membership.objects.for_org(world.a.organization).values_list("pk", flat=True),
            world.a.invitation.pk,
            world.a.session.pk,
            *(m.objects.for_org(world.a.organization).get().pk for m in CATALOG_MODELS),
            world.a.organization.pk,
        ]
    }

    for route in api_routes():
        if route.has_path_params or "GET" not in route.methods or route.path.endswith("docs/"):
            continue
        body = world.b_client.get(route.url()).content.decode()
        leaked = [pk for pk in a_ids if pk in body]
        assert not leaked, f"/{route.path} leaked {leaked}"
