from django.apps import AppConfig


class CustomersConfig(AppConfig):
    name = "apps.customers"
    label = "customers"
    verbose_name = "Customers"

    def ready(self) -> None:
        # Registers the credit-sale charger with the sales app.
        from . import services  # noqa: F401
