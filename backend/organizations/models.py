
# Create your models here.
from django.conf import settings
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
    
class OrganizationMembership(TimeStampedUUIDModel):

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        FINANCE_ADMIN = "finance_admin", "Finance Administrator"
        FINANCE_OPERATOR = "finance_operator", "Finance Operator"
        FINANCE_REVIEWER = "finance_reviewer", "Finance Reviewer"
        READ_ONLY = "read_only", "Read Only"

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
    )

    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.FINANCE_OPERATOR,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_org_user_membership",
            ),
        ]

        indexes = [
            models.Index(
                fields=["user", "is_active"],
                name="org_membership_user_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.organization} ({self.role})"

    