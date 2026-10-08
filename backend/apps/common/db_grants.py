"""Least-privilege grants for the application's runtime database role.

Migrations run as the schema owner; the running application connects as a
separate role (``DATABASE_APP_ROLE``) that may read and write rows but
cannot change the schema, rewrite migration history, or update or delete
rows in append-only tables. Grants are re-applied after every ``migrate``
(including test databases), so new tables are always covered.
"""

import re
from typing import Any

import structlog
from django.apps import apps
from django.conf import settings
from django.db import connections

logger = structlog.get_logger(__name__)
_SAFE_ROLE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def append_only_tables() -> list[str]:
    """Tables of models that declare ``append_only = True``."""
    return sorted(
        model._meta.db_table for model in apps.get_models() if getattr(model, "append_only", False)
    )


def apply_database_grants(using: str = "default", **kwargs: Any) -> None:
    role = settings.DATABASE_APP_ROLE
    if not role:
        return
    if not _SAFE_ROLE.match(role):
        raise ValueError(f"DATABASE_APP_ROLE has an unexpected format: {role!r}")
    connection = connections[using]
    if connection.vendor != "postgresql":
        return
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        if cursor.fetchone() is None:
            logger.warning("db_grants.role_missing", role=role)
            return
        grantee = quote(role)
        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {grantee}"
        )
        cursor.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {grantee}")
        cursor.execute(f"REVOKE INSERT, UPDATE, DELETE ON django_migrations FROM {grantee}")
        for table in append_only_tables():
            cursor.execute(f"REVOKE UPDATE, DELETE ON {quote(table)} FROM {grantee}")
