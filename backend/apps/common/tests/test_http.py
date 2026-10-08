import pytest
from django.db import connection
from django.test import Client


def test_request_id_is_generated_when_absent(client: Client):
    response = client.get("/healthz")

    assert len(response["X-Request-ID"]) == 32


def test_valid_incoming_request_id_is_propagated(client: Client):
    response = client.get("/healthz", headers={"X-Request-ID": "edge-proxy-1234abcd"})

    assert response["X-Request-ID"] == "edge-proxy-1234abcd"


@pytest.mark.parametrize("bad", ["short", "has spaces in it!", "x" * 65, "inject\nnewline-123"])
def test_unsafe_incoming_request_id_is_replaced(client: Client, bad: str):
    response = client.get("/healthz", headers={"X-Request-ID": bad})

    assert response["X-Request-ID"] != bad
    assert len(response["X-Request-ID"]) == 32


def test_healthz_needs_no_dependencies(client: Client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "no-cache" in response["Cache-Control"]


@pytest.mark.django_db
def test_readyz_reports_ready(client: Client):
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "migrations": "ok", "cache": "ok"},
    }


@pytest.mark.django_db
def test_readyz_reports_database_failure(client: Client, monkeypatch: pytest.MonkeyPatch):
    def broken_cursor(*args, **kwargs):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(connection, "cursor", broken_cursor)

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "error"


def test_readyz_rejects_post(client: Client):
    assert client.post("/readyz").status_code == 405


@pytest.mark.django_db
def test_api_schema_requires_authentication(client: Client):
    response = client.get("/api/v1/schema/")

    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_readyz_reports_pending_migrations(client: Client, monkeypatch: pytest.MonkeyPatch):
    from django.db.migrations.executor import MigrationExecutor

    monkeypatch.setattr(MigrationExecutor, "migration_plan", lambda self, targets: ["pending"])

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] == "pending"


@pytest.mark.django_db
def test_readyz_reports_migration_check_and_cache_failures(
    client: Client, monkeypatch: pytest.MonkeyPatch
):
    from django.core.cache import cache
    from django.db.migrations.executor import MigrationExecutor

    def explode(*args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(MigrationExecutor, "migration_plan", explode)
    monkeypatch.setattr(cache, "set", explode)

    checks = client.get("/readyz").json()["checks"]

    assert checks["migrations"] == "error"
    assert checks["cache"] == "error"


@pytest.mark.django_db
def test_readyz_reports_cache_that_does_not_store(client: Client, monkeypatch: pytest.MonkeyPatch):
    from django.core.cache import cache

    monkeypatch.setattr(cache, "get", lambda key: None)

    assert client.get("/readyz").json()["checks"]["cache"] == "error"
