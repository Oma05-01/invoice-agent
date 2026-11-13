from decimal import Decimal

from rest_framework import serializers

from accounting.models import Account, JournalEntry, JournalLine


class AccountSerializer(serializers.ModelSerializer):

    parent_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
    )
    
    class Meta:
        model = Account
        fields = (
            "id",
            "code",
            "name",
            "account_type",
            "description",
            "parent_id",
            "is_active",
            "is_control_account",
        )
        read_only_fields = fields


class JournalLineAccountSerializer(serializers.ModelSerializer):

    class Meta:
        model = Account
        fields = (
            "id",
            "code",
            "name",
            "account_type",
        )
        read_only_fields = fields


class JournalLineSerializer(serializers.ModelSerializer):
    account = JournalLineAccountSerializer(read_only=True)
    source_line_item_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = JournalLine
        fields = (
            "id",
            "line_number",
            "account",
            "source_line_item_id",
            "description",
            "debit",
            "credit",
        )
        read_only_fields = fields


class JournalEntrySerializer(serializers.ModelSerializer):

    reversal_of_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
    )

    source_invoice_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
    )
    created_by_id = serializers.ReadOnlyField()
    posted_by_id = serializers.ReadOnlyField()
    lines = JournalLineSerializer(many=True, read_only=True)

    class Meta:
        model = JournalEntry
        fields = (
            "id",
            "source_invoice_id",
            "entry_date",
            "currency",
            "reference",
            "description",
            "status",
            "created_by_id",
            "posted_by_id",
            "posted_at",
            "reversal_of_id",
            "reversal_reason",
            "created_at",
            "updated_at",
            "lines",
        )
        read_only_fields = fields


class JournalLineCorrectionSerializer(serializers.Serializer):
    account_id = serializers.UUIDField(
        required=False,
        allow_null=True,
    )
    debit = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )
    credit = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    correction_reason = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        correction_fields = {
            "account_id",
            "debit",
            "credit",
            "description",
        }

        if not correction_fields.intersection(attrs):
            raise serializers.ValidationError(
                "At least one journal-line correction is required."
            )

        return attrs


class JournalReversalSerializer(serializers.Serializer):
    reversal_reason = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )

    def validate_reversal_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                "A reversal reason is required."
            )

        return value

class AccountLedgerQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    currency = serializers.CharField(
        required=False,
        max_length=3,
    )

    def validate_currency(self, value):
        value = value.strip().upper()

        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError(
                "Currency must be a three-letter code, such as NGN or USD."
            )

        return value

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if (
            start_date
            and end_date
            and start_date > end_date
        ):
            raise serializers.ValidationError({
                "end_date": "End date cannot be earlier than start date."
            })

        return attrs


class TrialBalanceQuerySerializer(serializers.Serializer):
    as_of_date = serializers.DateField(required=False)
    currency = serializers.CharField(
        required=False,
        max_length=3,
    )

    def validate_currency(self, value):
        value = value.strip().upper()

        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError(
                "Currency must be a three-letter code, such as NGN or USD."
            )

        return value

class IncomeStatementQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)

    currency = serializers.CharField(
        required=False,
        max_length=3,
    )

    def validate_currency(self, value):
        value = value.strip().upper()

        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError(
                "Currency must be a three-letter code, such as NGN or USD."
            )

        return value

    def validate(self, attrs):
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError({
                "end_date": "End date cannot be earlier than start date."
            })

        return attrs


class BalanceSheetQuerySerializer(serializers.Serializer):
    as_of_date = serializers.DateField(required=False)

    currency = serializers.CharField(
        required=False,
        max_length=3,
    )

    def validate_currency(self, value):
        value = value.strip().upper()

        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError(
                "Currency must be a three-letter code, such as NGN or USD."
            )

        return value


class APAgeingQuerySerializer(serializers.Serializer):
    as_of_date = serializers.DateField(required=False)

    currency = serializers.CharField(
        required=False,
        max_length=3,
    )

    def validate_currency(self, value):
        value = value.strip().upper()

        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError(
                "Currency must be a three-letter code, such as NGN or USD."
            )

        return value
    

class JournalAdjustmentLineInputSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()

    debit = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        default=Decimal("0.00"),
    )

    credit = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
        default=Decimal("0.00"),
    )

    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        debit = attrs["debit"]
        credit = attrs["credit"]

        if debit > 0 and credit > 0:
            raise serializers.ValidationError(
                "A journal line cannot contain both a debit and a credit."
            )

        if debit == 0 and credit == 0:
            raise serializers.ValidationError(
                "A journal line must contain a positive debit or credit."
            )

        return attrs


class JournalAdjustmentCreateSerializer(serializers.Serializer):
    entry_date = serializers.DateField()

    reason = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )

    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    lines = JournalAdjustmentLineInputSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_lines(self, value):
        if len(value) < 2:
            raise serializers.ValidationError(
                "An adjustment must contain at least two journal lines."
            )

        return value

class JournalEntryDateUpdateSerializer(serializers.Serializer):
    entry_date = serializers.DateField()

    correction_reason = serializers.CharField(
        max_length=2000,
        allow_blank=False,
        trim_whitespace=True,
    )

