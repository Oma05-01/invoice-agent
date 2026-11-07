from collections.abc import Mapping
from rest_framework import serializers


class ApprovalCommentSerializer(serializers.Serializer):

    comment = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
    )


class ApprovalRejectionSerializer(serializers.Serializer):

    comment = serializers.CharField(
        max_length=2000,
        required=True,
        trim_whitespace=True,
    )

class ReturnToReviewSerializer(serializers.Serializer):

    return_reason = serializers.CharField(
        max_length=1000,
        required=True,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unknown_fields = (
                set(data.keys()) - set(self.fields.keys())
            )

            if unknown_fields:
                raise serializers.ValidationError({
                    "unknown_fields": (
                        f"Unsupported fields: "
                        f"{', '.join(sorted(unknown_fields))}"
                    )
                })

        return super().to_internal_value(data)

