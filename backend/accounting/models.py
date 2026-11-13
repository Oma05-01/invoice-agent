from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from organizations.models import (
    Organization,
    TimeStampedUUIDModel,
)


class Account(TimeStampedUUIDModel):

    class AccountType(models.TextChoices):
        ASSET = "asset", "Asset"
        LIABILITY = "liability", "Liability"
        EQUITY = "equity", "Equity"
        INCOME = "income", "Income"
        EXPENSE = "expense", "Expense"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="accounts",
    )

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=255)

    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
    )

    description = models.TextField(blank=True)

    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    is_active = models.BooleanField(default=True)

    is_control_account = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="unique_org_account_code",
            ),
        ]

        indexes = [
            models.Index(
                fields=["organization", "account_type", "is_active"],
                name="account_org_type_active_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if self.parent_id:
            if self.parent.organization_id != self.organization_id:
                raise ValidationError({
                    "parent": (
                        "The parent account must belong "
                        "to the same organization."
                    )
                })

            if self.parent_id == self.pk:
                raise ValidationError({
                    "parent": "An account cannot be its own parent."
                })

            if self.parent.account_type != self.account_type:
                raise ValidationError({
                    "parent": (
                        "Parent and child accounts must "
                        "have the same account type."
                    )
                })

    def __str__(self):
        return f"{self.code} - {self.name}"


class JournalEntry(TimeStampedUUIDModel):

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="journal_entries",
    )

    source_invoice = models.OneToOneField(
        "invoices.Invoice",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_entry",
    )

    approval_decision = models.OneToOneField(
        "approvals.ApprovalDecision",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_entry",
    )

    reversal_of = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal_entry",
    )

    entry_date = models.DateField(
        default=timezone.localdate,
    )

    currency = models.CharField(max_length=3)

    reference = models.CharField(
        max_length=100,
        blank=True,
    )

    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_journal_entries",
    )

    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="posted_journal_entries",
    )

    posted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reversal_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-entry_date", "-created_at"]

        indexes = [
            models.Index(
                fields=["organization", "status", "entry_date"],
                name="journal_org_status_date_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.source_invoice_id
            and self.source_invoice.organization_id != self.organization_id
        ):
            errors["source_invoice"] = (
                "The source invoice must belong "
                "to the same organization."
            )

        if self.approval_decision_id:
            decision_invoice_id = (
                self.approval_decision.approval_request.invoice_id
            )

            if (
                self.source_invoice_id is None
                or decision_invoice_id != self.source_invoice_id
            ):
                errors["approval_decision"] = (
                    "The approval decision must belong "
                    "to the source invoice."
                )

        if (
            self.reversal_of_id
            and self.reversal_of.organization_id != self.organization_id
        ):
            errors["reversal_of"] = (
                "The original journal must belong "
                "to the same organization."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.reference or f"Journal {self.pk}"


class JournalLine(TimeStampedUUIDModel):

    entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    line_number = models.PositiveIntegerField()

    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_lines",
    )

    source_line_item = models.ForeignKey(
        "invoices.InvoiceLineItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_lines",
    )

    description = models.TextField(blank=True)

    debit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    credit = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    class Meta:
        ordering = ["line_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["entry", "line_number"],
                name="unique_journal_line_number",
            ),
            models.CheckConstraint(
                condition=(
                    Q(debit__gte=0)
                    & Q(credit__gte=0)
                    & (Q(debit=0) | Q(credit=0))
                ),
                name="journal_line_nonnegative_one_sided",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.account_id
            and self.account.organization_id != self.entry.organization_id
        ):
            errors["account"] = (
                "The account must belong to the "
                "journal's organization."
            )

        if self.source_line_item_id:
            if (
                self.entry.source_invoice_id is None
                or self.source_line_item.invoice_id
                != self.entry.source_invoice_id
            ):
                errors["source_line_item"] = (
                    "The source line item must belong "
                    "to the journal's source invoice."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.entry} - Line {self.line_number}"
        )

