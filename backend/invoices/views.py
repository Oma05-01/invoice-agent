import logging
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from rest_framework import status
from rest_framework.authentication import (
    BasicAuthentication,
    SessionAuthentication,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrganizationMembership

from documents.models import Document

from invoices.models import (
    Invoice,
    InvoiceValidationIssue,
)

from invoices.tasks import process_invoice_task


logger = logging.getLogger(__name__)


QUEUE_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_OPERATOR,
)


class OrganizationInvoiceAPIView(APIView):

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

    def get_invoice(self, organization_id, invoice_id):

        return (
            Invoice.objects
            .filter(
                pk=invoice_id,
                organization_id=organization_id,
            )
            .first()
        )


class InvoiceProcessingAPIView(OrganizationInvoiceAPIView):
    """
    Queue an uploaded invoice for background processing.
    """

    def post(
        self,
        request,
        organization_id,
        invoice_id,
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

        if membership.role not in QUEUE_ROLES:
            return Response(
                {"detail": "You cannot initiate invoice processing."},
                status=status.HTTP_403_FORBIDDEN,
            )

        task_id = uuid4()

        # Claim the invoice and commit its queued state before
        # publishing the Celery message.

        with transaction.atomic():

            invoice = (
                Invoice.objects
                .select_for_update()
                .filter(
                    pk=invoice_id,
                    organization_id=organization_id,
                )
                .first()
            )

            if invoice is None:
                return Response(
                    {"detail": "Invoice not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            allowed_invoice_statuses = {
                Invoice.Status.UPLOADED,
                Invoice.Status.FAILED,
            }

            if invoice.status not in allowed_invoice_statuses:
                return Response(
                    {
                        "detail": (
                            "Invoice cannot be queued from its "
                            f"current status: {invoice.status}."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            if not invoice.source_document_id:
                return Response(
                    {"detail": "Invoice has no source document."},
                    status=status.HTTP_409_CONFLICT,
                )

            document = (
                Document.objects
                .select_for_update()
                .filter(
                    pk=invoice.source_document_id,
                    organization_id=organization_id,
                )
                .first()
            )

            if document is None:
                return Response(
                    {"detail": "Source document not found."},
                    status=status.HTTP_409_CONFLICT,
                )

            allowed_document_statuses = {
                Document.Status.UPLOADED,
                Document.Status.FAILED,
            }

            if document.status not in allowed_document_statuses:
                return Response(
                    {
                        "detail": (
                            "Document cannot be queued from its "
                            f"current status: {document.status}."
                        )
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            # Update invoice state.

            invoice.status = Invoice.Status.QUEUED
            invoice.processing_task_id = task_id
            invoice.queued_at = timezone.now()

            invoice.save(
                update_fields=[
                    "status",
                    "processing_task_id",
                    "queued_at",
                    "updated_at",
                ]
            )

            # Update document state.

            document.status = Document.Status.QUEUED
            document.processing_error = ""

            document.save(
                update_fields=[
                    "status",
                    "processing_error",
                    "updated_at",
                ]
            )

        # The transaction has committed at this point.
        # Publishing after commit prevents workers from reading
        # uncommitted database records.

        try:

            process_invoice_task.apply_async(
                args=[
                    str(invoice.id),
                    str(task_id),
                ],
                task_id=str(task_id),
            )

        except Exception:

            logger.exception(
                "Unable to enqueue invoice task: %s",
                invoice.id,
            )

            error_message = (
                "Invoice could not be added to the processing queue. "
                "Please retry."
            )

            with transaction.atomic():

                Invoice.objects.filter(
                    pk=invoice.id,
                    status=Invoice.Status.QUEUED,
                    processing_task_id=task_id,
                ).update(
                    status=Invoice.Status.FAILED,
                )

                Document.objects.filter(
                    pk=document.id,
                    status=Document.Status.QUEUED,
                ).update(
                    status=Document.Status.FAILED,
                    processing_error=error_message,
                )

            return Response(
                {"detail": error_message},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "Invoice successfully queued for processing.",
                "invoice_id": str(invoice.id),
                "task_id": str(task_id),
                "status": Invoice.Status.QUEUED,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class InvoiceProcessingStatusAPIView(OrganizationInvoiceAPIView):
    """
    Retrieve the persisted status of an invoice.
    """

    def get(
        self,
        request,
        organization_id,
        invoice_id,
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

        invoice = self.get_invoice(
            organization_id,
            invoice_id,
        )

        if invoice is None:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        document = invoice.source_document

        issues = InvoiceValidationIssue.objects.filter(
            invoice=invoice,
        )

        return Response(
            {
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "status": invoice.status,
                "processing_task_id": (
                    str(invoice.processing_task_id)
                    if invoice.processing_task_id
                    else None
                ),
                "queued_at": (
                    invoice.queued_at.isoformat()
                    if invoice.queued_at
                    else None
                ),
                "document": {
                    "id": str(document.id),
                    "status": document.status,
                    "processing_error": document.processing_error,
                },
                "validation": {
                    "total_issues": issues.count(),
                    "open_issues": issues.filter(
                        status=InvoiceValidationIssue.Status.OPEN,
                    ).count(),
                },
                "financial_data": {
                    "currency": invoice.currency,
                    "subtotal": (
                        str(invoice.subtotal)
                        if invoice.subtotal is not None
                        else None
                    ),
                    "tax_amount": (
                        str(invoice.tax_amount)
                        if invoice.tax_amount is not None
                        else None
                    ),
                    "total_amount": (
                        str(invoice.total_amount)
                        if invoice.total_amount is not None
                        else None
                    ),
                    "amount_due": (
                        str(invoice.amount_due)
                        if invoice.amount_due is not None
                        else None
                    ),
                },
            }
        )

