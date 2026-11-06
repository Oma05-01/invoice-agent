import logging
import re

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from documents.models import Document
from documents.extraction import (
    extract_pdf_text,
    OCRRequiredError,
    DocumentExtractionError,
)

from vendors.models import Vendor

from invoices.models import (
    Invoice,
    InvoiceLineItem,
    InvoiceValidationIssue,
)

from invoices.schemas import InvoiceExtractionResult

from invoices.services.evidence import (
    verify_extraction_evidence,
)

from invoices.services.validation import (
    validate_invoice_extraction,
    ValidationFinding,
)

from invoices.services.provider_factory import (
    build_invoice_extraction_service,
)


logger = logging.getLogger(__name__)


class InvoiceProcessingError(Exception):
    """Base exception for invoice processing failures."""


class InvoiceProcessingStateError(InvoiceProcessingError):
    """Raised when an invoice cannot enter processing."""


def normalize_name(value: str) -> str:
    """Normalize supplier names for exact matching."""

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip().casefold()


def _claim_invoice(invoice_id):
    """
    Atomically claim an invoice for processing.

    Prevents already-processing or already-reviewed invoices
    from being processed again accidentally.
    """

    with transaction.atomic():

        invoice = (
            Invoice.objects
            .select_for_update()
            .get(pk=invoice_id)
        )

        allowed_statuses = {
            Invoice.Status.UPLOADED,
            Invoice.Status.QUEUED,
            Invoice.Status.FAILED,
        }

        if invoice.status not in allowed_statuses:
            raise InvoiceProcessingStateError(
                f"Invoice cannot be processed from status "
                f"'{invoice.status}'."
            )

        if not invoice.source_document_id:
            raise InvoiceProcessingError(
                "Invoice has no associated source document."
            )

        document = (
            Document.objects
            .select_for_update()
            .get(
                pk=invoice.source_document_id,
                organization_id=invoice.organization_id,
            )
        )

        allowed_document_statuses = {
            Document.Status.UPLOADED,
            Document.Status.QUEUED,
            Document.Status.FAILED,
        }

        if document.status not in allowed_document_statuses:
            raise InvoiceProcessingStateError(
                f"Source document cannot be processed from "
                f"status '{document.status}'."
            )

        invoice.status = Invoice.Status.EXTRACTING
        invoice.save(update_fields=["status", "updated_at"])

        document.status = Document.Status.PROCESSING
        document.processing_error = ""

        document.save(
            update_fields=[
                "status",
                "processing_error",
                "updated_at",
            ]
        )

        return invoice.id, document.id


def _read_document(document):
    """
    Read and extract a supported searchable PDF.

    Image OCR and mixed scanned/searchable PDFs are deferred
    until the OCR pipeline is implemented.
    """

    if document.content_type != "application/pdf":
        raise OCRRequiredError(
            "This document requires image/OCR processing, "
            "which is not yet implemented."
        )

    document.file.open("rb")

    try:
        content = document.file.read()

    finally:
        document.file.close()

    extraction_result = extract_pdf_text(content)

    if extraction_result.pages_requiring_ocr:
        pages = ", ".join(
            str(page)
            for page in extraction_result.pages_requiring_ocr
        )

        raise OCRRequiredError(
            f"OCR is required for PDF pages: {pages}."
        )

    return extraction_result


