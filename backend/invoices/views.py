import logging
from uuid import uuid4

from django.db import transaction
from django.utils import timezone

from django.db.models import Q
from django.utils.dateparse import parse_date

from rest_framework.pagination import PageNumberPagination

from rest_framework import status
from rest_framework.authentication import (
    BasicAuthentication,
    SessionAuthentication,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from invoices.serializers import InvoiceHeaderCorrectionSerializer
from organizations.models import OrganizationMembership
from documents.models import Document

from invoices.models import (
    Invoice,
    InvoiceValidationIssue,OutboxEvent, InvoiceLineItem
)

from invoices.services.review import (
    correct_invoice_header,
    InvoiceReviewStateError,
    InvoiceCorrectionNoChanges,
)

from invoices.serializers import (VendorResolutionSerializer, InvoiceLineItemCorrectionSerializer,
    InvoiceLineItemDeleteSerializer, InvoiceValidationIssueIgnoreSerializer, InvoiceReviewSubmissionSerializer)

from invoices.services.review import (assign_invoice_vendor,
    add_invoice_line_item,
    submit_invoice_for_approval,
    update_invoice_line_item,
    delete_invoice_line_item,
    ignore_invoice_validation_issue,
    InvoiceIssueDecisionError,
    InvoiceIssueNotIgnorable,
)

from vendors.models import Vendor

from auditlog.models import InvoiceAuditEvent
from auditlog.services import record_invoice_event


logger = logging.getLogger(__name__)


QUEUE_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_OPERATOR,
)

ISSUE_DECISION_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_REVIEWER,
)

VENDOR_RESOLUTION_ROLES = (
    *QUEUE_ROLES,
    OrganizationMembership.Role.FINANCE_REVIEWER,
)

