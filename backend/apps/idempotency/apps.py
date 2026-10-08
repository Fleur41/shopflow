from django.apps import AppConfig


class IdempotencyConfig(AppConfig):
    name = "apps.idempotency"
    label = "idempotency"
    verbose_name = "Idempotency keys"
