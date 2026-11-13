import uuid

from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounting.models import (
    Account,
    JournalAdjustment,
    JournalEntry,
    JournalLine,
    VendorPayment,
)
from approvals.models import ApprovalDecision
from invoices.models import Invoice
from django.db.models import Max

from auditlog.models import InvoiceAuditEvent
from auditlog.services import (
    record_invoice_event,
    record_journal_event,
)
from organizations.models import OrganizationMembership

class AccountingError(Exception):
    """Base exception for accounting operations."""


class AccountingConfigurationError(AccountingError):
    """Raised when the organization's chart of accounts is invalid."""


class AccountingStateError(AccountingError):
    """Raised when an accounting operation violates a business rule."""

class AccountingPermissionError(AccountingError):
    """Raised when a user lacks permission for an accounting operation."""


DRAFT_EDIT_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_OPERATOR,
)

POSTING_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
)

REVERSAL_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
)

# Starter chart of accounts.
#
# These are baseline accounts, not a substitute for an
# organization's approved accounting policy.

DEFAULT_CHART_OF_ACCOUNTS = (
    (
        "1000",
        "Cash and Cash Equivalents",
        Account.AccountType.ASSET,
        "Cash held by the organization.",
        True,
    ),
    (
        "1100",
        "Accounts Receivable",
        Account.AccountType.ASSET,
        "Amounts owed to the organization.",
        True,
    ),
    (
        "2000",
        "Accounts Payable",
        Account.AccountType.LIABILITY,
        "Amounts owed to suppliers.",
        True,
    ),
    (
        "2100",
        "Tax Payable",
        Account.AccountType.LIABILITY,
        "Taxes payable, subject to accounting review.",
        False,
    ),
    (
        "3000",
        "Retained Earnings and Equity",
        Account.AccountType.EQUITY,
        "Accumulated organizational equity.",
        False,
    ),
    (
        "4000",
        "Operating Revenue",
        Account.AccountType.INCOME,
        "Revenue generated from business operations.",
        False,
    ),
    (
        "5000",
        "Unclassified Expense",
        Account.AccountType.EXPENSE,
        "Expense awaiting finance classification.",
        False,
    ),
    (
        "5100",
        "Professional Services Expense",
        Account.AccountType.EXPENSE,
        "Professional and consulting services.",
        False,
    ),
    (
        "5200",
        "Office and Administrative Expense",
        Account.AccountType.EXPENSE,
        "General office and administrative expenses.",
        False,
    ),
)


@transaction.atomic
def initialize_chart_of_accounts(*, organization):
    """
    Create the starter chart of accounts for an organization.

    Idempotent: running this repeatedly does not create
    duplicate accounts or overwrite existing configuration.
    """

    if not organization.is_active:
        raise AccountingStateError(
            "Accounts cannot be initialized for an inactive organization."
        )

    accounts = {}

    for code, name, account_type, description, is_control in (
        DEFAULT_CHART_OF_ACCOUNTS
    ):
        account, created = Account.objects.get_or_create(
            organization=organization,
            code=code,
            defaults={
                "name": name,
                "account_type": account_type,
                "description": description,
                "is_control_account": is_control,
                "is_active": True,
            },
        )

        # Never silently use an existing account code
        # with a conflicting account classification.

        if account.account_type != account_type:
            raise AccountingConfigurationError(
                f"Account code {code} already exists with "
                "a different account type."
            )

        accounts[code] = account

    return accounts


