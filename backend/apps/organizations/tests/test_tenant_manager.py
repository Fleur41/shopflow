import pytest

from apps.organizations.models import Membership, Store, UnscopedQueryError

pytestmark = pytest.mark.django_db


def test_unscoped_queries_fail_loudly(biz):
    with pytest.raises(UnscopedQueryError, match="for_org"):
        list(Store.objects.all())
    with pytest.raises(UnscopedQueryError):
        Store.objects.filter(code="MAIN").exists()


def test_for_org_returns_only_that_organizations_rows(biz, other_biz):
    codes_a = set(Store.objects.for_org(biz.organization).values_list("code", flat=True))
    codes_b = set(Store.objects.for_org(other_biz.organization.pk).values_list("code", flat=True))

    assert codes_a == {"MAIN", "BR2"}
    assert codes_b == {"MAIN"}


def test_for_org_requires_an_organization():
    with pytest.raises(UnscopedQueryError):
        Store.objects.for_org(None)


def test_create_requires_an_organization(biz):
    with pytest.raises(UnscopedQueryError, match="organization"):
        Store.objects.create(code="X1", name="X", currency="KES", timezone="UTC")

    store = Store.objects.create(
        organization=biz.organization, code="X1", name="X", currency="KES", timezone="UTC"
    )
    assert store.organization == biz.organization


def test_django_internals_use_the_unscoped_default_manager(biz):
    assert Store._default_manager is Store.unscoped
    # Related managers keep working: they are filtered by the relation itself.
    assert list(biz.cashier.stores.all()) == [biz.store]
    assert Membership.unscoped.filter(user=biz.user).count() == 1