def _match_supplier(
    organization_id,
    extraction: InvoiceExtractionResult,
):
    """
    Match an extracted supplier against existing active vendors.

    No supplier is automatically created.
    Ambiguous or conflicting matches require human review.
    """

    findings = []

    suppliers = list(
        Vendor.objects.filter(
            organization_id=organization_id,
            is_active=True,
        )
    )

    supplier_name = extraction.supplier_legal_name

    if not supplier_name:

        return None, [
            ValidationFinding(
                code="UNKNOWN_VENDOR",
                severity="warning",
                field_name="supplier_legal_name",
                message="Supplier identification information is missing.",
            )
        ]

    normalized_name = normalize_name(supplier_name)

    # First attempt an exact TIN match.

    if extraction.supplier_tin:

        tin_matches = [
            vendor
            for vendor in suppliers
            if (
                vendor.tax_identification_number.strip()
                and vendor.tax_identification_number.strip().casefold()
                == extraction.supplier_tin.strip().casefold()
            )
        ]

        if len(tin_matches) == 1:

            vendor = tin_matches[0]

            known_names = {
                normalize_name(vendor.legal_name),
                normalize_name(vendor.display_name)
                if vendor.display_name else "",
            }

            if normalized_name not in known_names:

                findings.append(
                    ValidationFinding(
                        code="SUPPLIER_NAME_MISMATCH",
                        severity="warning",
                        field_name="supplier_legal_name",
                        message=(
                            "Supplier TIN matches an existing vendor, "
                            "but the extracted supplier name differs."
                        ),
                    )
                )

            return vendor, findings

        if len(tin_matches) > 1:

            return None, [
                ValidationFinding(
                    code="AMBIGUOUS_VENDOR",
                    severity="warning",
                    field_name="supplier_tin",
                    message=(
                        "Multiple existing vendors match "
                        "the extracted supplier TIN."
                    ),
                )
            ]

    # Fall back to an exact normalized name match.

    name_matches = []

    for vendor in suppliers:

        known_names = {
            normalize_name(vendor.legal_name),
        }

        if vendor.display_name:
            known_names.add(
                normalize_name(vendor.display_name)
            )

        if normalized_name in known_names:
            name_matches.append(vendor)

    if len(name_matches) == 1:

        vendor = name_matches[0]

        if (
            extraction.supplier_tin
            and vendor.tax_identification_number
            and (
                extraction.supplier_tin.strip().casefold()
                != vendor.tax_identification_number.strip().casefold()
            )
        ):

            return None, [
                ValidationFinding(
                    code="SUPPLIER_TIN_MISMATCH",
                    severity="warning",
                    field_name="supplier_tin",
                    message=(
                        "Supplier name matches an existing vendor, "
                        "but the extracted TIN differs from "
                        "the registered TIN."
                    ),
                )
            ]

        return vendor, findings

    if len(name_matches) > 1:

        return None, [
            ValidationFinding(
                code="AMBIGUOUS_VENDOR",
                severity="warning",
                field_name="supplier_legal_name",
                message=(
                    "Multiple existing vendors match "
                    "the extracted supplier name."
                ),
            )
        ]

    return None, [
        ValidationFinding(
            code="UNKNOWN_VENDOR",
            severity="warning",
            field_name="supplier_legal_name",
            message=(
                "No existing vendor matches the extracted supplier."
            ),
        )
    ]


def _calculate_tax_amount(extraction):
    """
    Calculate the known additive/included tax total.

    Return None if the tax information is incomplete.
    """

    if extraction.taxes is None:
        return None

    for tax in extraction.taxes:

        if (
            tax.amount is None
            or tax.treatment == "unknown"
        ):
            return None

    return sum(
        (
            tax.amount
            for tax in extraction.taxes
            if tax.treatment in ("added", "included")
        ),
        Decimal("0"),
    )


