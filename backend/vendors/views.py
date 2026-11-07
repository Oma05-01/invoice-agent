from django.db.models import Q

from rest_framework.authentication import (
    BasicAuthentication,
    SessionAuthentication,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrganizationMembership
from vendors.models import Vendor


class VendorListAPIView(APIView):
    """
    Return active vendors belonging to an organization.

    All active organization members can view the vendor list,
    including read-only members.
    """

    authentication_classes = [
        SessionAuthentication,
        BasicAuthentication,
    ]
    permission_classes = [IsAuthenticated]

    def get(self, request, organization_id):

        membership = OrganizationMembership.objects.filter(
            organization_id=organization_id,
            user=request.user,
            is_active=True,
        ).first()

        if membership is None:
            return Response(
                {
                    "detail": (
                        "Organization not found or access denied."
                    )
                },
                status=404,
            )

        queryset = Vendor.objects.filter(
            organization_id=organization_id,
            is_active=True,
        )

        search = request.query_params.get("search", "").strip()

        if search:
            queryset = queryset.filter(
                Q(legal_name__icontains=search)
                | Q(display_name__icontains=search)
                | Q(vendor_code__icontains=search)
                | Q(
                    tax_identification_number__icontains=search
                )
            )

        count = queryset.count()

        vendors = list(
            queryset.order_by("legal_name", "id")[:100]
        )

        results = [
            {
                "id": str(vendor.id),
                "legal_name": vendor.legal_name,
                "display_name": vendor.display_name or None,
                "vendor_code": vendor.vendor_code or None,
                "tax_identification_number": (
                    vendor.tax_identification_number or None
                ),
                "address": vendor.address or None,
            }
            for vendor in vendors
        ]

        return Response(
            {
                "count": count,
                "has_more": count > len(results),
                "results": results,
            }
        )