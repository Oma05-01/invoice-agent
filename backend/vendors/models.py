
# Create your models here.
from django.db import models
from django.db.models import Q

from organizations.models import TimeStampedUUIDModel, Organization


class Vendor(TimeStampedUUIDModel):

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="vendors",
    )

    vendor_code = models.CharField(max_length=50, blank=True)

    legal_name = models.CharField(max_length=255)

    display_name = models.CharField(
        max_length=255,
        blank=True,
    )

    tax_identification_number = models.CharField(
        max_length=50,
        blank=True,
    )

    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["legal_name"]

        constraints = [
            models.UniqueConstraint(
                fields=["organization", "vendor_code"],
                condition=Q(vendor_code__gt=""),
                name="unique_org_vendor_code",
            ),
        ]

        indexes = [
            models.Index(
                fields=["organization", "legal_name"],
                name="vendor_org_name_idx",
            ),
        ]

    def __str__(self):
        return self.display_name or self.legal_name