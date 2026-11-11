
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class InvoiceAuditEvent(models.Model):

    class Action(models.TextChoices):
        PROCESSING_QUEUED = (
            "processing_queued",
            "Processing Queued",
        )
        REVIEW_STARTED = (
            "review_started",
            "Review Started",
        )
        FIELD_UPDATED = (
            "field_updated",
            "Field Updated",
        )
        VENDOR_ASSIGNED = (
            "vendor_assigned",
            "Vendor Assigned",
        )
        VALIDATION_ISSUE_RESOLVED = (
            "validation_issue_resolved",
            "Validation Issue Resolved",
        )
        VALIDATION_ISSUE_IGNORED = (
            "validation_issue_ignored",
            "Validation Issue Ignored",
        )
        REVIEW_SUBMITTED = (
            "review_submitted",
            "Review Submitted",
        )
        APPROVAL_REQUESTED = (
            "approval_requested",
            "Approval Requested",
        )
        APPROVAL_GRANTED = (
            "approval_granted",
            "Approval Granted",
        )
        APPROVAL_REJECTED = (
            "approval_rejected",
            "Approval Rejected",
        )
        REOPENED_FOR_REVIEW = (
            "reopened_for_review",
            "Returned for Review",
        )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="invoice_audit_events",
    )

    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.PROTECT,
        related_name="audit_events",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoice_audit_events",
    )

    action = models.CharField(
        max_length=100,
        choices=Action.choices,
    )

    changes = models.JSONField(
        default=dict,
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["organization", "created_at"],
                name="audit_org_created_idx",
            ),
            models.Index(
                fields=["invoice", "created_at"],
                name="audit_invoice_created_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.invoice_id
            and self.organization_id
            and self.invoice.organization_id != self.organization_id
        ):
            raise ValidationError(
                "The audit event organization must match the invoice organization."
            )

    def __str__(self):
        return (
            f"{self.action} - Invoice {self.invoice_id}"
        )


class JournalAuditEvent(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="journal_audit_events",
    )

    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.PROTECT,
        related_name="audit_events",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_audit_events",
    )

    operation = models.CharField(max_length=100)

    changes = models.JSONField(
        default=dict,
        blank=True,
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

        indexes = [
            models.Index(
                fields=["organization", "created_at"],
                name="j_audit_org_created_idx",
            ),
            models.Index(
                fields=["journal_entry", "created_at"],
                name="j_audit_entry_created_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.journal_entry_id
            and self.organization_id
            and self.journal_entry.organization_id
            != self.organization_id
        ):
            raise ValidationError(
                "The audit event organization must match "
                "the journal organization."
            )

    def __str__(self):
        return (
            f"{self.operation} - Journal "
            f"{self.journal_entry_id}"
        )
