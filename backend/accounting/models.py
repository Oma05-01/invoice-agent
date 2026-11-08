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