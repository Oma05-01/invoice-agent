
from copy import deepcopy
from datetime import date
from decimal import Decimal
from vendors.models import Vendor
from django.db import transaction
from django.utils import timezone

from auditlog.models import InvoiceAuditEvent
from auditlog.services import record_invoice_event
from documents.models import Document
from invoices.models import (
    Invoice,
    InvoiceValidationIssue,
    InvoiceLineItem
)
from invoices.schemas import InvoiceExtractionResult
from invoices.services.validation import validate_invoice_extraction
from approvals.models import ApprovalRequest

VALIDATION_CODES = {
    "MISSING_REQUIRED_FIELD",
    "DUE_DATE_BEFORE_INVOICE_DATE",
    "LINE_TOTAL_MISMATCH",
    "SUBTOTAL_MISMATCH",
    "TOTAL_MISMATCH",
    "AMOUNT_DUE_MISMATCH",
}

NON_IGNORABLE_ISSUE_CODES = {
    "UNKNOWN_VENDOR",
    "MISSING_REQUIRED_FIELD",
}

class InvoiceIssueDecisionError(Exception):
    pass


class InvoiceIssueNotIgnorable(Exception):
    pass


class InvoiceReviewStateError(Exception):
    pass


class InvoiceCorrectionNoChanges(Exception):
    pass


def serialize_audit_value(value):
    if isinstance(value, (date,)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    return value


def build_validation_payload(invoice):
    """
    Construct validation input using current operational invoice
    values and current persisted line items.

    Original extraction remains untouched.
    """

    payload = deepcopy(invoice.extracted_data or {})

    editable_fields = {
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency",
        "subtotal",
        "other_charges",
        "total_amount",
        "amount_due",
        "description",
    }

    for field_name in editable_fields:
        value = getattr(invoice, field_name)
        payload[field_name] = serialize_audit_value(value)

    # Rebuild line items from current operational records.
    # This ensures validation sees human corrections, additions
    # and deletions rather than stale AI-extracted values.

    payload["line_items"] = [
        {
            "description": item.description,
            "quantity": serialize_audit_value(item.quantity),
            "unit_price": serialize_audit_value(item.unit_price),
            "tax_rate_percent": serialize_audit_value(item.tax_rate),
            "line_total": serialize_audit_value(item.line_total),
            "suggested_expense_category": (
                item.suggested_category or None
            ),
        }
        for item in invoice.line_items.all()
    ]

    if invoice.vendor_id:
        payload["supplier_legal_name"] = (
            payload.get("supplier_legal_name")
            or invoice.vendor.legal_name
        )

        payload["supplier_tin"] = (
            payload.get("supplier_tin")
            or invoice.vendor.tax_identification_number
            or None
        )

    return InvoiceExtractionResult.model_validate(payload)


def _line_item_snapshot(item):
    return {
        "id": str(item.id),
        "position": item.position,
        "description": item.description,
        "quantity": serialize_audit_value(item.quantity),
        "unit_price": serialize_audit_value(item.unit_price),
        "tax_rate": serialize_audit_value(item.tax_rate),
        "line_total": serialize_audit_value(item.line_total),
        "suggested_category": item.suggested_category,
        "ledger_code": item.ledger_code,
    }


def _revalidate_review_invoice(*, invoice, actor):
    """
    Re-run deterministic validation against the current
    operational invoice and line-item records.
    """

    extraction = build_validation_payload(invoice)

    findings = validate_invoice_extraction(extraction)

    automatically_resolved = synchronize_validation_issues(
        invoice=invoice,
        findings=findings,
        actor=actor,
    )

    return findings, automatically_resolved


@transaction.atomic
def add_invoice_line_item(
    *,
    organization_id,
    invoice_id,
    actor,
    corrections,
    correction_reason,
):
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
        raise Invoice.DoesNotExist

    if invoice.status != Invoice.Status.NEEDS_REVIEW:
        raise InvoiceReviewStateError(
            "Line items can only be added during invoice review."
        )

    last_position = (
        invoice.line_items
        .order_by("-position")
        .values_list("position", flat=True)
        .first()
        or 0
    )

    item = InvoiceLineItem.objects.create(
        invoice=invoice,
        position=last_position + 1,
        **corrections,
    )

    findings, automatically_resolved = (
        _revalidate_review_invoice(
            invoice=invoice,
            actor=actor,
        )
    )

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.FIELD_UPDATED,
        changes={
            f"line_items.{item.id}": {
                "before": None,
                "after": _line_item_snapshot(item),
            }
        },
        metadata={
            "operation": "line_item_added",
            "correction_reason": correction_reason,
            "validation_findings": len(findings),
            "automatically_resolved_issue_ids": (
                automatically_resolved
            ),
        },
    )

    return item, findings, automatically_resolved


