
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
import uuid
from organizations.models import (
    TimeStampedUUIDModel,
    Organization,
)


class ApprovalRequest(TimeStampedUUIDModel):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="approval_requests",
    )

    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.PROTECT,
        related_name="approval_requests",
    )

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_approval_requests",
    )

    submission_note = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    class Meta:
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["invoice"],
                condition=Q(status="pending"),
                name="one_pending_approval_invoice",
            ),
        ]

        indexes = [
            models.Index(
                fields=["organization", "status", "created_at"],
                name="approval_org_status_idx",
            ),
            models.Index(
                fields=["invoice", "created_at"],
                name="approval_invoice_date_idx",
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
                "The approval request organization must match "
                "the invoice organization."
            )

    def __str__(self):
        return (
            f"Approval for invoice {self.invoice_id} "
            f"({self.status})"
        )


class ApprovalDecision(models.Model):

    class Outcome(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    approval_request = models.OneToOneField(
        ApprovalRequest,
        on_delete=models.PROTECT,
        related_name="decision",
    )

    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approval_decisions",
    )

    outcome = models.CharField(
        max_length=20,
        choices=Outcome.choices,
    )

    comment = models.TextField(blank=True)

    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-decided_at"]

        indexes = [
            models.Index(
                fields=["decided_by", "decided_at"],
                name="approval_decider_date_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.approval_request_id
            and self.decided_by_id
            and self.approval_request.submitted_by_id
            == self.decided_by_id
        ):
            raise ValidationError(
                "The person who submitted an invoice cannot approve it."
            )

        if (
            self.outcome == self.Outcome.REJECTED
            and not self.comment.strip()
        ):
            raise ValidationError(
                "A rejection comment is required."
            )

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "Approval decisions are immutable."
            )

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Approval decisions cannot be deleted."
        )

    def __str__(self):
        return (
            f"{self.outcome} - "
            f"Approval {self.approval_request_id}"
        )
