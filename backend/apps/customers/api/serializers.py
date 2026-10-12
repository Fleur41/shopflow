from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.common.validators import normalize_phone
from apps.organizations.api.master_data import (
    ENTRY_FIELDS,
    READ_ONLY_FIELDS,
    MasterDataSerializer,
    VersionedUpdateMixin,
)
from apps.organizations.api.serializers import ScopedPrimaryKeyField, _ctx
from apps.organizations.models import Store
from apps.payments.models import PaymentMethod

from ..models import Customer, CustomerAccount, CustomerLedgerEntry

CONTACT_FIELDS = ("phone", "email", "address")


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=19, decimal_places=4, **kwargs)


def mask(value: str) -> str:
    """Enough to tell customers apart, not enough to contact them."""
    if not value:
        return ""
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{name[:1]}•••@{domain}"
    if len(value) > 6:
        return f"{value[:4]}•••{value[-3:]}"
    return "•••"


class CustomerAccountSummary(serializers.ModelSerializer[CustomerAccount]):
    available_credit = serializers.SerializerMethodField()

    class Meta:
        model = CustomerAccount
        fields = ("currency", "credit_limit", "balance", "available_credit", "status", "version")
        read_only_fields = fields

    def get_available_credit(self, account: CustomerAccount) -> str:
        limit = account.credit_limit or Decimal(0)
        return f"{max(limit - account.balance, Decimal(0)):.4f}"


class CustomerSerializer(MasterDataSerializer[Customer]):
    unique_fields = ()
    credit_limit = _money(
        write_only=True,
        required=False,
        allow_null=True,
        min_value=Decimal(0),
        help_text="On create only; needs customers.set_credit_limit.",
    )
    account = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = (
            "id",
            "name",
            "phone",
            "email",
            "address",
            "notes",
            "credit_limit",
            "account",
            *ENTRY_FIELDS,
        )
        read_only_fields = READ_ONLY_FIELDS

    def validate_phone(self, value: str) -> str:
        try:
            return normalize_phone(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages), code="invalid") from exc

    @extend_schema_field(CustomerAccountSummary(allow_null=True))
    def get_account(self, customer: Customer) -> dict[str, Any] | None:
        if not _ctx(self).has_perm("customers.view_balance"):
            return None
        accounts = getattr(customer, "prefetched_accounts", None)
        if accounts is None:
            accounts = list(customer.accounts.all())
        currency = _ctx(self).organization.base_currency
        account = next((a for a in accounts if a.currency == currency), None)
        return CustomerAccountSummary(account).data if account else None

    def to_representation(self, customer: Customer) -> dict[str, Any]:
        data = super().to_representation(customer)
        if not _ctx(self).has_perm("customers.view_contact"):
            for name in CONTACT_FIELDS:
                data[name] = mask(data[name])
        return data


class CustomerUpdateSerializer(VersionedUpdateMixin, CustomerSerializer):
    credit_limit = None  # type: ignore[assignment]  # set on the account instead

    class Meta(CustomerSerializer.Meta):
        fields: tuple[str, ...] = tuple(  # type: ignore[assignment]
            f for f in CustomerSerializer.Meta.fields if f != "credit_limit"
        )


class AccountUpdateSerializer(serializers.Serializer[Any]):
    version = serializers.IntegerField()
    credit_limit = _money(required=False, allow_null=True, min_value=Decimal(0))
    status = serializers.ChoiceField(choices=CustomerAccount.Status.choices, required=False)


class CustomerOpeningBalanceSerializer(serializers.Serializer[Any]):
    amount = _money(min_value=Decimal("0.01"))
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class LedgerEntrySerializer(serializers.ModelSerializer[CustomerLedgerEntry]):
    created_by = serializers.CharField(source="created_by.full_name")
    store = serializers.CharField(source="store.code", allow_null=True, default=None)
    store_id = serializers.UUIDField(allow_null=True)
    sale_id = serializers.UUIDField(allow_null=True)
    receipt_number = serializers.CharField(source="sale.receipt_number", default=None)
    reverses_id = serializers.UUIDField(allow_null=True)
    reversed = serializers.SerializerMethodField()

    class Meta:
        model = CustomerLedgerEntry
        fields = (
            "id",
            "seq",
            "entry_type",
            "amount",
            "balance_after",
            "description",
            "store",
            "store_id",
            "sale_id",
            "receipt_number",
            "reverses_id",
            "reversed",
            "created_by",
            "occurred_at",
            "recorded_at",
        )
        read_only_fields = fields

    def get_reversed(self, entry: CustomerLedgerEntry) -> bool:
        return hasattr(entry, "reversed_by")


class PaymentCreateSerializer(serializers.Serializer[Any]):
    client_txn_id = serializers.UUIDField()
    store_id = ScopedPrimaryKeyField(Store, source="store")
    payment_method_id = ScopedPrimaryKeyField(PaymentMethod, source="payment_method")
    amount = _money(min_value=Decimal("0.01"))
    tendered = _money(required=False, allow_null=True)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    occurred_at = serializers.DateTimeField(required=False)

    def validate_store_id(self, store: Store) -> Store:
        ctx = _ctx(self)
        if not store.is_active or not ctx.can_access_store(store.pk):
            raise serializers.ValidationError("You don't work at this store.", code="store")
        return store


class ReverseSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=200)
