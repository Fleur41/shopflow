"""Payment method endpoints (docs/API.md §4.10).

Every member can read them (the till needs them); changing them is an owner
setting. Behaviour shared with other master data lives in
``apps.organizations.api.master_data``.
"""

from typing import Any, ClassVar

from apps.common.pagination import DefaultCursorPagination
from apps.organizations.api.master_data import (
    MasterDataDetailView,
    MasterDataListView,
    patch_schema,
)
from apps.organizations.master_data import MasterData

from .. import services
from ..models import PaymentMethod
from .serializers import PaymentMethodSerializer, PaymentMethodUpdateSerializer


class _ByPosition(DefaultCursorPagination):
    """The order of the tender buttons at the till."""

    ordering = ("position", "name", "id")


class PaymentMethodListView(MasterDataListView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "org.view", "POST": "org.manage"}
    model = PaymentMethod
    serializer_class = PaymentMethodSerializer
    search_fields = ("code", "name")
    pagination_class = _ByPosition

    def create_entry(self, fields: dict[str, Any]) -> MasterData:
        return services.create_payment_method(self.ctx, **fields)


@patch_schema
class PaymentMethodDetailView(MasterDataDetailView):
    required_permissions: ClassVar[dict[str, str]] = {"GET": "org.view", "PATCH": "org.manage"}
    model = PaymentMethod
    serializer_class = PaymentMethodSerializer
    update_serializer_class = PaymentMethodUpdateSerializer
