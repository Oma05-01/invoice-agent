from rest_framework import serializers

from insights.services.spend import MAX_SPEND_LIMIT, SPEND_DIMENSIONS


class SpendReportQuerySerializer(serializers.Serializer):
    dimension = serializers.ChoiceField(choices=SPEND_DIMENSIONS)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    limit = serializers.IntegerField(
        required=False,
        default=20,
        min_value=1,
        max_value=MAX_SPEND_LIMIT,
    )
    currency = serializers.CharField(
        required=False,
        min_length=3,
        max_length=3,
        trim_whitespace=True,
    )

    def validate_currency(self, value):
        value = value.strip().upper()
        if not value.isalpha():
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