@transaction.atomic
def update_invoice_line_item(
    *,
    organization_id,
    invoice_id,
    line_item_id,
    actor,
    corrections,
    correction_reason,
):
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
        raise Invoice.DoesNotExist

    if invoice.status != Invoice.Status.NEEDS_REVIEW:
        raise InvoiceReviewStateError(
            "Line items can only be edited during invoice review."
        )

    item = (
        InvoiceLineItem.objects
        .select_for_update()
        .filter(
            pk=line_item_id,
            invoice=invoice,
        )
        .first()
    )

    if item is None:
        raise InvoiceLineItem.DoesNotExist

    changes = {}

    for field_name, new_value in corrections.items():
        old_value = getattr(item, field_name)

        if old_value == new_value:
            continue

        changes[f"line_items.{item.id}.{field_name}"] = {
            "before": serialize_audit_value(old_value),
            "after": serialize_audit_value(new_value),
        }

        setattr(item, field_name, new_value)

    if not changes:
        raise InvoiceCorrectionNoChanges(
            "The supplied values do not change the line item."
        )

    item.save(
        update_fields=[
            *corrections.keys(),
            "updated_at",
        ]
    )

    findings, automatically_resolved = (
        _revalidate_review_invoice(
            invoice=invoice,
            actor=actor,
        )
    )

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.FIELD_UPDATED,
        changes=changes,
        metadata={
            "operation": "line_item_updated",
            "line_item_id": str(item.id),
            "correction_reason": correction_reason,
            "validation_findings": len(findings),
            "automatically_resolved_issue_ids": (
                automatically_resolved
            ),
        },
    )

    return item, findings, automatically_resolved


@transaction.atomic
def delete_invoice_line_item(
    *,
    organization_id,
    invoice_id,
    line_item_id,
    actor,
    correction_reason,
):
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
        raise Invoice.DoesNotExist

    if invoice.status != Invoice.Status.NEEDS_REVIEW:
        raise InvoiceReviewStateError(
            "Line items can only be deleted during invoice review."
        )

    item = (
        InvoiceLineItem.objects
        .select_for_update()
        .filter(
            pk=line_item_id,
            invoice=invoice,
        )
        .first()
    )

    if item is None:
        raise InvoiceLineItem.DoesNotExist

    previous_values = _line_item_snapshot(item)
    item_id = str(item.id)

    item.delete()

    findings, automatically_resolved = (
        _revalidate_review_invoice(
            invoice=invoice,
            actor=actor,
        )
    )

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.FIELD_UPDATED,
        changes={
            f"line_items.{item_id}": {
                "before": previous_values,
                "after": None,
            }
        },
        metadata={
            "operation": "line_item_deleted",
            "line_item_id": item_id,
            "correction_reason": correction_reason,
            "validation_findings": len(findings),
            "automatically_resolved_issue_ids": (
                automatically_resolved
            ),
        },
    )

    return item_id, findings, automatically_resolved

