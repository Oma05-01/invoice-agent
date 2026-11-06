
# Create your models here.
import uuid

from django.db import models


class TimeStampedUUIDModel(models.Model):
    """
    Shared base model for business records.

    UUID primary keys make records easier to reference across
    APIs and external integrations.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimeStampedUUIDModel):
    name = models.CharField(max_length=255)

    legal_name = models.CharField(
        max_length=255,
        blank=True,
    )

    slug = models.SlugField(
        max_length=100,
        unique=True,
    )

    default_currency = models.CharField(
        max_length=3,
        default="NGN",
    )

    timezone = models.CharField(
        max_length=50,
        default="Africa/Lagos",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "organizations"

    def __str__(self):
        return self.name