import threading
import time
import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.idempotency.models import IdempotencyKey
from apps.organizations import services
from apps.organizations.models import Store
from apps.organizations.testing import add_staff, client_for, create_business

pytestmark = pytest.mark.urls("apps.idempotency.tests.urls")
OPERATION_ID = str(uuid.uuid4())  # the Idempotency-Key value a client would send


@pytest.fixture
def biz(db):
    return create_business()


@pytest.fixture
def owner(biz):
    return client_for(biz.user, biz.organization)


def _post(client, body, key=OPERATION_ID, url="/strict-stores/"):
    headers = {"HTTP_IDEMPOTENCY_KEY": key} if key is not None else {}
    return client.post(url, body, format="json", **headers)


def _store_codes(organization):
    return sorted(Store.objects.for_org(organization).values_list("code", flat=True))


def test_retry_with_the_same_key_replays_without_repeating(owner, biz):
    first = _post(owner, {"code": "S1"})
    retry = _post(owner, {"code": "S1"})

    assert first.status_code == retry.status_code == 201
    assert retry.json() == first.json()
    assert retry["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first
    assert _store_codes(biz.organization) == ["MAIN", "S1"]
    assert (
        AuditLog.objects.filter(action="store.created", entity_id=first.json()["id"]).count() == 1
    )


def test_required_key_must_be_sent(owner, biz):
    response = _post(owner, {"code": "S1"}, key=None)

    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert _store_codes(biz.organization) == ["MAIN"]


@pytest.mark.parametrize("key", ["short", "has spaces in it", "x" * 256, "semi;colon-key"])
def test_malformed_keys_are_rejected(owner, key):
    response = _post(owner, {"code": "S1"}, key=key)

    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_INVALID"


def test_same_key_for_a_different_request_is_refused(owner, biz):
    _post(owner, {"code": "S1"})

    response = _post(owner, {"code": "S2"})

    assert response.status_code == 422
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert _store_codes(biz.organization) == ["MAIN", "S1"]


def test_a_key_never_returns_another_users_response(owner, biz):
    _post(owner, {"code": "S1"})
    colleague = add_staff(
        biz.organization, email="co@duka-a.example", template="OWNER", all_stores=True
    )

    response = _post(client_for(colleague.user, biz.organization), {"code": "S1"})

    assert response.status_code == 422


def test_same_key_on_a_different_endpoint_is_refused(owner):
    _post(owner, {"code": "S1"})

    response = _post(owner, {"code": "S1", "name": "Other"}, url="/api/v1/stores/")

    assert response.status_code == 422


def test_keys_are_independent_between_businesses(owner, biz):
    other = create_business(email="owner@duka-b.example", name="Duka B")

    assert _post(owner, {"code": "S1"}).status_code == 201
    assert _post(client_for(other.user, other.organization), {"code": "S1"}).status_code == 201


def test_failures_roll_back_the_key_so_a_corrected_retry_works(owner, biz):
    failed = _post(owner, {"fail": True})

    assert failed.status_code == 422
    assert not IdempotencyKey.objects.exists()
    assert _store_codes(biz.organization) == ["MAIN"]  # the half-done work rolled back too

    retried = _post(owner, {"code": "S1"})
    assert retried.status_code == 201


def test_validation_errors_are_not_remembered(owner, biz):
    invalid = _post(owner, {"code": "x"}, url="/api/v1/stores/")  # name missing, bad code

    assert invalid.status_code == 400
    assert not IdempotencyKey.objects.exists()
    valid = _post(owner, {"code": "S9", "name": "Fixed"}, url="/api/v1/stores/")
    assert valid.status_code == 201


def test_optional_endpoints_work_without_a_key(owner, biz):
    response = owner.post("/api/v1/stores/", {"code": "S1", "name": "No key"}, format="json")

    assert response.status_code == 201
    assert not IdempotencyKey.objects.exists()


def test_purge_removes_only_expired_keys(owner, biz):
    _post(owner, {"code": "S1"})
    _post(owner, {"code": "S2"}, key="0192a7c4-0000-7000-8000-000000000002")
    IdempotencyKey.objects.filter(key=OPERATION_ID).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    call_command("purge_idempotency_keys")

    assert list(IdempotencyKey.objects.values_list("key", flat=True)) == [
        "0192a7c4-0000-7000-8000-000000000002"
    ]


# --- Real concurrency against PostgreSQL ----------------------------------------------


def _race(client, monkeypatch, *, hold_seconds):
    """Send the same request twice at once; the first holds its transaction open."""
    real_create = services.create_store
    calls = []

    def slow_create(*args, **kwargs):
        calls.append(1)
        store = real_create(*args, **kwargs)
        time.sleep(hold_seconds)
        return store

    monkeypatch.setattr(services, "create_store", slow_create)
    barrier = threading.Barrier(2)
    responses = []

    def send():
        try:
            barrier.wait()
            responses.append(_post(client, {"code": "R1"}))
        finally:
            connection.close()

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
        time.sleep(0.05)  # make the arrival order deterministic
    for thread in threads:
        thread.join(timeout=15)
    return responses, calls


@pytest.mark.django_db(transaction=True)
def test_simultaneous_duplicates_run_once_and_the_second_replays(monkeypatch):
    business = create_business()
    client = client_for(business.user, business.organization)

    responses, calls = _race(client, monkeypatch, hold_seconds=0.5)

    assert sorted(r.status_code for r in responses) == [201, 201]
    assert sorted(r.get("Idempotent-Replayed", "-") for r in responses) == ["-", "true"]
    assert len(calls) == 1
    assert _store_codes(business.organization) == ["MAIN", "R1"]


@pytest.mark.django_db(transaction=True)
def test_a_duplicate_that_waits_too_long_gets_in_progress(monkeypatch, settings):
    settings.IDEMPOTENCY_LOCK_TIMEOUT = timedelta(milliseconds=200)
    business = create_business()
    client = client_for(business.user, business.organization)

    responses, calls = _race(client, monkeypatch, hold_seconds=1.5)

    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409]
    blocked = next(r for r in responses if r.status_code == 409)
    assert blocked.json()["code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert len(calls) == 1
