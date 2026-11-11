from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from organizations.models import TimeStampedUUIDModel, Organization
from vendors.models import Vendor
from documents.models import Document
import uuid

from django.utils import timezone

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

    class PaymentTermsBasis(models.TextChoices):
        INVOICE_DATE = "invoice_date", "Invoice date"
        RECEIPT_DATE = "receipt_date", "Receipt date"
        MONTH_END = "month_end", "Month end"
        OTHER = "other", "Other"
        UNKNOWN = "unknown", "Unknown"

    class PaymentTermsSource(models.TextChoices):
        DOCUMENT = "document", "Invoice document"
        MANUAL = "manual", "Manual"

    class DueDateSource(models.TextChoices):
        DOCUMENT = "document", "Invoice document"
        CALCULATED = "calculated", "Calculated"
        MANUAL = "manual", "Manual correction"

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

    purchase_order_number = models.CharField(
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

    payment_terms = models.TextField(blank=True)

    payment_terms_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    payment_terms_basis = models.CharField(
        max_length=20,
        choices=PaymentTermsBasis.choices,
        default=PaymentTermsBasis.UNKNOWN,
    )

    payment_terms_source = models.CharField(
        max_length=20,
        choices=PaymentTermsSource.choices,
        blank=True,
        default="",
    )

    due_date_source = models.CharField(
        max_length=20,
        choices=DueDateSource.choices,
        blank=True,
        default="",
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

class InvoiceExtractionRun(TimeStampedUUIDModel):

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="extraction_runs",
    )

    provider = models.CharField(
        max_length=50,
    )

    model = models.CharField(
        max_length=150,
        blank=True,
    )

    prompt_version = models.CharField(
        max_length=40,
    )

    schema_version = models.CharField(
        max_length=40,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )

    # Exact response content returned by the provider,
    # before normalization or Pydantic validation.
    raw_response = models.TextField(
        blank=True,
        default="",
    )

    # Structured data that passed Pydantic validation.
    validated_data = models.JSONField(
        null=True,
        blank=True,
    )

    # Structured data after deterministic post-processing,
    # such as invoice-number recovery.
    postprocessed_data = models.JSONField(
        null=True,
        blank=True,
    )

    error_summary = models.TextField(
        blank=True,
        default="",
    )

    started_at = models.DateTimeField(
        default=timezone.now,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-started_at"]

        indexes = [
            models.Index(
                fields=["invoice", "started_at"],
                name="extrun_inv_start_idx",
            ),
            models.Index(
                fields=["status", "started_at"],
                name="extrun_status_start_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.provider} extraction "
            f"for {self.invoice_id} ({self.status})"
        )
    

class InvoiceTaxComponent(TimeStampedUUIDModel):

    class Treatment(models.TextChoices):
        ADDED = "added", "Added"
        DEDUCTED = "deducted", "Deducted"
        INCLUDED = "included", "Included"
        WITHHELD = "withheld", "Withheld"
        UNKNOWN = "unknown", "Unknown"

    class RecoverabilityStatus(models.TextChoices):
        NOT_ASSESSED = "not_assessed", "Not assessed"
        FULLY_RECOVERABLE = (
            "fully_recoverable",
            "Fully recoverable",
        )
        PARTIALLY_RECOVERABLE = (
            "partially_recoverable",
            "Partially recoverable",
        )
        NON_RECOVERABLE = (
            "non_recoverable",
            "Non-recoverable",
        )

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="tax_components",
    )

    position = models.PositiveIntegerField(default=1)

    name = models.CharField(max_length=100)

    tax_type = models.CharField(max_length=50)

    treatment = models.CharField(
        max_length=20,
        choices=Treatment.choices,
        default=Treatment.UNKNOWN,
    )

    rate_percent = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        null=True,
        blank=True,
    )

    taxable_base = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    recoverability_status = models.CharField(
        max_length=30,
        choices=RecoverabilityStatus.choices,
        default=RecoverabilityStatus.NOT_ASSESSED,
    )

    recoverable_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["position"]

        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "position"],
                name="unique_invoice_tax_position",
            ),
        ]

    def __str__(self):
        return f"{self.name} - {self.invoice}"

class InvoiceChargeComponent(TimeStampedUUIDModel):

    class Treatment(models.TextChoices):
        ADDED = "added", "Added"
        DEDUCTED = "deducted", "Deducted"
        INCLUDED = "included", "Included"
        UNKNOWN = "unknown", "Unknown"

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name="charge_components",
    )

    position = models.PositiveIntegerField(default=1)

    description = models.TextField()

    treatment = models.CharField(
        max_length=20,
        choices=Treatment.choices,
        default=Treatment.UNKNOWN,
    )

    amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["position"]

        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "position"],
                name="unique_invoice_charge_position",
            ),
        ]

    def __str__(self):
        return f"{self.description} - {self.invoice}"

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

    decision_reason = models.TextField(
        blank=True,
    )

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


class OutboxEvent(models.Model):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DISPATCHING = "dispatching", "Dispatching"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    event_type = models.CharField(
        max_length=100,
    )

    aggregate_id = models.UUIDField(
        db_index=True,
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )

    payload = models.JSONField(default=dict)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    attempts = models.PositiveSmallIntegerField(
        default=0,
    )

    available_at = models.DateTimeField(
        default=timezone.now,
    )

    locked_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    published_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["created_at"]

        indexes = [
            models.Index(
                fields=["status", "available_at"],
                name="outbox_status_available_idx",
            ),
            models.Index(
                fields=["status", "locked_at"],
                name="outbox_status_locked_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.event_type} "
            f"({self.aggregate_id}) - {self.status}"
        )