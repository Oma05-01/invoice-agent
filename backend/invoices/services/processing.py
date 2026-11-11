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
from auditlog.models import InvoiceAuditEvent
from vendors.models import Vendor

from invoices.models import (
    Invoice,
    InvoiceLineItem,
    InvoiceTaxComponent,
    InvoiceChargeComponent,
    InvoiceValidationIssue,
)

from invoices.schemas import InvoiceExtractionResult

from invoices.services.evidence import (
    verify_extraction_evidence,
)

from invoices.services.payment_terms import (
    normalize_payment_terms,
    resolve_due_date,
)

from invoices.services.validation import (
    validate_invoice_extraction,
    ValidationFinding,
)

from invoices.services.provider_factory import (
    build_invoice_extraction_service,
)
from invoices.services.invoice_number_recovery import (
    recover_split_invoice_number,
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


SUPPLIER_NAME_SUFFIXES = {
    "ltd",
    "limited",
    "llc",
    "plc",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "company",
    "co",
    "invoice",
}


def _supplier_name_tokens(value: str) -> list[str]:
    """
    Convert a supplier name into ordered comparison tokens.

    Remove terminal legal suffixes and document labels,
    while preserving the original order of meaningful words.
    """

    tokens = re.findall(
        r"[a-z0-9]+",
        value.casefold(),
    )

    while tokens and tokens[-1] in SUPPLIER_NAME_SUFFIXES:
        tokens.pop()

    return tokens


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

    Matching priority:
    1. Exact TIN.
    2. Exact normalized legal/display name.
    3. Unique, sufficiently distinctive ordered name prefix.

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
                message=(
                    "Supplier identification information is missing."
                ),
            )
        ], None

    normalized_name = normalize_name(supplier_name)

    # ---------------------------------------------------------
    # 1. Exact TIN matching takes priority.
    # ---------------------------------------------------------

    if extraction.supplier_tin:

        extracted_tin = extraction.supplier_tin.strip().casefold()

        tin_matches = [
            vendor
            for vendor in suppliers
            if (
                vendor.tax_identification_number.strip()
                and (
                    vendor.tax_identification_number.strip().casefold()
                    == extracted_tin
                )
            )
        ]

        if len(tin_matches) == 1:

            vendor = tin_matches[0]

            known_names = {
                normalize_name(vendor.legal_name),
            }

            if vendor.display_name:
                known_names.add(
                    normalize_name(vendor.display_name)
                )

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

            return vendor, findings, "exact_tin"

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
            ], None

    # ---------------------------------------------------------
    # 2. Exact normalized name matching.
    # ---------------------------------------------------------

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
            ], None

        return vendor, findings, "exact_name"

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
        ], None

    # ---------------------------------------------------------
    # 3. Ordered supplier-name prefix matching.
    # ---------------------------------------------------------

    extracted_tokens = _supplier_name_tokens(supplier_name)

    # Require at least two meaningful tokens and ten characters.
    # This avoids automatically matching short, generic names.
    is_strong_prefix = (
        len(extracted_tokens) >= 2
        and sum(len(token) for token in extracted_tokens) >= 10
    )

    if is_strong_prefix:

        prefix_matches = []

        for vendor in suppliers:

            candidate_names = [
                vendor.legal_name,
            ]

            if vendor.display_name:
                candidate_names.append(vendor.display_name)

            vendor_matches = False

            for candidate_name in candidate_names:

                vendor_tokens = _supplier_name_tokens(
                    candidate_name
                )

                if (
                    len(vendor_tokens) >= len(extracted_tokens)
                    and vendor_tokens[:len(extracted_tokens)]
                    == extracted_tokens
                ):
                    vendor_matches = True
                    break

            if vendor_matches:
                prefix_matches.append(vendor)

        # Only assign a vendor when exactly one vendor matches.
        if len(prefix_matches) == 1:

            vendor = prefix_matches[0]

            # Never automatically accept a conflicting registered TIN.
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
                            "Supplier name resembles an existing vendor, "
                            "but the extracted TIN differs from "
                            "the registered TIN."
                        ),
                    )
                ], None

            return vendor, findings, "ordered_name_prefix"

        if len(prefix_matches) > 1:

            return None, [
                ValidationFinding(
                    code="AMBIGUOUS_VENDOR",
                    severity="warning",
                    field_name="supplier_legal_name",
                    message=(
                        "Multiple existing vendors match "
                        "the extracted supplier-name prefix."
                    ),
                )
            ], None

    # ---------------------------------------------------------
    # 4. No reliable match.
    # ---------------------------------------------------------

    return None, [
        ValidationFinding(
            code="UNKNOWN_VENDOR",
            severity="warning",
            field_name="supplier_legal_name",
            message=(
                "No existing vendor matches the extracted supplier."
            ),
        )
    ], None


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

        # Normalize the original payment-term wording.
        normalized_terms = normalize_payment_terms(
            extraction.payment_terms
        )

        # Preserve an explicitly extracted due date.
        explicit_due_date = (
            date.fromisoformat(extraction.due_date)
            if extraction.due_date
            else None
        )

        # Resolve the due date using deterministic rules.
        due_date_resolution = resolve_due_date(
            explicit_due_date=explicit_due_date,
            invoice_date=invoice.invoice_date,
            payment_terms=normalized_terms,
        )

        invoice.due_date = due_date_resolution.due_date
        invoice.due_date_source = due_date_resolution.source

        invoice.payment_terms = (
            extraction.payment_terms or ""
        )

        invoice.payment_terms_days = (
            normalized_terms.days
        )

        invoice.payment_terms_basis = (
            normalized_terms.basis
        )

        invoice.payment_terms_source = (
            Invoice.PaymentTermsSource.DOCUMENT
            if extraction.payment_terms
            else ""
        )

        invoice.purchase_order_number = (
            extraction.purchase_order_number or ""
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

        # Replace component records from any previous
        # pre-review extraction attempt.
        invoice.tax_components.all().delete()
        invoice.charge_components.all().delete()

        # Persist individual tax components.
        tax_components = [
            InvoiceTaxComponent(
                invoice=invoice,
                position=position,
                name=tax.name,
                tax_type=tax.tax_type,
                treatment=tax.treatment,
                rate_percent=tax.rate_percent,
                taxable_base=tax.taxable_base,
                amount=tax.amount,
                # Recoverability remains NOT_ASSESSED.
            )
            for position, tax in enumerate(
                extraction.taxes or [],
                start=1,
            )
        ]

        if tax_components:
            InvoiceTaxComponent.objects.bulk_create(
                tax_components
            )

        # Persist individually identified other charges.
        charge_components = [
            InvoiceChargeComponent(
                invoice=invoice,
                position=position,
                description=charge.description,
                treatment=charge.treatment,
                amount=charge.amount,
            )
            for position, charge in enumerate(
                extraction.other_charge_components or [],
                start=1,
            )
        ]

        if charge_components:
            InvoiceChargeComponent.objects.bulk_create(
                charge_components
            )

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

        # 4. Recover invoice numbers split across PDF header rows.
        # layout-aware PDF recovery service.

        recovery = recover_split_invoice_number(
            document_result.page_words,
            document_result.page_sizes,
        )

        recovery_audit = None

        if recovery is not None:

            original_invoice_number = extraction.invoice_number

            payload = extraction.model_dump(mode="python")

            original_model_confidence = (
                payload.get("field_confidence") or {}
            ).get("invoice_number")

            # Replace the AI-extracted number with the
            # independently recovered PDF value.

            payload["invoice_number"] = recovery["invoice_number"]

            # Preserve every PDF fragment as separate evidence.
            field_evidence = dict(
                payload.get("field_evidence") or {}
            )

            field_evidence["invoice_number"] = [
                {
                    "page": recovery["page"],
                    "quote": fragment,
                }
                for fragment in recovery["fragments"]
            ]

            payload["field_evidence"] = field_evidence

            # The recovered value is deterministic, not an
            # AI confidence-scored extraction.

            field_confidence = dict(
                payload.get("field_confidence") or {}
            )

            field_confidence.pop("invoice_number", None)

            payload["field_confidence"] = field_confidence

            extraction = type(extraction).model_validate(payload)

            # Preserve the original AI value when recovery
            # actually changes the invoice number.

            if original_invoice_number != recovery["invoice_number"]:
                recovery_audit = {
                    "before": original_invoice_number,
                    "after": recovery["invoice_number"],
                    "page": recovery["page"],
                    "fragments": recovery["fragments"],
                    "method": recovery["method"],
                    "original_model_confidence": (
                        original_model_confidence
                    ),
                }

        # 5. Verify source evidence.

        evidence_findings = verify_extraction_evidence(
            extraction,
            document_result.page_texts,
        )

        # 6. Run deterministic financial validation.

        financial_findings = validate_invoice_extraction(
            extraction
        )

        # 7. Match the supplier against registered vendors.

        vendor, vendor_findings, vendor_match_method = _match_supplier(
            document.organization_id,
            extraction,
        )

        all_findings = (
            evidence_findings
            + financial_findings
            + vendor_findings
        )

        # 8. Persist processing results and the recovery audit
        # event in the same database transaction.

        with transaction.atomic():

            current_invoice = (
                Invoice.objects
                .select_related("vendor")
                .get(pk=invoice_id)
            )

            previous_vendor_name = (
                current_invoice.vendor.legal_name
                if current_invoice.vendor_id
                else None
            )

            result = _persist_extraction(
                invoice_id=invoice_id,
                document_id=document.id,
                extraction=extraction,
                vendor=vendor,
                findings=all_findings,
            )

            if (
                vendor is not None
                and vendor_match_method == "ordered_name_prefix"
                and current_invoice.vendor_id != vendor.pk
            ):
                InvoiceAuditEvent.objects.create(
                    organization_id=current_invoice.organization_id,
                    invoice=current_invoice,
                    actor=None,
                    action=InvoiceAuditEvent.Action.FIELD_UPDATED,
                    changes={
                        "vendor": {
                            "before": previous_vendor_name,
                            "after": vendor.legal_name,
                        }
                    },
                    metadata={
                        "operation": "deterministic_vendor_matching",
                        "method": "ordered_name_prefix",
                        "extracted_supplier_name": (
                            extraction.supplier_legal_name
                        ),
                        "matched_vendor_id": str(vendor.pk),
                    },
                )

            if recovery_audit is not None:
                persisted_invoice = Invoice.objects.get(
                    pk=invoice_id
                )

                InvoiceAuditEvent.objects.create(
                    organization_id=persisted_invoice.organization_id,
                    invoice=persisted_invoice,
                    actor=None,
                    action=InvoiceAuditEvent.Action.FIELD_UPDATED,
                    changes={
                        "invoice_number": {
                            "before": recovery_audit["before"],
                            "after": recovery_audit["after"],
                        }
                    },
                    metadata={
                        "operation": (
                            "deterministic_invoice_number_recovery"
                        ),
                        "method": recovery_audit["method"],
                        "page": recovery_audit["page"],
                        "evidence": recovery_audit["fragments"],
                        "original_model_confidence": (
                            recovery_audit[
                                "original_model_confidence"
                            ]
                        ),
                    },
                )

        return result

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

