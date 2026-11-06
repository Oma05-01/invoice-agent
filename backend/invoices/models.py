from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from organizations.models import TimeStampedUUIDModel, Organization
from vendors.models import Vendor
from documents.models import Document


class Invoice(TimeStampedUUIDModel):

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        EXTRACTING = "extracting", "Extracting"
        NEEDS_REVIEW = "needs_review", "Needs Review"
        PENDING_APPROVAL = "pending_approval", "Pending Approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPORTED = "exported", "Exported"
        FAILED = "failed", "Failed"
        QUEUED = "queued", "Queued"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="invoices",
    )

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
    )

    source_document = models.OneToOneField(
        Document,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoice",
    )

    invoice_number = models.CharField(
        max_length=100,
        blank=True,
    )

    invoice_date = models.DateField(
        null=True,
        blank=True,
    )

    due_date = models.DateField(
        null=True,
        blank=True,
    )

    currency = models.CharField(
        max_length=3,
        null=True,
        blank=True,
        default=None,
    )

    subtotal = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    tax_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    other_charges = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    total_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    amount_due = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    description = models.TextField(blank=True)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.UPLOADED,
    )

    extracted_data = models.JSONField(default=dict)

    field_confidence = models.JSONField(default=dict)

    processing_task_id = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
    )

    queued_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "vendor",
                    "invoice_number",
                ],
                condition=(
                    Q(invoice_number__gt="")
                    & Q(vendor__isnull=False)
                ),
                name="unique_org_vendor_invoice_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["organization", "status", "created_at"],
                name="invoice_org_status_idx",
            ),
            models.Index(
                fields=["organization", "invoice_date"],
                name="invoice_org_date_idx",
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
                "The selected vendor does not belong to this organization."
            )

        if (
            self.source_document_id
            and self.organization_id
            and self.source_document.organization_id != self.organization_id
        ):
            errors["source_document"] = (
                "The source document does not belong to this organization."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.invoice_number or f"Invoice {self.pk}"


class InvoiceLineItem(TimeStampedUUIDModel):

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="line_items",
    )

    position = models.PositiveIntegerField(default=1)

    description = models.TextField()

    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
    )

    unit_price = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    tax_rate = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        null=True,
        blank=True,
    )

    line_total = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    suggested_category = models.CharField(
        max_length=100,
        blank=True,
    )

    ledger_code = models.CharField(
        max_length=50,
        blank=True,
    )

    class Meta:
        ordering = ["position"]

        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "position"],
                name="unique_invoice_line_position",
            ),
        ]

    def __str__(self):
        return self.description

class InvoiceValidationIssue(TimeStampedUUIDModel):

    class Severity(models.TextChoices):
        INFO = "info", "Information"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        IGNORED = "ignored", "Ignored"

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="validation_issues",
    )

    code = models.CharField(max_length=100)

    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
    )

    field_name = models.CharField(
        max_length=100,
        blank=True,
    )

    message = models.TextField()

    details = models.JSONField(default=dict)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_invoice_issues",
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["invoice", "status", "severity"],
                name="invoice_issue_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.code}: {self.invoice}"