@transaction.atomic
def create_draft_journal_for_approved_invoice(
    *,
    invoice,
    approval_decision,
    actor,
):
    """
    Generate one balanced draft journal for an approved invoice.

    The initial draft uses an unclassified expense account.
    Finance must review the classification before posting.

    Returns:
        (journal_entry, created)
    """

    # Lock the invoice and reload its authoritative values.

    locked_invoice = (
        Invoice.objects
        .select_for_update(of=("self",))
        .select_related("organization")
        .get(pk=invoice.pk)
    )

    # Verify the approval decision and its relationship
    # to the invoice.

    decision = (
        ApprovalDecision.objects
        .select_related("approval_request")
        .get(pk=approval_decision.pk)
    )

    if decision.outcome != ApprovalDecision.Outcome.APPROVED:
        raise AccountingStateError(
            "Only approved invoices can generate accounting journals."
        )

    if decision.approval_request.invoice_id != locked_invoice.pk:
        raise AccountingStateError(
            "The approval decision does not belong to this invoice."
        )

    if (
        decision.approval_request.organization_id
        != locked_invoice.organization_id
    ):
        raise AccountingStateError(
            "The approval decision belongs to another organization."
        )

    if locked_invoice.status != Invoice.Status.APPROVED:
        raise AccountingStateError(
            "The invoice must be approved before journal generation."
        )

    # Prevent duplicate journals if this operation is retried.

    existing_entry = (
        JournalEntry.objects
        .select_for_update(of=("self",))
        .filter(source_invoice=locked_invoice)
        .first()
    )

    if existing_entry is not None:
        if existing_entry.approval_decision_id != decision.pk:
            raise AccountingStateError(
                "A journal already exists for this invoice "
                "with a different approval decision."
            )

        return existing_entry, False

    total_amount = locked_invoice.total_amount

    if total_amount is None or total_amount <= Decimal("0.00"):
        raise AccountingStateError(
            "A positive invoice total is required to generate "
            "a draft journal."
        )

    organization = locked_invoice.organization

    accounts = initialize_chart_of_accounts(
        organization=organization,
    )

    expense_account = accounts["5000"]
    payable_account = accounts["2000"]

    currency = (
        locked_invoice.currency
        or organization.default_currency
    )

    invoice_reference = (
        locked_invoice.invoice_number
        or str(locked_invoice.pk)
    )

    reference = f"INV-{invoice_reference}"[:100]

    entry = JournalEntry(
        organization=organization,
        source_invoice=locked_invoice,
        approval_decision=decision,
        entry_date=(
            locked_invoice.invoice_date
            or timezone.localdate()
        ),
        currency=currency,
        reference=reference,
        description=(
            f"Draft accounting entry for invoice "
            f"{invoice_reference}. Expense classification "
            "requires finance review."
        ),
        status=JournalEntry.Status.DRAFT,
        created_by=actor,
    )

    entry.full_clean()
    entry.save(force_insert=True)

    # Initial double-entry posting.
    #
    # We deliberately do not infer VAT treatment or expense
    # categories from the AI's suggested classifications.

    lines = [
        JournalLine(
            entry=entry,
            line_number=1,
            account=expense_account,
            description="Unclassified supplier expense",
            debit=total_amount,
            credit=Decimal("0.00"),
        ),
        JournalLine(
            entry=entry,
            line_number=2,
            account=payable_account,
            description="Supplier accounts payable",
            debit=Decimal("0.00"),
            credit=total_amount,
        ),
    ]

    for line in lines:
        line.full_clean()
        line.save(force_insert=True)

    record_journal_audit(
        entry=entry,
        actor=actor,
        operation="journal_draft_created",
        changes={
            "journal_status": {
                "before": None,
                "after": entry.status,
            }
        },
        metadata={
            "total_debit": str(total_amount),
            "total_credit": str(total_amount),
            "line_count": len(lines),
            "source_invoice_id": str(locked_invoice.id),
        },
        mirror_to_invoice=False,
    )

    return entry, True

def require_accounting_role(*, organization_id, actor, allowed_roles):
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

    if membership is None or membership.role not in allowed_roles:
        raise AccountingPermissionError(
            "You are not authorized to perform this accounting operation."
        )

    return membership


def get_locked_journal(*, organization_id, journal_entry_id):
    entry = (
        JournalEntry.objects
        .select_for_update(of=("self",))
        .select_related("source_invoice")
        .filter(
            pk=journal_entry_id,
            organization_id=organization_id,
        )
        .first()
    )

    if entry is None:
        raise JournalEntry.DoesNotExist

    return entry


