from rest_framework import serializers

from vendors.models import Vendor


class VendorCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Vendor

        fields = (
            "id",
            "legal_name",
            "display_name",
            "vendor_code",
            "tax_identification_number",
            "email",
            "phone",
            "address",
        )

        read_only_fields = ("id",)

    def validate_legal_name(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "The legal name is required."
            )

        organization = self.context["organization"]

        if Vendor.objects.filter(
            organization=organization,
            legal_name__iexact=value,
        ).exists():
            raise serializers.ValidationError(
                "A vendor with this legal name already exists "
                "in this organization."
            )

        return value

    def validate_display_name(self, value):
        return value.strip() if value else ""

    def validate_vendor_code(self, value):
        value = value.strip() if value else ""

        if value:
            organization = self.context["organization"]

            if Vendor.objects.filter(
                organization=organization,
                vendor_code__iexact=value,
            ).exists():
                raise serializers.ValidationError(
                    "This vendor code is already in use."
                )

        return value

    def validate_tax_identification_number(self, value):
        value = value.strip() if value else ""

        if value:
            organization = self.context["organization"]

            if Vendor.objects.filter(
                organization=organization,
                tax_identification_number__iexact=value,
            ).exists():
                raise serializers.ValidationError(
                    "A vendor with this TIN already exists "
                    "in this organization."
                )

        return value

