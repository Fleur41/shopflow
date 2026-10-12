from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.organizations.api.serializers import _ctx

from ..models import CashMovement, CashSession, Till


def _money(**kwargs: Any) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=19, decimal_places=4, **kwargs)


class TillSerializer(serializers.ModelSerializer[Till]):
    class Meta:
        model = Till
        fields: tuple[str, ...] = ("id", "name", "is_active", "version")
        read_only_fields: tuple[str, ...] = ("id", "version")

    def validate_name(self, value: str) -> str:
        name = value.strip()
        store = self.context["store"]
        tills = Till.objects.for_org(_ctx(self).organization).filter(store=store, name__iexact=name)
        if self.instance is not None:
            tills = tills.exclude(pk=self.instance.pk)
        if tills.exists():
            raise serializers.ValidationError("This store already has a till with this name.")
        return name


class TillUpdateSerializer(TillSerializer):
    version = serializers.IntegerField()

    class Meta(TillSerializer.Meta):
        read_only_fields = ("id",)


class _TillUser(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()


class CashMovementSerializer(serializers.ModelSerializer[CashMovement]):
    created_by = serializers.CharField(source="created_by.full_name")

    class Meta:
        model = CashMovement
        fields = ("id", "movement_type", "amount", "reason", "created_by", "occurred_at")
        read_only_fields = fields


class CashSessionSerializer(serializers.ModelSerializer[CashSession]):
    """A session as the person at the till sees it: no expected cash while open
    (the close-out count is blind)."""

    till = TillSerializer()
    opened_by = serializers.SerializerMethodField()
    closed_by = serializers.SerializerMethodField()

    class Meta:
        model = CashSession
        fields: tuple[str, ...] = (
            "id",
            "till",
            "status",
            "opening_float",
            "opened_by",
            "opened_at",
            "closed_by",
            "closed_at",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(_TillUser)
    def get_opened_by(self, session: CashSession) -> dict[str, Any]:
        return {"id": str(session.opened_by_id), "name": session.opened_by.full_name}

    @extend_schema_field(_TillUser(allow_null=True))
    def get_closed_by(self, session: CashSession) -> dict[str, Any] | None:
        if session.closed_by is None:
            return None
        return {"id": str(session.closed_by_id), "name": session.closed_by.full_name}


class CashSessionSummarySerializer(CashSessionSerializer):
    """For managers: the result of the count too."""

    class Meta(CashSessionSerializer.Meta):
        fields = (
            *CashSessionSerializer.Meta.fields,
            "expected_cash",
            "counted_cash",
            "variance",
            "variance_reason",
        )
        read_only_fields = fields


class CurrentSessionSerializer(serializers.Serializer[Any]):
    session = CashSessionSerializer(allow_null=True)


class _MethodTotal(serializers.Serializer[Any]):
    method = serializers.CharField()
    count = serializers.IntegerField()
    total = _money()


class ReportSerializer(serializers.Serializer[Any]):
    """X report while open, Z report once closed."""

    opening_float = _money()
    sales_count = serializers.IntegerField()
    sales_total = _money()
    on_credit = _money()
    voids_count = serializers.IntegerField()
    voids_total = _money()
    returns_count = serializers.IntegerField()
    returns_total = _money()
    by_method = _MethodTotal(many=True)
    cash_in = _money()
    cash_out = _money()
    pay_ins = _money()
    pay_outs = _money()
    drops = _money()
    expected_cash = _money()
    counted_cash = _money(allow_null=True)
    variance = _money(allow_null=True)
    corrections = _money()
    variance_after_corrections = _money(allow_null=True)


class SessionReportSerializer(serializers.Serializer[Any]):
    session = CashSessionSummarySerializer()
    report = ReportSerializer()
    movements = CashMovementSerializer(many=True)


class OpenSessionSerializer(serializers.Serializer[Any]):
    client_txn_id = serializers.UUIDField()
    till_id = serializers.UUIDField()
    opening_float = _money(min_value=Decimal(0))


class MovementCreateSerializer(serializers.Serializer[Any]):
    client_txn_id = serializers.UUIDField()
    movement_type = serializers.ChoiceField(choices=["PAY_IN", "PAY_OUT", "DROP"])
    amount = _money(min_value=Decimal("0.01"))
    reason = serializers.CharField(max_length=300)


class CorrectionSerializer(serializers.Serializer[Any]):
    client_txn_id = serializers.UUIDField()
    amount = _money(help_text="Found (+) or missing (-).")
    reason = serializers.CharField(max_length=300)


class CloseSessionSerializer(serializers.Serializer[Any]):
    counted_cash = _money(min_value=Decimal(0))
    denomination_count = serializers.DictField(
        child=serializers.IntegerField(min_value=0), required=False, allow_null=True
    )
    variance_reason = serializers.CharField(
        max_length=300, required=False, allow_blank=True, default=""
    )

    def validate_denomination_count(self, value: dict[str, int] | None) -> dict[str, int] | None:
        if not value:
            return None
        for key in value:
            try:
                Decimal(key)
            except ArithmeticError as exc:
                raise serializers.ValidationError(f"{key} isn't a note or coin value.") from exc
        return {key: count for key, count in value.items() if count}
