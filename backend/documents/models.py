import uuid

from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import Q

from organizations.models import TimeStampedUUIDModel, Organization


def document_upload_path(instance, filename):
    """
    Store files inside organisation-specific directories.

    Use a generated filename rather than trusting the
    original uploaded filename.
    """

    suffix = Path(instance.original_filename or filename).suffix.lower()

    return (
        f"organizations/{instance.organization_id}/"
        f"documents/{uuid.uuid4().hex}{suffix}"
    )


class Document(TimeStampedUUIDModel):

    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    class Source(models.TextChoices):
        UPLOAD = "upload", "Manual Upload"
        EMAIL = "email", "Email"
        API = "api", "API Integration"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="documents",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_finance_documents",
    )

    processing_error = models.TextField(blank=True)

    original_filename = models.CharField(max_length=255)

    file = models.FileField(
        upload_to=document_upload_path,
    )

    content_type = models.CharField(max_length=100)

    file_size = models.PositiveBigIntegerField(default=0)

    sha256 = models.CharField(
        max_length=64,
        blank=True,
        null=True,
    )

    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.UPLOAD,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADED,
    )

    class Meta:
        ordering = ["-created_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sha256"],
                condition=Q(sha256__isnull=False),
                name="unique_org_document_hash",
            ),
        ]

        indexes = [
            models.Index(
                fields=["organization", "status"],
                name="document_org_status_idx",
            ),
        ]

    def __str__(self):
        return self.original_filename