def validate_journal_line_amounts(
    *,
    debit,
    credit,
    allow_zero=True,
):
    debit = Decimal(str(debit))
    credit = Decimal(str(credit))

    if not debit.is_finite() or not credit.is_finite():
        raise AccountingStateError(
            "Journal amounts must be finite decimal values."
        )

    if debit < Decimal("0.00") or credit < Decimal("0.00"):
        raise AccountingStateError(
            "Journal amounts cannot be negative."
        )

    if debit > 0 and credit > 0:
        raise AccountingStateError(
            "A journal line cannot contain both a debit and a credit."
        )

    if not allow_zero and debit == 0 and credit == 0:
        raise AccountingStateError(
            "A journal line must contain a positive debit or credit."
        )


def validate_journal_for_posting(entry, lines):
    if len(lines) < 2:
        raise AccountingStateError(
            "A journal must contain at least two lines before posting."
        )

    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")

    for line in lines:
        if line.account_id is None:
            raise AccountingStateError(
                f"Journal line {line.line_number} has no assigned account."
            )

        if not line.account.is_active:
            raise AccountingStateError(
                f"Account {line.account.code} is inactive."
            )

        if line.account.organization_id != entry.organization_id:
            raise AccountingStateError(
                "A journal line references an account from another organization."
            )

        validate_journal_line_amounts(
            debit=line.debit,
            credit=line.credit,
            allow_zero=False,
        )

        total_debit += line.debit
        total_credit += line.credit

    if total_debit <= 0:
        raise AccountingStateError(
            "A journal must contain a positive total debit."
        )

    if total_debit != total_credit:
        raise AccountingStateError(
            f"Journal is unbalanced. Debits: {total_debit}; "
            f"credits: {total_credit}."
        )

    return total_debit, total_credit


def record_journal_audit(
    *,
    entry,
    actor,
    operation,
    changes,
    metadata=None,
    mirror_to_invoice=True,
):
    """
    Record accounting activity against the journal.

    When the journal belongs to an invoice, optionally mirror
    the event into the invoice activity history.
    """

    journal_event = record_journal_event(
        entry=entry,
        actor=actor,
        operation=operation,
        changes=changes,
        metadata=metadata,
    )

    if entry.source_invoice_id and mirror_to_invoice:
        record_invoice_event(
            invoice=entry.source_invoice,
            actor=actor,
            action=InvoiceAuditEvent.Action.FIELD_UPDATED,
            changes=changes,
            metadata={
                "operation": operation,
                "journal_entry_id": str(entry.id),
                **(metadata or {}),
            },
        )

    return journal_event


@transaction.atomic
def update_draft_journal_line(
    *,
    organization_id,
    journal_entry_id,
    journal_line_id,
    actor,
    corrections,
    correction_reason,
):
    require_accounting_role(
        organization_id=organization_id,
        actor=actor,
        allowed_roles=DRAFT_EDIT_ROLES,
    )

    if not correction_reason.strip():
        raise AccountingStateError(
            "A correction reason is required."
        )

    entry = get_locked_journal(
        organization_id=organization_id,
        journal_entry_id=journal_entry_id,
    )

    if entry.status != JournalEntry.Status.DRAFT:
        raise AccountingStateError(
            "Only draft journal lines can be edited."
        )

    line = (
        JournalLine.objects
        .select_for_update(of=("self",))
        .select_related("account")
        .filter(
            pk=journal_line_id,
            entry=entry,
        )
        .first()
    )

    if line is None:
        raise JournalLine.DoesNotExist

    allowed_fields = {
        "account_id",
        "debit",
        "credit",
        "description",
    }

    if not corrections or set(corrections) - allowed_fields:
        raise AccountingStateError(
            "No valid journal line corrections were supplied."
        )

    previous = {
        "account": (
            f"{line.account.code} - {line.account.name}"
            if line.account_id else None
        ),
        "debit": str(line.debit),
        "credit": str(line.credit),
        "description": line.description,
    }

    for field_name, value in corrections.items():

        if field_name == "account_id":
            account = None

            if value is not None:
                account = (
                    Account.objects
                    .select_for_update()
                    .filter(
                        pk=value,
                        organization_id=organization_id,
                        is_active=True,
                    )
                    .first()
                )

                if account is None:
                    raise AccountingConfigurationError(
                        "An active account in this organization is required."
                    )

            line.account = account

        else:
            setattr(line, field_name, value)

    validate_journal_line_amounts(
        debit=line.debit,
        credit=line.credit,
    )

    line.full_clean()

    line.save(
        update_fields=[
            *corrections.keys(),
            "account",
            "updated_at",
        ]
    )

    current = {
        "account": (
            f"{line.account.code} - {line.account.name}"
            if line.account_id else None
        ),
        "debit": str(line.debit),
        "credit": str(line.credit),
        "description": line.description,
    }

    record_journal_audit(
        entry=entry,
        actor=actor,
        operation="journal_line_updated",
        changes={
            f"journal_lines.{line.id}": {
                "before": previous,
                "after": current,
            }
        },
        metadata={
            "correction_reason": correction_reason,
        },
    )

    return line