def synchronize_validation_issues(
    *,
    invoice,
    findings,
    actor,
):
    """
    Synchronize deterministic financial validation issues.

    Findings that disappear after correction are resolved.
    Findings that reappear are reopened.
    Ignored issues remain ignored.
    """

    existing_issues = list(
        InvoiceValidationIssue.objects
        .select_for_update()
        .filter(
            invoice=invoice,
            code__in=VALIDATION_CODES,
        )
    )

    issues_by_key = {
        (issue.code, issue.field_name): issue
        for issue in existing_issues
    }

    active_keys = set()
    automatically_resolved = []

    for finding in findings:
        key = (finding.code, finding.field_name)
        active_keys.add(key)

        issue = issues_by_key.pop(key, None)

        if issue is None:
            InvoiceValidationIssue.objects.create(
                invoice=invoice,
                code=finding.code,
                severity=finding.severity,
                field_name=finding.field_name,
                message=finding.message,
                details=finding.details,
                status=InvoiceValidationIssue.Status.OPEN,
            )
            continue

        update_fields = []

        issue.severity = finding.severity
        issue.message = finding.message
        issue.details = finding.details

        update_fields.extend([
            "severity",
            "message",
            "details",
            "updated_at",
        ])

        if issue.status == InvoiceValidationIssue.Status.RESOLVED:
            issue.status = InvoiceValidationIssue.Status.OPEN
            issue.resolved_by = None
            issue.resolved_at = None
            issue.decision_reason = ""

            update_fields.extend([
                "status",
                "resolved_by",
                "resolved_at",
                "decision_reason",
            ])

        # An explicitly ignored issue stays ignored while
        # the same finding remains present.

        issue.save(update_fields=update_fields)

    # Existing open findings that are no longer present
    # have been resolved by the latest correction.

    for issue in issues_by_key.values():
        if issue.status not in {
            InvoiceValidationIssue.Status.OPEN,
            InvoiceValidationIssue.Status.IGNORED,
        }:
            continue
        issue.status = InvoiceValidationIssue.Status.RESOLVED
        issue.resolved_by = actor
        issue.resolved_at = timezone.now()
        issue.decision_reason = ""

        issue.save(
            update_fields=[
                "status",
                "resolved_by",
                "resolved_at",
                "decision_reason",
                "updated_at",
            ]
        )

        automatically_resolved.append(str(issue.id))

    return automatically_resolved


@transaction.atomic
def correct_invoice_header(
    *,
    organization_id,
    invoice_id,
    actor,
    corrections,
    correction_reason,
):
    """
    Apply human invoice-header corrections atomically.

    Original AI extraction data is never overwritten.
    """

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
        raise Invoice.DoesNotExist

    if invoice.status != Invoice.Status.NEEDS_REVIEW:
        raise InvoiceReviewStateError(
            "Only invoices awaiting review can be corrected."
        )

    changes = {}

    for field_name, new_value in corrections.items():
        old_value = getattr(invoice, field_name)

        if old_value == new_value:
            continue

        changes[field_name] = {
            "before": serialize_audit_value(old_value),
            "after": serialize_audit_value(new_value),
        }

        setattr(invoice, field_name, new_value)

    if not changes:
        raise InvoiceCorrectionNoChanges(
            "The supplied values do not change the invoice."
        )

    invoice.save(
        update_fields=[
            *changes.keys(),
            "updated_at",
        ]
    )

    # Revalidate using corrected operational values and
    # the original extracted tax and line-item structure.

    extraction = build_validation_payload(invoice)

    findings = validate_invoice_extraction(extraction)

    automatically_resolved = synchronize_validation_issues(
        invoice=invoice,
        findings=findings,
        actor=actor,
    )

    # Save the correction and resulting validation history
    # in the same transaction.

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.FIELD_UPDATED,
        changes=changes,
        metadata={
            "correction_reason": correction_reason,
            "validation_findings": len(findings),
            "automatically_resolved_issue_ids": (
                automatically_resolved
            ),
        },
    )

    return invoice, changes, findings

