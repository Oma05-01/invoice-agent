
import re

from collections.abc import Mapping

from rest_framework import serializers


EDITABLE_HEADER_FIELDS = {
    "invoice_number",
    "invoice_date",
    "due_date",
    "currency",
    "subtotal",
    "other_charges",
    "total_amount",
    "amount_due",
    "description",
}


class InvoiceHeaderCorrectionSerializer(serializers.Serializer):
    invoice_number = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )

    invoice_date = serializers.DateField(
        required=False,
        allow_null=True,
    )

    due_date = serializers.DateField(
        required=False,
        allow_null=True,
    )

    currency = serializers.CharField(
        max_length=3,
        required=False,
        allow_null=True,
    )

    subtotal = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    other_charges = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    total_amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    amount_due = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    description = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    correction_reason = serializers.CharField(
        max_length=1000,
        required=True,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data.keys()) - set(self.fields.keys())

            if unknown_fields:
                raise serializers.ValidationError({
                    "unknown_fields": (
                        f"Unsupported fields: "
                        f"{', '.join(sorted(unknown_fields))}"
                    )
                })

        return super().to_internal_value(data)

    def validate_currency(self, value):
        if value is None:
            return None

        value = value.strip().upper()

        if not re.fullmatch(r"[A-Z]{3}", value):
            raise serializers.ValidationError(
                "Currency must be a three-letter ISO code."
            )

        return value

    def validate(self, attrs):
        supplied_fields = EDITABLE_HEADER_FIELDS.intersection(
            attrs.keys()
        )

        if not supplied_fields:
            raise serializers.ValidationError(
                "At least one invoice field must be supplied."
            )

        return attrs

class VendorResolutionSerializer(serializers.Serializer):

    vendor_id = serializers.UUIDField()

    correction_reason = serializers.CharField(
        max_length=1000,
        required=True,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data.keys()) - set(self.fields.keys())

            if unknown_fields:
                raise serializers.ValidationError({
                    "unknown_fields": (
                        f"Unsupported fields: "
                        f"{', '.join(sorted(unknown_fields))}"
                    )
                })

        return super().to_internal_value(data)

class InvoiceLineItemCorrectionSerializer(serializers.Serializer):

    description = serializers.CharField(
        max_length=5000,
        required=False,
    )

    quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        required=False,
        allow_null=True,
    )

    unit_price = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    tax_rate = serializers.DecimalField(
        max_digits=7,
        decimal_places=4,
        required=False,
        allow_null=True,
    )

    line_total = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    ledger_code = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
    )

    correction_reason = serializers.CharField(
        max_length=1000,
        required=True,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data.keys()) - set(self.fields.keys())

            if unknown_fields:
                raise serializers.ValidationError({
                    "unknown_fields": (
                        f"Unsupported fields: "
                        f"{', '.join(sorted(unknown_fields))}"
                    )
                })

        return super().to_internal_value(data)

    def validate(self, attrs):
        editable_fields = {
            "description",
            "quantity",
            "unit_price",
            "tax_rate",
            "line_total",
            "ledger_code",
        }

        if not editable_fields.intersection(attrs.keys()):
            raise serializers.ValidationError(
                "At least one line-item field must be supplied."
            )

        return attrs


class InvoiceLineItemDeleteSerializer(serializers.Serializer):

    correction_reason = serializers.CharField(
        max_length=1000,
        required=True,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data.keys()) - set(self.fields.keys())

            if unknown_fields:
                raise serializers.ValidationError({
                    "unknown_fields": (
                        f"Unsupported fields: "
                        f"{', '.join(sorted(unknown_fields))}"
                    )
                })

        return super().to_internal_value(data)


class InvoiceValidationIssueIgnoreSerializer(serializers.Serializer):

    decision_reason = serializers.CharField(
        max_length=1000,
        required=True,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data.keys()) - set(self.fields.keys())

            if unknown_fields:
                raise serializers.ValidationError({
                    "unknown_fields": (
                        f"Unsupported fields: "
                        f"{', '.join(sorted(unknown_fields))}"
                    )
                })

        return super().to_internal_value(data)

class InvoiceReviewSubmissionSerializer(serializers.Serializer):

    submission_note = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
    )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = set(data.keys()) - set(self.fields.keys())

            if unknown_fields:
                raise serializers.ValidationError({
                    "unknown_fields": (
                        f"Unsupported fields: "
                        f"{', '.join(sorted(unknown_fields))}"
                    )
                })

        return super().to_internal_value(data)