@transaction.atomic
def update_draft_journal_entry_date(
    *,
    organization_id,
    journal_entry_id,
    actor,
    entry_date,
    correction_reason,
):
    require_accounting_role(
        organization_id=organization_id,
        actor=actor,
        allowed_roles=DRAFT_EDIT_ROLES,
    )

    if not correction_reason or not correction_reason.strip():
        raise AccountingStateError(
            "A correction reason is required."
        )

    if type(entry_date) is not date:
        raise AccountingStateError(
            "A valid journal entry date is required."
        )

    entry = get_locked_journal(
        organization_id=organization_id,
        journal_entry_id=journal_entry_id,
    )

    if entry.status != JournalEntry.Status.DRAFT:
        raise AccountingStateError(
            "Only draft journal dates can be changed."
        )

    previous_date = entry.entry_date.isoformat()

    entry.entry_date = entry_date
    entry.full_clean()
    entry.save(update_fields=["entry_date", "updated_at"])

    record_journal_audit(
        entry=entry,
        actor=actor,
        operation="journal_entry_date_updated",
        changes={
            "entry_date": {
                "before": previous_date,
                "after": entry.entry_date.isoformat(),
            }
        },
        metadata={
            "correction_reason": correction_reason.strip(),
        },
    )

    return entry



def _post_locked_journal_entry(*, entry, actor):
    """
    Post an already-locked draft journal.

    The caller must provide an atomic transaction and must
    lock the journal before calling this helper.
    """
    if entry.status != JournalEntry.Status.DRAFT:
        raise AccountingStateError(
            "Only draft journals can be posted."
        )

    if entry.source_invoice_id:
        if entry.source_invoice.status != Invoice.Status.APPROVED:
            raise AccountingStateError(
                "The source invoice must remain approved before posting."
            )

    if (
        len(entry.currency) != 3
        or not entry.currency.isalpha()
    ):
        raise AccountingStateError(
            "A valid three-letter journal currency is required."
        )

    lines = list(
        JournalLine.objects
        .select_for_update(of=("self",))
        .select_related("account")
        .filter(entry=entry)
        .order_by("line_number")
    )

    total_debit, total_credit = validate_journal_for_posting(
        entry,
        lines,
    )

    previous_status = entry.status

    entry.status = JournalEntry.Status.POSTED
    entry.posted_by = actor
    entry.posted_at = timezone.now()

    entry.save(
        update_fields=[
            "status",
            "posted_by",
            "posted_at",
            "updated_at",
        ]
    )

    record_journal_audit(
        entry=entry,
        actor=actor,
        operation="journal_posted",
        changes={
            "journal_status": {
                "before": previous_status,
                "after": entry.status,
            }
        },
        metadata={
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "posted_by": actor.get_username(),
        },
    )

    return entry


@transaction.atomic
def post_journal_entry(
    *,
    organization_id,
    journal_entry_id,
    actor,
):
    require_accounting_role(
        organization_id=organization_id,
        actor=actor,
        allowed_roles=POSTING_ROLES,
    )

    entry = get_locked_journal(
        organization_id=organization_id,
        journal_entry_id=journal_entry_id,
    )

    if VendorPayment.objects.filter(journal_entry=entry).exists():
        raise AccountingStateError(
            "Vendor payment journals must be posted "
            "through the vendor payment workflow."
        )

    return _post_locked_journal_entry(
        entry=entry,
        actor=actor,
    )


