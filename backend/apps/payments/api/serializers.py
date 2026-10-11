from typing import Any, ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.organizations.api.master_data import (
    ENTRY_FIELDS,
    READ_ONLY_FIELDS,
    MasterDataSerializer,
    VersionedUpdateMixin,
)
from apps.organizations.api.serializers import _ctx

from ..models import PaymentMethod, payment_code_validator


class PaymentMethodSerializer(MasterDataSerializer[PaymentMethod]):
    # Declared explicitly so input is upper-cased before the format check runs.
    code = serializers.CharField(max_length=30)
    etims_payment_type = serializers.ChoiceField(
        choices=PaymentMethod.EtimsPaymentType.choices,
        required=False,
        help_text="KRA eTIMS payment type. Defaults from the kind.",
    )
    position = serializers.IntegerField(
        min_value=0, max_value=32767, required=False, help_text="Defaults to after the others."
    )
    unique_fields = ("code", "name")
    taken_messages: ClassVar[dict[str, str]] = {
        "code": "Another payment method already uses this code.",
        "name": "Another payment method already has this name.",
    }

    class Meta:
        model = PaymentMethod
        fields = (
            "id",
            "code",
            "name",
            "kind",
            "provider",
            "requires_reference",
            "position",
            "etims_payment_type",
            *ENTRY_FIELDS,
        )
        read_only_fields = READ_ONLY_FIELDS

    def validate_code(self, value: str) -> str:
        code = value.strip().upper()
        try:
            payment_code_validator(code)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages), code="invalid") from exc
        return code

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if attrs.get("kind") == PaymentMethod.Kind.CASH:
            others = PaymentMethod.objects.for_org(_ctx(self).organization)
            if others.filter(kind=PaymentMethod.Kind.CASH).exists():
                raise serializers.ValidationError(
                    {"kind": ["This business already has a cash payment method."]}, code="taken"
                )
        return attrs


class PaymentMethodUpdateSerializer(VersionedUpdateMixin, PaymentMethodSerializer):
    # Past payments keep meaning what they said: reports and sync rely on the
    # code, and the till's cash count relies on the kind.
    code = serializers.CharField(read_only=True)
    kind = serializers.ChoiceField(choices=PaymentMethod.Kind.choices, read_only=True)
