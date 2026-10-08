from typing import Any

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class CommonConfig(AppConfig):
    name = "apps.common"
    label = "common"
    verbose_name = "Common"

    def ready(self) -> None:
        # Sent once per app after the whole migrate run; bind to this app only.
        post_migrate.connect(_apply_grants, sender=self)


def _apply_grants(**kwargs: Any) -> None:
    from .db_grants import apply_database_grants

    apply_database_grants(using=kwargs.get("using", "default"))
