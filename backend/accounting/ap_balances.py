
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from accounting.models import (
    Account,
    JournalAdjustment,
    JournalEntry,
    JournalLine,
    PaymentAllocation,
    VendorPayment,
)


ZERO = Decimal("0.00")

REPORTABLE_STATUSES = (
    JournalEntry.Status.POSTED,
    JournalEntry.Status.REVERSED,
)


def get_invoice_ap_obligation(*, invoice, as_of_date):
    """
    Calculate an invoice's net AP obligation as of a date.

    Includes:
    - The original invoice journal.
    - Posted adjustments linked to that journal, including nested
      adjustments.
    - Posted reversal journals for those entries.

    Draft journals are excluded. Journal entry dates and actual
    posting dates must both be on or before the reporting date.
    """

    try:
        invoice_journal = invoice.journal_entry
    except JournalEntry.DoesNotExist:
        return ZERO

    if (
        invoice_journal.status not in REPORTABLE_STATUSES
        or invoice_journal.entry_date > as_of_date
        or invoice_journal.posted_at is None
        or timezone.localtime(invoice_journal.posted_at).date()
        > as_of_date
    ):
        return ZERO

    # Discover all adjustments linked to the invoice journal.
    # Nested adjustments are supported.
    related_journal_ids = {invoice_journal.pk}
    pending_ids = {invoice_journal.pk}

    while pending_ids:
        adjustment_ids = set(
            JournalAdjustment.objects.filter(
                organization_id=invoice.organization_id,
                original_journal_id__in=pending_ids,
            ).values_list(
                "adjustment_journal_id",
                flat=True,
            )
        )

        new_ids = adjustment_ids - related_journal_ids

        related_journal_ids.update(new_ids)
        pending_ids = new_ids

    # Include original journals and their reversal entries.
    relevant_entries = (
        JournalEntry.objects
        .filter(
            organization_id=invoice.organization_id,
            status__in=REPORTABLE_STATUSES,
            entry_date__lte=as_of_date,
            posted_at__date__lte=as_of_date,
        )
        .filter(
            Q(pk__in=related_journal_ids)
            | Q(reversal_of_id__in=related_journal_ids)
        )
    )

    totals = (
        JournalLine.objects
        .filter(
            entry__in=relevant_entries,
            account__organization_id=invoice.organization_id,
            account__code="2000",
            account__account_type=Account.AccountType.LIABILITY,
            account__is_control_account=True,
        )
        .aggregate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        )
    )

    debit = totals["total_debit"] or ZERO
    credit = totals["total_credit"] or ZERO

    return credit - debit


def get_invoice_posted_payment_allocations(
    *,
    invoice,
    as_of_date,
):
    """
    Calculate allocations from payments that had actually been
    posted by the reporting date.

    A payment reduces AP only after it has been posted.
    A reversed payment remains a historical settlement before
    its reversal becomes effective.

    Draft payments never reduce AP ageing.
    """

    queryset = PaymentAllocation.objects.filter(
        invoice_id=invoice.pk,
        payment__organization_id=invoice.organization_id,
        payment__status__in=(
            VendorPayment.Status.POSTED,
            VendorPayment.Status.REVERSED,
        ),
        payment__posted_by__isnull=False,
        payment__posted_at__isnull=False,
        payment__posted_at__date__lte=as_of_date,
        payment__journal_entry__status__in=REPORTABLE_STATUSES,
        payment__journal_entry__entry_date__lte=as_of_date,
        payment__journal_entry__posted_at__date__lte=as_of_date,
    )

    # A reversal only releases the payment allocation after the
    # reversal journal has become effective and has been posted.
    queryset = queryset.filter(
        Q(
            payment__journal_entry__reversal_entry__isnull=True,
        )
        |
        Q(
            payment__journal_entry__reversal_entry__entry_date__gt=as_of_date,
        )
        |
        Q(
            payment__journal_entry__reversal_entry__posted_at__date__gt=as_of_date,
        )
    )

    result = queryset.aggregate(
        total_allocated=Sum("amount"),
    )

    return result["total_allocated"] or ZERO
