"""Keep the Permission table in step with ``catalog.CATALOG``.

Runs after every ``migrate``. Newly introduced permission codes are also
granted to existing roles created from a template that includes them, so a
release adding (say) ``reports.export`` to the Manager template reaches
existing businesses. Owners need nothing: they implicitly hold every code.
"""

import structlog
from django.db import transaction

from .catalog import ALL_CODES, CATALOG, ROLE_TEMPLATES
from .models import Permission, Role, RolePermission

logger = structlog.get_logger(__name__)


def sync_permission_catalog(using: str = "default") -> None:
    with transaction.atomic(using=using):
        existing = set(Permission.objects.using(using).values_list("code", flat=True))
        for definition in CATALOG:
            Permission.objects.using(using).update_or_create(
                code=definition.code,
                defaults={
                    "description": definition.description,
                    "category": definition.category,
                    "is_sensitive": definition.sensitive,
                },
            )

        obsolete = existing - ALL_CODES
        if obsolete:
            Permission.objects.using(using).filter(code__in=obsolete).delete()
            logger.warning("permissions.removed", codes=sorted(obsolete))

        added = ALL_CODES - existing
        if existing and added:  # first sync: no roles exist yet
            for template, (_, _, codes) in ROLE_TEMPLATES.items():
                new_codes = sorted(added & codes)
                if not new_codes:
                    continue
                role_ids = (
                    Role.unscoped.using(using)
                    .filter(template=template)
                    .values_list("pk", flat=True)
                )
                RolePermission.objects.using(using).bulk_create(
                    [
                        RolePermission(role_id=role_id, permission_id=code)
                        for role_id in role_ids
                        for code in new_codes
                    ],
                    ignore_conflicts=True,
                )
            logger.info("permissions.added", codes=sorted(added))
