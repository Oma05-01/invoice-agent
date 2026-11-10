from django.db import IntegrityError, transaction
from django.db.models import Q

from rest_framework import status
from rest_framework.authentication import (
    BasicAuthentication,
    SessionAuthentication,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrganizationMembership
from vendors.models import Vendor
from vendors.serializers import VendorCreateSerializer


VENDOR_CREATE_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_OPERATOR,
)


class VendorListAPIView(APIView):
    """
    List active organization vendors and create new vendors.

    All active organization members can view the vendor list.
    Only authorized finance roles can create vendors.
    """

    authentication_classes = [
        SessionAuthentication,
        BasicAuthentication,
    ]

    permission_classes = [IsAuthenticated]

    def get_membership(self, request, organization_id):

        return (
            OrganizationMembership.objects
            .filter(
                organization_id=organization_id,
                user=request.user,
                is_active=True,
            )
            .select_related("organization")
            .first()
        )

    def get(self, request, organization_id):

        membership = self.get_membership(
            request,
            organization_id,
        )

        if membership is None:
            return Response(
                {
                    "detail": (
                        "Organization not found or access denied."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        queryset = Vendor.objects.filter(
            organization_id=organization_id,
            is_active=True,
        )

        search = request.query_params.get(
            "search",
            "",
        ).strip()

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

    def post(self, request, organization_id):

        membership = self.get_membership(
            request,
            organization_id,
        )

        if membership is None:
            return Response(
                {
                    "detail": (
                        "Organization not found or access denied."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if membership.role not in VENDOR_CREATE_ROLES:
            return Response(
                {
                    "detail": (
                        "You do not have permission to create vendors."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = VendorCreateSerializer(
            data=request.data,
            context={
                "organization": membership.organization,
            },
        )

        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                vendor = serializer.save(
                    organization_id=organization_id,
                )

        except IntegrityError as exc:

            constraint_name = getattr(
                getattr(exc.__cause__, "diag", None),
                "constraint_name",
                None,
            )

            if constraint_name == "unique_org_vendor_code":
                return Response(
                    {
                        "detail": (
                            "This vendor code is already in use "
                            "in this organization."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            raise

        return Response(
            {
                "message": "Vendor created successfully.",
                "vendor": VendorCreateSerializer(vendor).data,
            },
            status=status.HTTP_201_CREATED,
        )