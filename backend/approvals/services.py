
from django.db import transaction

from approvals.models import ApprovalRequest, ApprovalDecision
from auditlog.models import InvoiceAuditEvent
from auditlog.services import record_invoice_event
from invoices.models import Invoice
from organizations.models import OrganizationMembership

from accounting.services import create_draft_journal_for_approved_invoice


RETURN_TO_REVIEW_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_OPERATOR,
)


class ApprovalReturnPermissionError(Exception):
    pass


APPROVER_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_REVIEWER,
)


class ApprovalPermissionError(Exception):
    pass


class ApprovalMakerCheckerError(Exception):
    pass


class ApprovalStateError(Exception):
    pass


def require_approval_permission(*, organization_id, actor):
    """
    Ensure the actor has an active membership and an
    authorized approval role in the target organization.
    """

    membership = (
        OrganizationMembership.objects
        .filter(
            organization_id=organization_id,
            user=actor,
            is_active=True,
        )
        .first()
    )

    if membership is None or membership.role not in APPROVER_ROLES:
        raise ApprovalPermissionError(
            "You are not authorized to approve invoices in this organization."
        )

    return membership


@transaction.atomic
def decide_approval_request(
    *,
    organization_id,
    approval_request_id,
    actor,
    outcome,
    comment="",
):
    """
    Approve or reject a pending invoice approval request.

    The approval decision, approval request status, invoice
    status and audit event are committed atomically.
    """

    require_approval_permission(
        organization_id=organization_id,
        actor=actor,
    )

    if outcome not in ApprovalDecision.Outcome.values:
        raise ValueError("Invalid approval decision outcome.")

    # First locate the request without locking it.
    # We need its invoice ID to maintain a consistent lock order.

    reference = (
        ApprovalRequest.objects
        .filter(
            pk=approval_request_id,
            organization_id=organization_id,
        )
        .values("invoice_id")
        .first()
    )

    if reference is None:
        raise ApprovalRequest.DoesNotExist

    # Lock the invoice first. Invoice submission also locks
    # the invoice before creating an approval request.

    invoice = (
        Invoice.objects
        .select_for_update()
        .filter(
            pk=reference["invoice_id"],
            organization_id=organization_id,
        )
        .first()
    )

    if invoice is None:
        raise ApprovalRequest.DoesNotExist

    # Then lock the approval request.

    approval_request = (
        ApprovalRequest.objects
        .select_for_update()
        .select_related("submitted_by")
        .filter(
            pk=approval_request_id,
            organization_id=organization_id,
            invoice=invoice,
        )
        .first()
    )

    if approval_request is None:
        raise ApprovalRequest.DoesNotExist

    if (
        approval_request.status != ApprovalRequest.Status.PENDING
        or invoice.status != Invoice.Status.PENDING_APPROVAL
    ):
        raise ApprovalStateError(
            "This approval request is no longer pending."
        )

    # Maker-checker enforcement.
    # A submitter cannot approve or reject their own request.

    if approval_request.submitted_by_id == actor.pk:
        raise ApprovalMakerCheckerError(
            "You cannot decide an approval request you submitted."
        )

    if (
        outcome == ApprovalDecision.Outcome.REJECTED
        and not comment.strip()
    ):
        raise ValueError(
            "A rejection comment is required."
        )

    previous_request_status = approval_request.status
    previous_invoice_status = invoice.status

    # Create the immutable decision record.

    decision = ApprovalDecision(
        approval_request=approval_request,
        decided_by=actor,
        outcome=outcome,
        comment=comment,
    )

    decision.save(force_insert=True)

    # Update approval request.

    approval_request.status = outcome

    approval_request.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # Update invoice.

    invoice.status = (
        Invoice.Status.APPROVED
        if outcome == ApprovalDecision.Outcome.APPROVED
        else Invoice.Status.REJECTED
    )

    invoice.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    journal_entry = None

    if outcome == ApprovalDecision.Outcome.APPROVED:
        journal_entry, journal_created = (
            create_draft_journal_for_approved_invoice(
                invoice=invoice,
                approval_decision=decision,
                actor=actor,
            )
        )

    # Record the decision in the invoice audit history.

    audit_action = (
        InvoiceAuditEvent.Action.APPROVAL_GRANTED
        if outcome == ApprovalDecision.Outcome.APPROVED
        else InvoiceAuditEvent.Action.APPROVAL_REJECTED
    )

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=audit_action,
        changes={
            "approval_request_status": {
                "before": previous_request_status,
                "after": approval_request.status,
            },
            "invoice_status": {
                "before": previous_invoice_status,
                "after": invoice.status,
            },
        },
        metadata={
            "approval_request_id": str(approval_request.id),
            "approval_decision_id": str(decision.id),
            "outcome": outcome,
            "comment": comment,
            "submitted_by_id": str(approval_request.submitted_by_id),
            "journal_entry_id": (
                str(journal_entry.id) if journal_entry else None
            ),
        },
    )

    return approval_request, decision, invoice

