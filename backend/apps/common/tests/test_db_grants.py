"""The runtime database role is least-privilege (docs/SECURITY.md §9).

These tests connect to the test database *as the app role* and try what an
attacker holding the application's database credentials might try.
"""

import os
import uuid

import psycopg
import pytest
from django.conf import settings
from django.db import connection

from apps.audit.services import AuditActor, record_audit
from apps.common.db_grants import append_only_tables
from apps.organizations.testing import create_business

requires_app_role = pytest.mark.skipif(
    not settings.DATABASE_APP_ROLE or not os.environ.get("DATABASE_APP_PASSWORD"),
    reason="DATABASE_APP_ROLE / DATABASE_APP_PASSWORD not configured",
)


def test_append_only_tables_are_registered():
    assert "audit_auditlog" in append_only_tables()


@pytest.mark.django_db
def test_every_append_only_table_has_the_modification_trigger():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_proc p ON p.oid = t.tgfoid WHERE p.proname = 'shopflow_prevent_modification'"
        )
        protected = {row[0] for row in cursor.fetchall()}

    assert set(append_only_tables()) <= protected


@pytest.fixture
def as_app_role(transactional_db):
    """A raw connection to the test database as the restricted runtime role."""
    db = connection.settings_dict
    conn = psycopg.connect(
        host=db["HOST"],
        port=db["PORT"] or 5432,
        dbname=db["NAME"],
        user=settings.DATABASE_APP_ROLE,
        password=os.environ["DATABASE_APP_PASSWORD"],
        autocommit=True,
    )
    yield conn
    conn.close()


def _refused(conn, sql, params=()):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(sql, params)


@requires_app_role
def test_app_role_cannot_rewrite_audit_history(as_app_role):
    business = create_business()
    entry = record_audit(
        AuditActor(organization_id=business.organization.pk, user_id=business.user.pk),
        action="test.recorded",
        entity_type="test",
        entity_id=uuid.uuid4(),
    )

    count = as_app_role.execute("SELECT count(*) FROM audit_auditlog").fetchone()[0]
    assert count >= 1  # reading is allowed
    _refused(as_app_role, "UPDATE audit_auditlog SET reason = 'x' WHERE id = %s", [entry.pk])
    _refused(as_app_role, "DELETE FROM audit_auditlog WHERE id = %s", [entry.pk])
    _refused(as_app_role, "TRUNCATE audit_auditlog")


@requires_app_role
def test_app_role_cannot_change_schema_or_migration_history(as_app_role):
    _refused(as_app_role, "ALTER TABLE accounts_user ADD COLUMN backdoor text")
    _refused(as_app_role, "DROP TABLE organizations_store")
    _refused(as_app_role, "DELETE FROM django_migrations")
    _refused(as_app_role, "DROP TRIGGER audit_auditlog_append_only ON audit_auditlog")


@requires_app_role
def test_app_role_can_do_normal_row_work(as_app_role):
    business = create_business()

    as_app_role.execute(
        "UPDATE organizations_organization SET name = %s WHERE id = %s",
        ["Renamed", business.organization.pk],
    )
    as_app_role.execute("SELECT nextval(pg_get_serial_sequence('django_admin_log', 'id'))")


@requires_app_role
def test_app_role_can_advance_the_sync_cursor_but_not_rewrite_price_history(as_app_role):
    # Every product save runs the row_version trigger, which needs the sequence.
    assert as_app_role.execute("SELECT nextval('shopflow_row_version')").fetchone()[0] > 0
    _refused(as_app_role, "UPDATE catalog_productpricehistory SET new_price = 0")
    _refused(as_app_role, "DELETE FROM catalog_productpricehistory")