def _persist_extraction(
    invoice_id,
    document_id,
    extraction,
    vendor,
    findings,
):
    """
    Persist the extraction and all associated findings atomically.
    """

    with transaction.atomic():

        invoice = (
            Invoice.objects
            .select_for_update()
            .get(pk=invoice_id)
        )

        if invoice.status != Invoice.Status.EXTRACTING:
            raise InvoiceProcessingStateError(
                "Invoice processing state changed unexpectedly."
            )

        document = (
            Document.objects
            .select_for_update()
            .get(pk=document_id)
        )

        if document.status != Document.Status.PROCESSING:
            raise InvoiceProcessingStateError(
                "Document processing state changed unexpectedly."
            )

        # Preserve the original extraction as structured JSON.

        invoice.extracted_data = extraction.model_dump(
            mode="json"
        )

        invoice.field_confidence = (
            extraction.field_confidence or {}
        )

        # Populate invoice header fields.

        invoice.vendor = vendor

        invoice.invoice_number = (
            extraction.invoice_number or ""
        )

        invoice.invoice_date = (
            date.fromisoformat(extraction.invoice_date)
            if extraction.invoice_date
            else None
        )

        invoice.due_date = (
            date.fromisoformat(extraction.due_date)
            if extraction.due_date
            else None
        )

        invoice.currency = extraction.currency

        invoice.subtotal = extraction.subtotal

        invoice.tax_amount = _calculate_tax_amount(
            extraction
        )

        invoice.other_charges = extraction.other_charges

        invoice.total_amount = extraction.total_amount

        invoice.amount_due = extraction.amount_due

        invoice.description = extraction.description or ""

        # All successfully extracted invoices still require
        # an accountant's review.

        invoice.status = Invoice.Status.NEEDS_REVIEW

        invoice.save()

        # Create line items.

        line_items = [
            InvoiceLineItem(
                invoice=invoice,
                position=position,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate_percent,
                line_total=item.line_total,
                suggested_category=(
                    item.suggested_expense_category or ""
                ),
            )
            for position, item in enumerate(
                extraction.line_items or [],
                start=1,
            )
        ]

        if line_items:
            InvoiceLineItem.objects.bulk_create(
                line_items
            )

        # Persist financial and evidence findings.

        issues = [
            InvoiceValidationIssue(
                invoice=invoice,
                code=finding.code,
                severity=finding.severity,
                field_name=finding.field_name,
                message=finding.message,
                details=finding.details,
            )
            for finding in findings
        ]

        if issues:
            InvoiceValidationIssue.objects.bulk_create(
                issues
            )

        # Document processing succeeded, even if the invoice
        # has validation issues requiring accountant attention.

        document.status = Document.Status.PROCESSED
        document.processing_error = ""

        document.save(
            update_fields=[
                "status",
                "processing_error",
                "updated_at",
            ]
        )

        return invoice


def _mark_processing_failed(
    invoice_id,
    document_id,
    exception,
):
    """
    Record a processing failure without exposing document contents
    or provider credentials.
    """

    error_message = (
        f"{type(exception).__name__}: {str(exception)[:1000]}"
    )

    with transaction.atomic():

        invoice = (
            Invoice.objects
            .select_for_update()
            .get(pk=invoice_id)
        )

        document = (
            Document.objects
            .select_for_update()
            .get(pk=document_id)
        )

        if invoice.status == Invoice.Status.EXTRACTING:

            invoice.status = Invoice.Status.FAILED

            invoice.save(
                update_fields=["status", "updated_at"]
            )

        if document.status == Document.Status.PROCESSING:

            document.status = Document.Status.FAILED
            document.processing_error = error_message

            document.save(
                update_fields=[
                    "status",
                    "processing_error",
                    "updated_at",
                ]
            )


def process_invoice(
    invoice_id,
    extraction_service=None,
):
    """
    Process an uploaded invoice from document ingestion
    through extraction, verification and persistence.

    An extraction service can be injected for automated tests.
    Otherwise, the configured live Groq service is used.
    """

    invoice_id, document_id = _claim_invoice(invoice_id)

    try:

        document = Document.objects.get(
            pk=document_id
        )

        # 1. Extract searchable PDF text.

        document_result = _read_document(document)

        # 2. Build the configured real Groq service,
        # unless a service was explicitly injected.

        if extraction_service is None:

            extraction_service = (
                build_invoice_extraction_service()
            )

        # 3. Extract structured invoice information.

        extraction = extraction_service.extract(
            document_text=document_result.text
        )

        # 4. Verify source evidence.

        evidence_findings = verify_extraction_evidence(
            extraction,
            document_result.page_texts,
        )

        # 5. Run deterministic financial validation.

        financial_findings = validate_invoice_extraction(
            extraction
        )

        # 6. Match the supplier against registered vendors.

        vendor, vendor_findings = _match_supplier(
            document.organization_id,
            extraction,
        )

        all_findings = (
            evidence_findings
            + financial_findings
            + vendor_findings
        )

        # 7. Persist all processing results atomically.

        return _persist_extraction(
            invoice_id=invoice_id,
            document_id=document_id,
            extraction=extraction,
            vendor=vendor,
            findings=all_findings,
        )

    except Exception as exc:

        logger.exception(
            "Invoice processing failed. Invoice ID: %s",
            invoice_id,
        )

        try:
            _mark_processing_failed(
                invoice_id,
                document_id,
                exc,
            )

        except Exception:

            logger.exception(
                "Could not persist invoice processing failure. "
                "Invoice ID: %s",
                invoice_id,
            )

        raise