@transaction.atomic
def return_rejected_invoice_to_review(
    *,
    organization_id,
    approval_request_id,
    actor,
    return_reason,
):
    """
    Return a rejected invoice to NEEDS_REVIEW.

    The previous rejected ApprovalRequest and ApprovalDecision
    remain unchanged as historical records.
    """

    # 1. Verify the actor's organizational membership.

    membership = (
        OrganizationMembership.objects
        .select_for_update()
        .filter(
            organization_id=organization_id,
            user=actor,
            is_active=True,
        )
        .first()
    )

    if (
        membership is None
        or membership.role not in RETURN_TO_REVIEW_ROLES
    ):
        raise ApprovalReturnPermissionError(
            "You are not authorized to return invoices for review."
        )

    # 2. Retrieve the invoice ID before acquiring row locks.
    # This allows us to maintain the same invoice-first
    # locking order used by the approval decision service.

    reference = (
        ApprovalRequest.objects
        .filter(
            pk=approval_request_id,
            organization_id=organization_id,
        )
        .values("invoice_id")
        .first()
    )

    if reference is None:
        raise ApprovalRequest.DoesNotExist

    # 3. Lock the invoice.

    invoice = (
        Invoice.objects
        .select_for_update()
        .filter(
            pk=reference["invoice_id"],
            organization_id=organization_id,
        )
        .first()
    )

    if invoice is None:
        raise ApprovalRequest.DoesNotExist

    # 4. Lock the original approval request.

    approval_request = (
        ApprovalRequest.objects
        .select_for_update()
        .filter(
            pk=approval_request_id,
            organization_id=organization_id,
            invoice=invoice,
        )
        .first()
    )

    if approval_request is None:
        raise ApprovalRequest.DoesNotExist

    # 5. Confirm the invoice and request were actually rejected.

    if (
        approval_request.status != ApprovalRequest.Status.REJECTED
        or invoice.status != Invoice.Status.REJECTED
    ):
        raise ApprovalStateError(
            "Only rejected invoices can be returned for review."
        )

    # 6. Lock and verify the original rejection decision.

    decision = (
        ApprovalDecision.objects
        .select_for_update()
        .filter(
            approval_request=approval_request,
            outcome=ApprovalDecision.Outcome.REJECTED,
        )
        .first()
    )

    if decision is None:
        raise ApprovalStateError(
            "The rejected approval request has no valid rejection decision."
        )

    # 7. Return the invoice to the review workflow.

    previous_status = invoice.status

    invoice.status = Invoice.Status.NEEDS_REVIEW

    invoice.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    # 8. Record the return operation.

    record_invoice_event(
        invoice=invoice,
        actor=actor,
        action=InvoiceAuditEvent.Action.REOPENED_FOR_REVIEW,
        changes={
            "invoice_status": {
                "before": previous_status,
                "after": Invoice.Status.NEEDS_REVIEW,
            }
        },
        metadata={
            "approval_request_id": str(approval_request.id),
            "rejection_decision_id": str(decision.id),
            "rejected_by_id": str(decision.decided_by_id),
            "rejection_comment": decision.comment,
            "return_reason": return_reason,
        },
    )

    return invoice, approval_request, decision