@transaction.atomic
def assign_invoice_vendor(
    *,
    organization_id,
    invoice_id,
    vendor_id,
    actor,
    correction_reason,
):
    """
    Assign an existing organization vendor to an invoice.

    Resolves open UNKNOWN_VENDOR issues and records the
    human decision in the audit history.
    """

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
        raise Invoice.DoesNotExist

    if invoice.status != Invoice.Status.NEEDS_REVIEW:
        raise InvoiceReviewStateError(
            "Vendor assignment is only permitted during invoice review."
        )

    vendor = (
        Vendor.objects
        .select_for_update()
        .filter(
            pk=vendor_id,
            organization_id=organization_id,
            is_active=True,
        )
        .first()
    )

    if vendor is None:
        raise Vendor.DoesNotExist

    if invoice.vendor_id == vendor.id:
        raise InvoiceCorrectionNoChanges(
            "This vendor is already assigned to the invoice."
        )

    previous_vendor = None

    if invoice.vendor_id:
        previous_vendor = (
            Vendor.objects
            .filter(pk=invoice.vendor_id)
            .first()
        )

    changes = {
        "vendor": {
            "before": (
                {
                    "id": str(previous_vendor.id),
                    "legal_name": previous_vendor.legal_name,
                }
                if previous_vendor else None
            ),
            "after": {
                "id": str(vendor.id),
                "legal_name": vendor.legal_name,
            },
        }
    }

    invoice.vendor = vendor

    invoice.save(
        update_fields=[
            "vendor",
            "updated_at",
        ]
    )

    # Resolve open supplier-matching warnings.
    open_issues = list(
        InvoiceValidationIssue.objects
        .select_for_update()
        .filter(
            invoice=invoice,
            code="UNKNOWN_VENDOR",
            status=InvoiceValidationIssue.Status.OPEN,
        )
    )

    resolved_issue_ids = []

    now = timezone.now()

    for issue in open_issues:
        issue.status = InvoiceValidationIssue.Status.RESOLVED
        issue.resolved_by = actor
        issue.resolved_at = now

        issue.save(
            update_fields=[
                "status",
                "resolved_by",
                "resolved_at",
                "updated_at",
            ]
        )

        resolved_issue_ids.append(str(issue.id))

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.VENDOR_ASSIGNED,
        changes=changes,
        metadata={
            "correction_reason": correction_reason,
            "resolved_validation_issue_ids": resolved_issue_ids,
        },
    )

    return invoice, vendor, resolved_issue_ids

@transaction.atomic
def ignore_invoice_validation_issue(
    *,
    organization_id,
    invoice_id,
    issue_id,
    actor,
    decision_reason,
):
    """
    Allow an authorized reviewer to acknowledge an eligible
    validation warning without changing its underlying finding.
    """

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
        raise Invoice.DoesNotExist

    if invoice.status != Invoice.Status.NEEDS_REVIEW:
        raise InvoiceReviewStateError(
            "Validation issues can only be reviewed while "
            "the invoice is awaiting review."
        )

    issue = (
        InvoiceValidationIssue.objects
        .select_for_update()
        .filter(
            pk=issue_id,
            invoice=invoice,
        )
        .first()
    )

    if issue is None:
        raise InvoiceValidationIssue.DoesNotExist

    if issue.status != InvoiceValidationIssue.Status.OPEN:
        raise InvoiceIssueDecisionError(
            "Only open validation issues can be ignored."
        )

    if (
        issue.severity == InvoiceValidationIssue.Severity.ERROR
        or issue.code in NON_IGNORABLE_ISSUE_CODES
    ):
        raise InvoiceIssueNotIgnorable(
            "This issue must be corrected rather than ignored."
        )

    previous_status = issue.status

    now = timezone.now()

    issue.status = InvoiceValidationIssue.Status.IGNORED
    issue.resolved_by = actor
    issue.resolved_at = now
    issue.decision_reason = decision_reason

    issue.save(
        update_fields=[
            "status",
            "resolved_by",
            "resolved_at",
            "decision_reason",
            "updated_at",
        ]
    )

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.VALIDATION_ISSUE_IGNORED,
        changes={
            f"validation_issues.{issue.id}.status": {
                "before": previous_status,
                "after": issue.status,
            }
        },
        metadata={
            "issue_id": str(issue.id),
            "issue_code": issue.code,
            "field_name": issue.field_name,
            "decision_reason": decision_reason,
        },
    )

    return issue