def _reverse_locked_journal_entry(
    *,
    original,
    actor,
    reversal_reason,
):
    """
    Reverse an already-locked posted journal.

    The caller must provide an atomic transaction and must
    lock the original journal before calling this helper.
    """
    if original.status != JournalEntry.Status.POSTED:
        raise AccountingStateError(
            "Only posted journals can be reversed."
        )

    if JournalEntry.objects.filter(reversal_of=original).exists():
        raise AccountingStateError(
            "This journal has already been reversed."
        )

    original_lines = list(
        JournalLine.objects
        .select_for_update(of=("self",))
        .select_related("account")
        .filter(entry=original)
        .order_by("line_number")
    )

    validate_journal_for_posting(original, original_lines)

    now = timezone.now()

    reversal = JournalEntry(
        organization=original.organization,
        reversal_of=original,
        entry_date=timezone.localdate(),
        currency=original.currency,
        reference=f"REV-{original.reference or original.id}"[:100],
        description=f"Reversal of {original.reference or original.id}",
        status=JournalEntry.Status.POSTED,
        created_by=actor,
        posted_by=actor,
        posted_at=now,
        reversal_reason=reversal_reason,
    )

    reversal.full_clean()
    reversal.save(force_insert=True)

    for index, original_line in enumerate(original_lines, start=1):
        reversal_line = JournalLine(
            entry=reversal,
            line_number=index,
            account=original_line.account,
            description=f"Reversal: {original_line.description}",
            debit=original_line.credit,
            credit=original_line.debit,
        )

        reversal_line.full_clean()
        reversal_line.save(force_insert=True)

    record_journal_audit(
        entry=reversal,
        actor=actor,
        operation="journal_reversal_created",
        changes={
            "journal_status": {
                "before": None,
                "after": reversal.status,
            }
        },
        metadata={
            "reversal_of_id": str(original.id),
            "reversal_reason": reversal_reason,
            "line_count": len(original_lines),
        },
    )

    previous_status = original.status

    original.status = JournalEntry.Status.REVERSED
    original.save(
        update_fields=["status", "updated_at"]
    )

    record_journal_audit(
        entry=original,
        actor=actor,
        operation="journal_reversed",
        changes={
            "journal_status": {
                "before": previous_status,
                "after": original.status,
            }
        },
        metadata={
            "reversal_entry_id": str(reversal.id),
            "reversal_reason": reversal_reason,
        },
    )

    return reversal


@transaction.atomic
def reverse_journal_entry(
    *,
    organization_id,
    journal_entry_id,
    actor,
    reversal_reason,
):
    require_accounting_role(
        organization_id=organization_id,
        actor=actor,
        allowed_roles=REVERSAL_ROLES,
    )

    if not isinstance(reversal_reason, str) or not reversal_reason.strip():
        raise AccountingStateError(
            "A reason is required to reverse a journal."
        )

    original = get_locked_journal(
        organization_id=organization_id,
        journal_entry_id=journal_entry_id,
    )

    if VendorPayment.objects.filter(journal_entry=original).exists():
        raise AccountingStateError(
            "Vendor payment journals must be reversed "
            "through the vendor payment workflow."
        )

    return _reverse_locked_journal_entry(
        original=original,
        actor=actor,
        reversal_reason=reversal_reason,
    )


