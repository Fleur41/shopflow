import uuid

import pytest
from django.db import IntegrityError, connection, transaction

from apps.audit.models import AppendOnlyError, AuditLog
from apps.audit.services import AuditActor, diff, record_audit
from apps.organizations.testing import create_business

pytestmark = pytest.mark.django_db


@pytest.fixture
def entry():
    business = create_business()
    actor = AuditActor(
        organization_id=business.organization.pk,
        user_id=business.user.pk,
        request_id="req-1",
        ip_address="203.0.113.9",
        user_agent="pytest",
    )
    return record_audit(
        actor,
        action="product.price_changed",
        entity_type="product",
        entity_id=uuid.uuid4(),
        changes={"selling_price": ["80.00", "85.00"]},
        reason="Supplier price increase",
    )


def test_record_audit_stores_actor_and_request_metadata(entry):
    stored = AuditLog.objects.get(pk=entry.pk)

    assert stored.actor_type == AuditLog.ActorType.USER
    assert stored.request_id == "req-1"
    assert stored.ip_address == "203.0.113.9"
    assert stored.changes == {"selling_price": ["80.00", "85.00"]}
    assert stored.reason == "Supplier price increase"


def test_model_refuses_updates_and_deletes(entry):
    entry.reason = "rewritten"
    with pytest.raises(AppendOnlyError):
        entry.save()
    with pytest.raises(AppendOnlyError):
        entry.delete()


def test_database_refuses_updates_and_deletes_from_any_code_path(entry):
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        AuditLog.objects.filter(pk=entry.pk).update(reason="tampered")
    with pytest.raises(IntegrityError, match="append-only"), transaction.atomic():
        AuditLog.objects.filter(pk=entry.pk).delete()
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM audit_auditlog")

    assert AuditLog.objects.get(pk=entry.pk).reason == "Supplier price increase"


def test_diff_reports_only_changed_fields_in_json_safe_form():
    store_id = uuid.uuid4()

    changes = diff(
        {"name": "Main", "phone": "1", "stores": {"B", "A"}, "store": None},
        {"name": "Main shop", "phone": "1", "stores": {"A"}, "store": store_id},
    )

    assert changes == {
        "name": ["Main", "Main shop"],
        "store": [None, str(store_id)],
        "stores": [["A", "B"], ["A"]],
    }