def line_item_response_data(item):
    return {
        "id": str(item.id),
        "position": item.position,
        "description": item.description,
        "quantity": (
            str(item.quantity)
            if item.quantity is not None else None
        ),
        "unit_price": (
            str(item.unit_price)
            if item.unit_price is not None else None
        ),
        "tax_rate": (
            str(item.tax_rate)
            if item.tax_rate is not None else None
        ),
        "line_total": (
            str(item.line_total)
            if item.line_total is not None else None
        ),
        "suggested_category": item.suggested_category,
        "ledger_code": item.ledger_code,
    }


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
    # Persist invoice, document and outbox event atomically.
    # The separate dispatcher publishes the event after commit.

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

            previous_invoice_status = invoice.status

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

            previous_document_status = document.status

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

            outbox_event = OutboxEvent.objects.create(
                event_type="invoice.process",
                aggregate_id=invoice.id,

                idempotency_key=(
                    f"invoice.process:{invoice.id}:{task_id}"
                ),

                payload={
                    "invoice_id": str(invoice.id),
                    "task_id": str(task_id),
                },
            )

            record_invoice_event(
                invoice=invoice,
                actor=request.user,
                action=InvoiceAuditEvent.Action.PROCESSING_QUEUED,
                changes={
                    "invoice_status": {
                        "before": previous_invoice_status,
                        "after": Invoice.Status.QUEUED,
                    },
                    "document_status": {
                        "before": previous_document_status,
                        "after": Document.Status.QUEUED,
                    },
                },
                metadata={
                    "task_id": str(task_id),
                    "outbox_event_id": str(outbox_event.id),
                },
            )

        return Response(
            {
                "message": (
                    "Invoice successfully queued for processing."
                ),
                "invoice_id": str(invoice.id),
                "task_id": str(task_id),
                "outbox_event_id": str(outbox_event.id),
                "status": Invoice.Status.QUEUED,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class InvoiceListPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class InvoiceListAPIView(OrganizationInvoiceAPIView):

    def get(self, request, organization_id):

        membership = self.get_membership(
            request,
            organization_id,
        )

        if membership is None:
            return Response(
                {"detail": "Organization not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        queryset = (
            Invoice.objects
            .filter(organization_id=organization_id)
            .select_related("vendor", "source_document")
            .order_by("-created_at", "-id")
        )

        # Search by invoice number or supplier name.
        search = request.query_params.get("search", "").strip()

        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search)
                | Q(vendor__legal_name__icontains=search)
                | Q(vendor__display_name__icontains=search)
            )

        # Filter by invoice status.
        status_filter = request.query_params.get("status", "").strip()

        if status_filter:
            valid_statuses = {
                value for value, _ in Invoice.Status.choices
            }

            if status_filter not in valid_statuses:
                return Response(
                    {
                        "status": [
                            "Invalid invoice status."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            queryset = queryset.filter(status=status_filter)

        # Parse optional date filters.
        date_from_raw = request.query_params.get(
            "invoice_date_from"
        )

        date_to_raw = request.query_params.get(
            "invoice_date_to"
        )

        date_from = None
        date_to = None

        if date_from_raw:
            date_from = parse_date(date_from_raw)

            if date_from is None:
                return Response(
                    {
                        "invoice_date_from": [
                            "Use the YYYY-MM-DD date format."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if date_to_raw:
            date_to = parse_date(date_to_raw)

            if date_to is None:
                return Response(
                    {
                        "invoice_date_to": [
                            "Use the YYYY-MM-DD date format."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if date_from and date_to and date_from > date_to:
            return Response(
                {
                    "detail": (
                        "invoice_date_from cannot be after "
                        "invoice_date_to."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if date_from:
            queryset = queryset.filter(
                invoice_date__gte=date_from
            )

        if date_to:
            queryset = queryset.filter(
                invoice_date__lte=date_to
            )

        # Paginate results.
        paginator = InvoiceListPagination()

        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )

        results = []

        for invoice in page:

            vendor = invoice.vendor
            document = invoice.source_document

            results.append(
                {
                    "id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "vendor": (
                        {
                            "id": str(vendor.id),
                            "name": (
                                vendor.display_name
                                or vendor.legal_name
                            ),
                        }
                        if vendor
                        else None
                    ),
                    "invoice_date": (
                        invoice.invoice_date.isoformat()
                        if invoice.invoice_date
                        else None
                    ),
                    "due_date": (
                        invoice.due_date.isoformat()
                        if invoice.due_date
                        else None
                    ),
                    "currency": invoice.currency,
                    "subtotal": (
                        str(invoice.subtotal)
                        if invoice.subtotal is not None
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
                    "status": invoice.status,
                    "document": (
                        {
                            "id": str(document.id),
                            "filename": document.original_filename,
                            "status": document.status,
                        }
                        if document
                        else None
                    ),
                    "created_at": invoice.created_at.isoformat(),
                }
            )

        return paginator.get_paginated_response(results)
     

class InvoiceProcessingStatusAPIView(OrganizationInvoiceAPIView):  

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
                "document": (
                    None
                    if document is None
                    else {
                        "id": str(document.id),
                        "status": document.status,
                        "processing_error": document.processing_error,
                    }
                ),
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


class InvoiceReviewDetailAPIView(OrganizationInvoiceAPIView):
    """
    Return the complete read-only invoice review workspace.

    Accessible to active organization members, including
    finance reviewers and read-only members.
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

        invoice = (
            Invoice.objects
            .select_related(
                "vendor",
                "source_document",
            )
            .prefetch_related(
                "line_items",
                "validation_issues",
            )
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

        # Preserve the original AI extraction separately
        # from the operational invoice fields.

        extraction = invoice.extracted_data or {}

        # -------------------------------------------------
        # Supplier information
        # -------------------------------------------------

        vendor = invoice.vendor

        matched_vendor = None

        if vendor is not None:
            matched_vendor = {
                "id": str(vendor.id),
                "legal_name": vendor.legal_name,
                "display_name": vendor.display_name,
                "tax_identification_number": (
                    vendor.tax_identification_number
                ),
                "email": vendor.email,
            }

        extracted_supplier = {
            "legal_name": extraction.get(
                "supplier_legal_name"
            ),
            "tax_identification_number": extraction.get(
                "supplier_tin"
            ),
            "address": extraction.get(
                "supplier_address"
            ),
        }

        # -------------------------------------------------
        # Source document
        # -------------------------------------------------

        document = invoice.source_document

        document_data = None

        if document is not None:
            document_data = {
                "id": str(document.id),
                "filename": document.original_filename,
                "content_type": document.content_type,
                "file_size": document.file_size,
                "sha256": document.sha256,
                "source": document.source,
                "status": document.status,
                "processing_error": document.processing_error,
                "uploaded_at": document.created_at.isoformat(),
            }

        # -------------------------------------------------
        # Operational invoice fields
        # -------------------------------------------------

        invoice_data = {
            "id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "invoice_date": (
                invoice.invoice_date.isoformat()
                if invoice.invoice_date else None
            ),
            "due_date": (
                invoice.due_date.isoformat()
                if invoice.due_date else None
            ),
            "currency": invoice.currency,
            "description": invoice.description,
            "status": invoice.status,
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
            "created_at": invoice.created_at.isoformat(),
            "updated_at": invoice.updated_at.isoformat(),
        }

        # -------------------------------------------------
        # Invoice line items
        # -------------------------------------------------

        line_items = [
            {
                "id": str(item.id),
                "position": item.position,
                "description": item.description,
                "quantity": (
                    str(item.quantity)
                    if item.quantity is not None else None
                ),
                "unit_price": (
                    str(item.unit_price)
                    if item.unit_price is not None else None
                ),
                "tax_rate": (
                    str(item.tax_rate)
                    if item.tax_rate is not None else None
                ),
                "line_total": (
                    str(item.line_total)
                    if item.line_total is not None else None
                ),
                "suggested_category": item.suggested_category,
                "ledger_code": item.ledger_code,
            }
            for item in invoice.line_items.all()
        ]

        # -------------------------------------------------
        # Validation issues
        # -------------------------------------------------

        issues = list(invoice.validation_issues.all())

        validation_issues = [
            {
                "id": str(issue.id),
                "code": issue.code,
                "severity": issue.severity,
                "field_name": issue.field_name,
                "message": issue.message,
                "details": issue.details,
                "status": issue.status,
                "resolved_by_id": (
                    str(issue.resolved_by_id)
                    if issue.resolved_by_id else None
                ),
                "resolved_at": (
                    issue.resolved_at.isoformat()
                    if issue.resolved_at else None
                ),
                "created_at": issue.created_at.isoformat(),
            }
            for issue in issues
        ]

        # -------------------------------------------------
        # Audit history
        # -------------------------------------------------

        audit_events = (
            InvoiceAuditEvent.objects
            .filter(
                invoice=invoice,
                organization_id=organization_id,
            )
            .select_related("actor")
            .order_by("-created_at")[:50]
        )

        audit_history = [
            {
                "id": str(event.id),
                "action": event.action,
                "actor": (
                    {
                        "id": str(event.actor_id),
                        "username": event.actor.get_username(),
                    }
                    if event.actor else None
                ),
                "changes": event.changes,
                "metadata": event.metadata,
                "created_at": event.created_at.isoformat(),
            }
            for event in audit_events
        ]

        # -------------------------------------------------
        # Review response
        # -------------------------------------------------

        return Response(
            {
                "invoice": invoice_data,
                "supplier": {
                    "matched_vendor": matched_vendor,
                    "extracted_supplier": extracted_supplier,
                },
                "document": document_data,
                "extraction": {
                    "original_data": extraction,
                    "field_confidence": (
                        invoice.field_confidence or {}
                    ),
                    "field_evidence": extraction.get(
                        "field_evidence",
                        {},
                    ),
                    "warnings": extraction.get(
                        "extraction_warnings",
                        [],
                    ),
                },
                "line_items": line_items,
                "validation": {
                    "total_issues": len(issues),
                    "open_issues": sum(
                        issue.status == InvoiceValidationIssue.Status.OPEN
                        for issue in issues
                    ),
                    "resolved_issues": sum(
                        issue.status == InvoiceValidationIssue.Status.RESOLVED
                        for issue in issues
                    ),
                    "ignored_issues": sum(
                        issue.status == InvoiceValidationIssue.Status.IGNORED
                        for issue in issues
                    ),
                    "issues": validation_issues,
                },
                "audit_history": audit_history,
            }
        )

    def patch(
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
                {"detail": "You cannot correct this invoice."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InvoiceHeaderCorrectionSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        validated_data = dict(serializer.validated_data)

        correction_reason = validated_data.pop(
            "correction_reason"
        )

        try:
            invoice, changes, findings = correct_invoice_header(
                organization_id=organization_id,
                invoice_id=invoice_id,
                actor=request.user,
                corrections=validated_data,
                correction_reason=correction_reason,
            )

        except Invoice.DoesNotExist:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceReviewStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        except InvoiceCorrectionNoChanges as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        issues = invoice.validation_issues.all()

        return Response(
            {
                "message": "Invoice corrections saved successfully.",
                "invoice_id": str(invoice.id),
                "status": invoice.status,
                "updated_fields": list(changes.keys()),
                "validation": {
                    "total_issues": issues.count(),
                    "open_issues": issues.filter(
                        status=InvoiceValidationIssue.Status.OPEN,
                    ).count(),
                    "new_validation_findings": len(findings),
                },
            },
            status=status.HTTP_200_OK,
        )

class InvoiceVendorResolutionAPIView(OrganizationInvoiceAPIView):

    def patch(
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

        if membership.role not in VENDOR_RESOLUTION_ROLES:
            return Response(
                {"detail": "You cannot resolve this invoice vendor."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = VendorResolutionSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        try:
            invoice, vendor, resolved_issue_ids = (
                assign_invoice_vendor(
                    organization_id=organization_id,
                    invoice_id=invoice_id,
                    vendor_id=serializer.validated_data["vendor_id"],
                    actor=request.user,
                    correction_reason=(
                        serializer.validated_data["correction_reason"]
                    ),
                )
            )

        except Invoice.DoesNotExist:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Vendor.DoesNotExist:
            return Response(
                {
                    "detail": (
                        "Active vendor not found in this organization."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceReviewStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        except InvoiceCorrectionNoChanges as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Invoice vendor assigned successfully.",
                "invoice_id": str(invoice.id),
                "vendor": {
                    "id": str(vendor.id),
                    "legal_name": vendor.legal_name,
                    "display_name": vendor.display_name,
                },
                "resolved_issue_ids": resolved_issue_ids,
            },
            status=status.HTTP_200_OK,
        )

class InvoiceLineItemCollectionAPIView(OrganizationInvoiceAPIView):

    def post(self, request, organization_id, invoice_id):

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
                {"detail": "You cannot modify invoice line items."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InvoiceLineItemCorrectionSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        corrections = dict(serializer.validated_data)
        correction_reason = corrections.pop("correction_reason")

        if "description" not in corrections:
            return Response(
                {"description": ["This field is required when adding a line item."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            item, findings, resolved_ids = add_invoice_line_item(
                organization_id=organization_id,
                invoice_id=invoice_id,
                actor=request.user,
                corrections=corrections,
                correction_reason=correction_reason,
            )

        except Invoice.DoesNotExist:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceReviewStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "message": "Invoice line item added successfully.",
                "line_item": line_item_response_data(item),
                "validation": {
                    "new_findings": len(findings),
                    "automatically_resolved_issue_ids": resolved_ids,
                },
            },
            status=status.HTTP_201_CREATED,
        )

class InvoiceLineItemDetailAPIView(OrganizationInvoiceAPIView):

    def get_authorized_membership(self, request, organization_id):

        membership = self.get_membership(
            request,
            organization_id,
        )

        if membership is None:
            return None, Response(
                {"detail": "Organization not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if membership.role not in QUEUE_ROLES:
            return membership, Response(
                {"detail": "You cannot modify invoice line items."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return membership, None

    def patch(
        self,
        request,
        organization_id,
        invoice_id,
        line_item_id,
    ):

        membership, error_response = self.get_authorized_membership(
            request,
            organization_id,
        )

        if error_response:
            return error_response

        serializer = InvoiceLineItemCorrectionSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        corrections = dict(serializer.validated_data)
        correction_reason = corrections.pop("correction_reason")

        try:
            item, findings, resolved_ids = update_invoice_line_item(
                organization_id=organization_id,
                invoice_id=invoice_id,
                line_item_id=line_item_id,
                actor=request.user,
                corrections=corrections,
                correction_reason=correction_reason,
            )

        except Invoice.DoesNotExist:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceLineItem.DoesNotExist:
            return Response(
                {"detail": "Invoice line item not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceReviewStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        except InvoiceCorrectionNoChanges as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Invoice line item updated successfully.",
                "line_item": line_item_response_data(item),
                "validation": {
                    "new_findings": len(findings),
                    "automatically_resolved_issue_ids": resolved_ids,
                },
            },
            status=status.HTTP_200_OK,
        )

    def delete(
        self,
        request,
        organization_id,
        invoice_id,
        line_item_id,
    ):

        membership, error_response = self.get_authorized_membership(
            request,
            organization_id,
        )

        if error_response:
            return error_response

        serializer = InvoiceLineItemDeleteSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        try:
            item_id, findings, resolved_ids = delete_invoice_line_item(
                organization_id=organization_id,
                invoice_id=invoice_id,
                line_item_id=line_item_id,
                actor=request.user,
                correction_reason=(
                    serializer.validated_data["correction_reason"]
                ),
            )

        except Invoice.DoesNotExist:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceLineItem.DoesNotExist:
            return Response(
                {"detail": "Invoice line item not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceReviewStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "message": "Invoice line item deleted successfully.",
                "line_item_id": item_id,
                "validation": {
                    "new_findings": len(findings),
                    "automatically_resolved_issue_ids": resolved_ids,
                },
            },
            status=status.HTTP_200_OK,
        )

class InvoiceValidationIssueIgnoreAPIView(OrganizationInvoiceAPIView):

    def post(
        self,
        request,
        organization_id,
        invoice_id,
        issue_id,
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

        if membership.role not in ISSUE_DECISION_ROLES:
            return Response(
                {"detail": "You cannot acknowledge validation issues."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InvoiceValidationIssueIgnoreSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        try:
            issue = ignore_invoice_validation_issue(
                organization_id=organization_id,
                invoice_id=invoice_id,
                issue_id=issue_id,
                actor=request.user,
                decision_reason=(
                    serializer.validated_data["decision_reason"]
                ),
            )

        except Invoice.DoesNotExist:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceValidationIssue.DoesNotExist:
            return Response(
                {"detail": "Validation issue not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceReviewStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        except InvoiceIssueDecisionError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        except InvoiceIssueNotIgnorable as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Validation issue acknowledged successfully.",
                "issue": {
                    "id": str(issue.id),
                    "code": issue.code,
                    "severity": issue.severity,
                    "status": issue.status,
                    "decision_reason": issue.decision_reason,
                    "resolved_by_id": str(issue.resolved_by_id),
                    "resolved_at": issue.resolved_at.isoformat(),
                },
            },
            status=status.HTTP_200_OK,
        )
    
class InvoiceReviewSubmissionAPIView(OrganizationInvoiceAPIView):

    def post(self, request, organization_id, invoice_id):

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
                {"detail": "You cannot submit this invoice for approval."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InvoiceReviewSubmissionSerializer(
            data=request.data,
        )

        serializer.is_valid(raise_exception=True)

        try:
            invoice, submitted, blockers, resolved_ids, approval_request = (
                submit_invoice_for_approval(
                    organization_id=organization_id,
                    invoice_id=invoice_id,
                    actor=request.user,
                    submission_note=(
                        serializer.validated_data.get(
                            "submission_note",
                            "",
                        )
                    ),
                )
            )

        except Invoice.DoesNotExist:
            return Response(
                {"detail": "Invoice not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except InvoiceReviewStateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )

        if not submitted:
            return Response(
                {
                    "message": (
                        "Invoice cannot be submitted until "
                        "the review blockers are addressed."
                    ),
                    "invoice_id": str(invoice.id),
                    "status": invoice.status,
                    "blockers": blockers,
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "message": "Invoice successfully submitted for approval.",
                "invoice_id": str(invoice.id),
                "approval_request_id": str(approval_request.id),
                "status": invoice.status,
                "automatically_resolved_issue_ids": resolved_ids,
            },
            status=status.HTTP_200_OK,
        )