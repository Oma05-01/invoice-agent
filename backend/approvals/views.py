
from django.db.models import Prefetch

from rest_framework import status
from rest_framework.authentication import (
    BasicAuthentication,
    SessionAuthentication,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from approvals.models import (
    ApprovalRequest,
    ApprovalDecision,
)
from approvals.serializers import (
    ApprovalCommentSerializer,
    ApprovalRejectionSerializer,
    ReturnToReviewSerializer,
)

from approvals.services import (
    APPROVER_ROLES,
    ApprovalPermissionError,
    ApprovalMakerCheckerError,
    ApprovalStateError,
    decide_approval_request,
     RETURN_TO_REVIEW_ROLES,
    ApprovalReturnPermissionError,
    return_rejected_invoice_to_review,
)

from invoices.models import Invoice
from organizations.models import OrganizationMembership


class ApprovalAPIView(APIView):

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
            .first()
        )

    def get_approver_access(self, request, organization_id):

        membership = self.get_membership(
            request,
            organization_id,
        )

        if membership is None:
            return None, Response(
                {"detail": "Organization not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if membership.role not in APPROVER_ROLES:
            return membership, Response(
                {"detail": "You are not authorized to access the approval queue."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return membership, None


def approval_request_summary(approval_request):
    invoice = approval_request.invoice
    vendor = invoice.vendor

    return {
        "id": str(approval_request.id),
        "status": approval_request.status,
        "submitted_by": {
            "id": str(approval_request.submitted_by_id),
            "username": approval_request.submitted_by.get_username(),
        },
        "submission_note": approval_request.submission_note,
        "submitted_at": approval_request.created_at.isoformat(),
        "invoice": {
            "id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "invoice_date": (
                invoice.invoice_date.isoformat()
                if invoice.invoice_date else None
            ),
            "currency": invoice.currency,
            "total_amount": (
                str(invoice.total_amount)
                if invoice.total_amount is not None else None
            ),
            "vendor": (
                {
                    "id": str(vendor.id),
                    "legal_name": vendor.legal_name,
                }
                if vendor else None
            ),
        },
    }


class ApprovalQueueAPIView(ApprovalAPIView):

    def get(self, request, organization_id):

        membership, error_response = self.get_approver_access(
            request,
            organization_id,
        )

        if error_response:
            return error_response

        approval_requests = (
            ApprovalRequest.objects
            .filter(
                organization_id=organization_id,
                status=ApprovalRequest.Status.PENDING,
            )
            .select_related(
                "submitted_by",
                "invoice",
                "invoice__vendor",
            )
            .order_by("created_at")
        )

        return Response(
            {
                "count": approval_requests.count(),
                "results": [
                    approval_request_summary(item)
                    for item in approval_requests
                ],
            },
            status=status.HTTP_200_OK,
        )


class ApprovalDetailAPIView(ApprovalAPIView):

    def get(
        self,
        request,
        organization_id,
        approval_request_id,
    ):

        membership, error_response = self.get_approver_access(
            request,
            organization_id,
        )

        if error_response:
            return error_response

        approval_request = (
            ApprovalRequest.objects
            .filter(
                pk=approval_request_id,
                organization_id=organization_id,
            )
            .select_related(
                "submitted_by",
                "invoice",
                "invoice__vendor",
                "invoice__source_document",
            )
            .first()
        )

        if approval_request is None:
            return Response(
                {"detail": "Approval request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        decision = (
            ApprovalDecision.objects
            .filter(approval_request=approval_request)
            .select_related("decided_by")
            .first()
        )

        invoice = approval_request.invoice
        vendor = invoice.vendor
        document = invoice.source_document

        return Response(
            {
                "approval_request": approval_request_summary(
                    approval_request
                ),
                "invoice": {
                    "status": invoice.status,
                    "description": invoice.description,
                    "financial_data": {
                        "subtotal": (
                            str(invoice.subtotal)
                            if invoice.subtotal is not None else None
                        ),
                        "tax_amount": (
                            str(invoice.tax_amount)
                            if invoice.tax_amount is not None else None
                        ),
                        "other_charges": (
                            str(invoice.other_charges)
                            if invoice.other_charges is not None else None
                        ),
                        "total_amount": (
                            str(invoice.total_amount)
                            if invoice.total_amount is not None else None
                        ),
                        "amount_due": (
                            str(invoice.amount_due)
                            if invoice.amount_due is not None else None
                        ),
                    },
                    "document": (
                        {
                            "id": str(document.id),
                            "filename": document.original_filename,
                            "status": document.status,
                            "content_type": document.content_type,
                        }
                        if document else None
                    ),
                },
                "decision": (
                    {
                        "id": str(decision.id),
                        "outcome": decision.outcome,
                        "comment": decision.comment,
                        "decided_by": {
                            "id": str(decision.decided_by_id),
                            "username": decision.decided_by.get_username(),
                        },
                        "decided_at": decision.decided_at.isoformat(),
                    }
                    if decision else None
                ),
            },
            status=status.HTTP_200_OK,
        )


class ApprovalDecisionAPIView(ApprovalAPIView):

    outcome = None
    serializer_class = None

    def post(
        self,
        request,
        organization_id,
        approval_request_id,
    ):

        membership, error_response = self.get_approver_access(
            request,
            organization_id,
        )

        if error_response:
            return error_response

        serializer = self.serializer_class(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        try:
            approval_request, decision, invoice = (
                decide_approval_request(
                    organization_id=organization_id,
                    approval_request_id=approval_request_id,
                    actor=request.user,
                    outcome=self.outcome,
                    comment=serializer.validated_data.get(
                        "comment",
                        "",
                    ),
                )
            )

        except ApprovalRequest.DoesNotExist:
            return Response(
                {"detail": "Approval request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except ApprovalPermissionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        except ApprovalMakerCheckerError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        except ApprovalStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "message": (
                    "Invoice approved successfully."
                    if self.outcome == ApprovalDecision.Outcome.APPROVED
                    else "Invoice rejected successfully."
                ),
                "approval_request_id": str(approval_request.id),
                "decision_id": str(decision.id),
                "decision": decision.outcome,
                "invoice_id": str(invoice.id),
                "invoice_status": invoice.status,
            },
            status=status.HTTP_200_OK,
        )


class ApproveInvoiceAPIView(ApprovalDecisionAPIView):

    outcome = ApprovalDecision.Outcome.APPROVED
    serializer_class = ApprovalCommentSerializer


class RejectInvoiceAPIView(ApprovalDecisionAPIView):

    outcome = ApprovalDecision.Outcome.REJECTED
    serializer_class = ApprovalRejectionSerializer


class ReturnRejectedInvoiceAPIView(ApprovalAPIView):

    def post(
        self,
        request,
        organization_id,
        approval_request_id,
    ):
        membership = self.get_membership(
            request,
            organization_id,
        )

        if membership is None:
            return Response(
                {"detail": "Organization not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if membership.role not in RETURN_TO_REVIEW_ROLES:
            return Response(
                {"detail": "You cannot return this invoice for review."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ReturnToReviewSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        try:
            invoice, approval_request, decision = (
                return_rejected_invoice_to_review(
                    organization_id=organization_id,
                    approval_request_id=approval_request_id,
                    actor=request.user,
                    return_reason=(
                        serializer.validated_data["return_reason"]
                    ),
                )
            )

        except ApprovalRequest.DoesNotExist:
            return Response(
                {"detail": "Approval request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except ApprovalReturnPermissionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        except ApprovalStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "message": "Invoice returned for review successfully.",
                "invoice_id": str(invoice.id),
                "invoice_status": invoice.status,
                "previous_approval_request_id": (
                    str(approval_request.id)
                ),
                "previous_approval_status": approval_request.status,
                "previous_decision_id": str(decision.id),
                "rejection_comment": decision.comment,
            },
            status=status.HTTP_200_OK,
        )
