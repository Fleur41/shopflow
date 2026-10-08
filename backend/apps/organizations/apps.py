from typing import Any

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class OrganizationsConfig(AppConfig):
    name = "apps.organizations"
    label = "organizations"
    verbose_name = "Organizations"

    def ready(self) -> None:
        post_migrate.connect(_sync_catalog, sender=self)


def _sync_catalog(**kwargs: Any) -> None:
    from .permission_sync import sync_permission_catalog

    sync_permission_catalog(using=kwargs.get("using", "default"))
