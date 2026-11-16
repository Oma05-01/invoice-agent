from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from insights.serializers import SpendReportQuerySerializer
from insights.services.spend import SpendReportError, spend_by
from organizations.models import OrganizationMembership


class OrganizationInsightsAPIView(APIView):
    """Base view enforcing active organisation membership for Insights."""

    permission_classes = [IsAuthenticated]

    def get_membership(self, request, organization_id):
        membership = (
            OrganizationMembership.objects
            .select_related("organization")
            .filter(
                organization_id=organization_id,
                user=request.user,
                is_active=True,
                organization__is_active=True,
            )
            .first()
        )
        if membership is None:
            raise NotFound("Organization not found or access denied.")
        return membership


class SpendReportAPIView(OrganizationInsightsAPIView):
    """Return posted expenditure grouped by vendor, account, or month."""

    def get(self, request, organization_id):
        membership = self.get_membership(request, organization_id)

        query_serializer = SpendReportQuerySerializer(
            data=request.query_params,
        )
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        try:
            report = spend_by(
                membership.organization,
                dimension=filters["dimension"],
                start_date=filters["start_date"],
                end_date=filters["end_date"],
                limit=filters["limit"],
                currency=filters.get("currency"),
            )
        except SpendReportError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc

        return Response(report, status=status.HTTP_200_OK)
