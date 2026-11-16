import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from organizations.models import Organization


def validate_tool_invocations(value):
    """Allow only non-sensitive tool invocation metadata to be persisted."""
    if not isinstance(value, list):
        raise ValidationError("Tool invocations must be a list.")

    for index, invocation in enumerate(value):
        if not isinstance(invocation, dict):
            raise ValidationError(
                f"Tool invocation at position {index} must be an object."
            )

        if set(invocation) != {"name", "succeeded"}:
            raise ValidationError(
                "Tool invocation metadata may contain only name and succeeded."
            )

        name = invocation.get("name")
        succeeded = invocation.get("succeeded")

        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise ValidationError(
                f"Tool invocation at position {index} has an invalid name."
            )

        if type(succeeded) is not bool:
            raise ValidationError(
                f"Tool invocation at position {index} has an invalid succeeded value."
            )


class AssistantConversation(models.Model):
    """A private financial-assistant conversation for one organisation member."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="assistant_conversations",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="financial_assistant_conversations",
    )

    title = models.CharField(
        max_length=160,
        default="New conversation",
    )

    last_message_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(
                fields=["organization", "created_by", "-last_message_at"],
                name="ins_asst_owner_activity",
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.organization})"


class AssistantMessage(models.Model):
    """One persisted user or assistant turn in a conversation."""

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    conversation = models.ForeignKey(
        AssistantConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sequence = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )

    role = models.CharField(
        max_length=12,
        choices=Role.choices,
    )

    content = models.TextField()

    # Model and tool metadata are populated for assistant turns only.
    # Tool arguments and financial report payloads are intentionally not stored.
    model = models.CharField(
        max_length=120,
        blank=True,
        default="",
    )

    tool_call_count = models.PositiveSmallIntegerField(default=0)

    tool_invocations = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_tool_invocations],
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "sequence"],
                name="ins_asst_msg_seq_uniq",
            ),
        ]

    def clean(self):
        super().clean()

        if self.role == self.Role.USER:
            errors = {}
            if self.model:
                errors["model"] = "User messages cannot specify an AI model."
            if self.tool_call_count or self.tool_invocations:
                errors["tool_invocations"] = (
                    "User messages cannot contain tool invocation metadata."
                )
            if errors:
                raise ValidationError(errors)

        if self.role == self.Role.ASSISTANT:
            if self.tool_call_count != len(self.tool_invocations or []):
                raise ValidationError({
                    "tool_call_count": (
                        "Tool call count must match the invocation metadata."
                    )
                })

    def __str__(self):
        return f"{self.get_role_display()} message {self.sequence}"