@transaction.atomic
def create_adjustment_journal(
    *,
    organization_id,
    original_journal_id,
    actor,
    entry_date,
    reason,
    lines,
    description="",
):
    """
    Create a standalone draft journal correcting an existing
    posted or reversed journal.

    The adjustment is linked to its original journal through
    JournalAdjustment.

    Posting remains a separate authorized operation.
    """

    # 1. Check creation permissions.
    require_accounting_role(
        organization_id=organization_id,
        actor=actor,
        allowed_roles=DRAFT_EDIT_ROLES,
    )

    # 2. Validate the reason.
    if not isinstance(reason, str) or not reason.strip():
        raise AccountingStateError(
            "An adjustment reason is required."
        )

    # 3. Validate the effective accounting date.
    if not isinstance(entry_date, date):
        raise AccountingStateError(
            "A valid adjustment entry date is required."
        )

    # 4. Validate the supplied journal lines.
    if not isinstance(lines, (list, tuple)) or len(lines) < 2:
        raise AccountingStateError(
            "An adjustment must contain at least two journal lines."
        )

    # 5. Retrieve and lock the original journal.
    original = get_locked_journal(
        organization_id=organization_id,
        journal_entry_id=original_journal_id,
    )

    if original.status not in (
        JournalEntry.Status.POSTED,
        JournalEntry.Status.REVERSED,
    ):
        raise AccountingStateError(
            "Only posted or reversed journals can be adjusted."
        )

    if original.reversal_of_id:
        raise AccountingStateError(
            "An adjustment must reference an original journal, "
            "not a reversal entry."
        )

    # 6. Resolve and validate accounts and amounts.
    prepared_lines = []

    for index, line_data in enumerate(lines, start=1):
        if not isinstance(line_data, dict):
            raise AccountingStateError(
                f"Adjustment line {index} must be an object."
            )

        account_id = line_data.get("account_id")

        account = (
            Account.objects
            .select_for_update()
            .filter(
                pk=account_id,
                organization_id=organization_id,
            )
            .first()
        )

        if account is None:
            raise AccountingStateError(
                f"Adjustment line {index} references an "
                "account that does not belong to this organization."
            )

        if not account.is_active:
            raise AccountingStateError(
                f"Account {account.code} is inactive."
            )

        try:
            debit = Decimal(
                str(line_data.get("debit", "0.00"))
            )

            credit = Decimal(
                str(line_data.get("credit", "0.00"))
            )

        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AccountingStateError(
                f"Adjustment line {index} has an invalid amount."
            ) from exc

        validate_journal_line_amounts(
            debit=debit,
            credit=credit,
            allow_zero=False,
        )

        prepared_lines.append({
            "account": account,
            "debit": debit,
            "credit": credit,
            "description": str(
                line_data.get("description") or ""
            ).strip(),
        })

    # 7. Create the standalone draft journal.
    original_reference = (
        original.reference or str(original.id)
    )

    reference = (
        f"ADJ-{original_reference}-"
        f"{uuid.uuid4().hex[:10]}"
    )[:100]

    journal_description = (
        description.strip()
        if isinstance(description, str) and description.strip()
        else f"Adjustment of {original_reference}"
    )

    entry = JournalEntry(
        organization_id=organization_id,
        entry_date=entry_date,
        currency=original.currency,
        reference=reference,
        description=journal_description,
        status=JournalEntry.Status.DRAFT,
        created_by=actor,
    )

    entry.full_clean()
    entry.save(force_insert=True)

    # 8. Create the journal lines.
    journal_lines = []

    for index, item in enumerate(prepared_lines, start=1):
        line = JournalLine(
            entry=entry,
            line_number=index,
            account=item["account"],
            description=item["description"],
            debit=item["debit"],
            credit=item["credit"],
        )

        line.full_clean()
        line.save(force_insert=True)

        journal_lines.append(line)

    # 9. Validate the complete journal before accepting the draft.
    total_debit, total_credit = validate_journal_for_posting(
        entry,
        journal_lines,
    )

    # 10. Create the explicit adjustment relationship.
    adjustment = JournalAdjustment(
        organization_id=organization_id,
        original_journal=original,
        adjustment_journal=entry,
        reason=reason.strip(),
        created_by=actor,
    )

    adjustment.full_clean()
    adjustment.save(force_insert=True)

    # 11. Audit the standalone adjustment journal.
    record_journal_audit(
        entry=entry,
        actor=actor,
        operation="adjustment_draft_created",
        changes={
            "journal_status": {
                "before": None,
                "after": entry.status,
            }
        },
        metadata={
            "adjustment_id": str(adjustment.id),
            "original_journal_id": str(original.id),
            "original_reference": original.reference,
            "adjustment_reason": reason.strip(),
            "entry_date": entry.entry_date.isoformat(),
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "line_count": len(journal_lines),
        },
        mirror_to_invoice=False,
    )

    # 12. Also record the adjustment against the original journal.
    record_journal_audit(
        entry=original,
        actor=actor,
        operation="journal_adjustment_created",
        changes={},
        metadata={
            "adjustment_id": str(adjustment.id),
            "adjustment_journal_id": str(entry.id),
            "adjustment_reference": entry.reference,
            "adjustment_reason": reason.strip(),
        },
    )

    return entry