@transaction.atomic
def submit_invoice_for_approval(
    *,
    organization_id,
    invoice_id,
    actor,
    submission_note="",
):
    """
    Validate and submit an invoice for approval.

    A blocked submission preserves the invoice's NEEDS_REVIEW
    status while retaining any refreshed validation findings.
    """

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
        raise Invoice.DoesNotExist

    if invoice.status != Invoice.Status.NEEDS_REVIEW:
        raise InvoiceReviewStateError(
            "Only invoices awaiting review can be submitted for approval."
        )

    # Revalidate against current operational invoice data.

    extraction = build_validation_payload(invoice)

    findings = validate_invoice_extraction(extraction)

    automatically_resolved = synchronize_validation_issues(
        invoice=invoice,
        findings=findings,
        actor=actor,
    )

    issues = list(
        InvoiceValidationIssue.objects
        .select_for_update()
        .filter(invoice=invoice)
    )

    blockers = []

    def add_blocker(code, field_name, message):
        blockers.append({
            "code": code,
            "field_name": field_name,
            "message": message,
        })

    # -------------------------------------------------
    # 1. Supplier assignment
    # -------------------------------------------------

    vendor = None

    if invoice.vendor_id:
        vendor = (
            Vendor.objects
            .select_for_update()
            .filter(
                pk=invoice.vendor_id,
                organization_id=organization_id,
            )
            .first()
        )

    if vendor is None:
        add_blocker(
            "VENDOR_NOT_ASSIGNED",
            "vendor",
            "An existing organization vendor must be assigned.",
        )

    elif not vendor.is_active:
        add_blocker(
            "VENDOR_INACTIVE",
            "vendor",
            "The assigned vendor is inactive.",
        )

    # -------------------------------------------------
    # 2. Document availability
    # -------------------------------------------------

    document = None

    if invoice.source_document_id:
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
        add_blocker(
            "SOURCE_DOCUMENT_MISSING",
            "source_document",
            "An original source document is required.",
        )

    elif document.status != Document.Status.PROCESSED:
        add_blocker(
            "SOURCE_DOCUMENT_NOT_PROCESSED",
            "source_document",
            "The source document must be successfully processed.",
        )

    # -------------------------------------------------
    # 3. Explicit required operational fields
    # -------------------------------------------------

    required_fields = {
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date,
        "currency": invoice.currency,
        "subtotal": invoice.subtotal,
        "total_amount": invoice.total_amount,
    }

    for field_name, value in required_fields.items():
        if value is None or value == "":
            add_blocker(
                "MISSING_REQUIRED_FIELD",
                field_name,
                f"The required field {field_name} is missing.",
            )

    # -------------------------------------------------
    # 4. Validation issue checks
    # -------------------------------------------------

    # All open issues must be addressed.
    # Errors remain blockers even if marked as ignored.

    for issue in issues:

        if (
            issue.severity == InvoiceValidationIssue.Severity.ERROR
            and issue.status == InvoiceValidationIssue.Status.IGNORED
        ):
            add_blocker(
                "IGNORED_ERROR",
                issue.field_name,
                "An error-severity validation issue cannot be ignored.",
            )

        elif issue.status == InvoiceValidationIssue.Status.OPEN:
            add_blocker(
                issue.code,
                issue.field_name,
                issue.message,
            )

    # -------------------------------------------------
    # 5. Stop if any blockers remain
    # -------------------------------------------------

    # Return blockers rather than raising an exception.
    # This allows refreshed validation findings to commit.

    if blockers:
        return invoice, False, blockers, automatically_resolved, None

    # -------------------------------------------------
    # 6. Submit for approval
    # -------------------------------------------------

    previous_status = invoice.status

    invoice.status = Invoice.Status.PENDING_APPROVAL

    invoice.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    approval_request = ApprovalRequest(
        organization=invoice.organization,
        invoice=invoice,
        submitted_by=actor,
        submission_note=submission_note,
        status=ApprovalRequest.Status.PENDING,
    )

    approval_request.full_clean()
    approval_request.save(force_insert=True)

    # -------------------------------------------------
    # 7. Record audit event
    # -------------------------------------------------

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.REVIEW_SUBMITTED,
        changes={
            "status": {
                "before": previous_status,
                "after": Invoice.Status.PENDING_APPROVAL,
            }
        },
        metadata={
            "submission_note": submission_note,
            "automatically_resolved_issue_ids": (
                automatically_resolved
            ),
            "ignored_issue_ids": [
                str(issue.id)
                for issue in issues
                if issue.status == InvoiceValidationIssue.Status.IGNORED
            ],
        },
    )

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.APPROVAL_REQUESTED,
        changes={
            "approval_request": {
                "before": None,
                "after": str(approval_request.id),
            }
        },
        metadata={
            "approval_request_id": str(approval_request.id),
            "submission_note": submission_note,
        },
    )

    return invoice, True, [], automatically_resolved, approval_request