class JournalAdjustment(TimeStampedUUIDModel):

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="journal_adjustments",
    )

    original_journal = models.ForeignKey(
        JournalEntry,
        on_delete=models.PROTECT,
        related_name="adjustments",
    )

    adjustment_journal = models.OneToOneField(
        JournalEntry,
        on_delete=models.PROTECT,
        related_name="adjustment_record",
    )

    reason = models.TextField()

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_journal_adjustments",
    )

    class Meta:
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["organization", "created_at"],
                name="j_adj_org_created_idx",
            ),
            models.Index(
                fields=["original_journal", "created_at"],
                name="j_adj_original_created_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.original_journal_id and self.adjustment_journal_id:
            if self.original_journal_id == self.adjustment_journal_id:
                errors["adjustment_journal"] = (
                    "An adjustment cannot reference itself."
                )

            if (
                self.original_journal.organization_id
                != self.organization_id
                or self.adjustment_journal.organization_id
                != self.organization_id
            ):
                errors["organization"] = (
                    "Both journals must belong to the adjustment organization."
                )

            if (
                self.original_journal.currency
                != self.adjustment_journal.currency
            ):
                errors["adjustment_journal"] = (
                    "The original and adjustment journals "
                    "must use the same currency."
                )

            if (
                self.adjustment_journal.source_invoice_id
                or self.adjustment_journal.approval_decision_id
                or self.adjustment_journal.reversal_of_id
            ):
                errors["adjustment_journal"] = (
                    "An adjustment must be a standalone journal, "
                    "not an invoice or reversal journal."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"Adjustment of {self.original_journal.reference} "
            f"by {self.adjustment_journal.reference}"
        )


class VendorPayment(TimeStampedUUIDModel):

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"
        REVERSED = "reversed", "Reversed"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="vendor_payments",
    )

    vendor = models.ForeignKey(
        "vendors.Vendor",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    payment_date = models.DateField(
        default=timezone.localdate,
    )

    reference = models.CharField(
        max_length=100,
        blank=True,
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    currency = models.CharField(max_length=3)

    payment_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        related_name="vendor_payments",
    )

    journal_entry = models.OneToOneField(
        JournalEntry,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vendor_payment",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_vendor_payments",
    )

    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="posted_vendor_payments",
    )

    posted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reversal_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]

        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="vendor_payment_amount_positive",
            ),
        ]

        indexes = [
            models.Index(
                fields=["organization", "status", "payment_date"],
                name="vpay_org_status_date_idx",
            ),
            models.Index(
                fields=["vendor", "payment_date"],
                name="vpay_vendor_date_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.vendor_id
            and self.organization_id
            and self.vendor.organization_id != self.organization_id
        ):
            errors["vendor"] = (
                "The vendor must belong to the payment organization."
            )

        if self.payment_account_id:
            if (
                self.payment_account.organization_id
                != self.organization_id
            ):
                errors["payment_account"] = (
                    "The payment account must belong "
                    "to the payment organization."
                )

            if (
                self.payment_account.account_type
                != Account.AccountType.ASSET
            ):
                errors["payment_account"] = (
                    "The payment account must be an asset account."
                )

            if not self.payment_account.is_active:
                errors["payment_account"] = (
                    "The payment account must be active."
                )

        if self.currency and (
            len(self.currency) != 3
            or not self.currency.isalpha()
        ):
            errors["currency"] = (
                "A valid three-letter currency is required."
            )

        if self.journal_entry_id:
            journal = self.journal_entry

            if journal.organization_id != self.organization_id:
                errors["journal_entry"] = (
                    "The payment journal must belong "
                    "to the payment organization."
                )

            if journal.currency != self.currency:
                errors["journal_entry"] = (
                    "The payment and journal currencies must match."
                )

            if (
                journal.source_invoice_id
                or journal.approval_decision_id
                or journal.reversal_of_id
                or JournalAdjustment.objects.filter(
                    Q(original_journal=journal)
                    | Q(adjustment_journal=journal)
                ).exists()
            ):
                errors["journal_entry"] = (
                    "A payment must reference a standalone "
                    "journal, not an invoice, adjustment "
                    "or reversal journal."
                )

            expected_journal_status = {
                self.Status.DRAFT: JournalEntry.Status.DRAFT,
                self.Status.POSTED: JournalEntry.Status.POSTED,
                self.Status.REVERSED: JournalEntry.Status.REVERSED,
            }.get(self.status)

            if journal.status != expected_journal_status:
                errors["journal_entry"] = (
                    "The payment and journal statuses must match."
                )

        elif self.status != self.Status.DRAFT:
            errors["journal_entry"] = (
                "Posted or reversed payments must have a journal."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.reference or f"Payment {self.pk}"



class PaymentAllocation(TimeStampedUUIDModel):

    payment = models.ForeignKey(
        VendorPayment,
        on_delete=models.PROTECT,
        related_name="allocations",
    )

    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.PROTECT,
        related_name="payment_allocations",
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    class Meta:
        ordering = ["created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["payment", "invoice"],
                name="unique_payment_invoice_allocation",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payment_allocation_amount_positive",
            ),
        ]

        indexes = [
            models.Index(
                fields=["invoice", "created_at"],
                name="palloc_invoice_created_idx",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.payment_id and self.invoice_id:
            payment = self.payment
            invoice = self.invoice

            if payment.organization_id != invoice.organization_id:
                errors["invoice"] = (
                    "The payment and invoice must belong "
                    "to the same organization."
                )

            if payment.vendor_id != invoice.vendor_id:
                errors["invoice"] = (
                    "The payment and invoice must belong "
                    "to the same vendor."
                )

            if invoice.status != invoice.Status.APPROVED:
                errors["invoice"] = (
                    "Only approved invoices can receive "
                    "payment allocations."
                )

            try:
                invoice_journal = invoice.journal_entry
            except JournalEntry.DoesNotExist:
                invoice_journal = None

            if (
                invoice_journal is None
                or invoice_journal.status != JournalEntry.Status.POSTED
            ):
                errors["invoice"] = (
                    "The invoice must have a posted "
                    "accounting journal."
                )

            elif invoice_journal.currency != payment.currency:
                errors["invoice"] = (
                    "The payment and invoice journal "
                    "currencies must match."
                )

            if payment.status != VendorPayment.Status.DRAFT:
                errors["payment"] = (
                    "Allocations can only be changed "
                    "while the payment is in Draft."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.payment} - {self.invoice}: "
            f"{self.amount}"
        )
