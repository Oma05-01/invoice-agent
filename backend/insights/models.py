import json
import re
import uuid
from datetime import date

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

MAX_REPORT_ARTIFACTS = 4
MAX_REPORT_ARTIFACT_SIZE = 250_000
MONEY_PATTERN = re.compile(r"^-?\d{1,18}\.\d{2}$")
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

REPORT_KEYS = {
    "dimension",
    "period",
    "limit_per_currency",
    "currencies",
    "report_basis",
}
CURRENCY_REPORT_KEYS = {
    "currency",
    "rows",
    "total_expenditure",
    "gross_debits",
    "gross_credits",
    "journal_count",
    "journal_line_count",
    "displayed_rows_expenditure",
    "group_count",
    "returned_group_count",
    "is_truncated",
}
ROW_ACTIVITY_KEYS = {
    "amount",
    "gross_debits",
    "gross_credits",
    "journal_count",
    "journal_line_count",
}


def _valid_iso_date(value):
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _valid_money(value):
    return isinstance(value, str) and bool(MONEY_PATTERN.fullmatch(value))


def _valid_nonnegative_integer(value):
    return type(value) is int and 0 <= value <= 1_000_000_000


def _valid_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def validate_report_artifacts(value):
    """Validate bounded, versioned server-generated financial report data."""
    if not isinstance(value, list):
        raise ValidationError("Report artifacts must be a list.")

    if len(value) > MAX_REPORT_ARTIFACTS:
        raise ValidationError("Too many report artifacts.")

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise ValidationError("Report artifacts must contain JSON data.")

    if len(encoded) > MAX_REPORT_ARTIFACT_SIZE:
        raise ValidationError("Report artifacts exceed the permitted size.")

    for index, artifact in enumerate(value):
        if not isinstance(artifact, dict) or set(artifact) != {
            "schema_version",
            "tool",
            "report",
        }:
            raise ValidationError(
                f"Report artifact {index} has an invalid structure."
            )

        if type(artifact["schema_version"]) is not int or artifact["schema_version"] != 1:
            raise ValidationError("Unsupported report artifact schema version.")

        if artifact["tool"] != "spend_by":
            raise ValidationError("Unsupported report artifact tool.")

        report = artifact["report"]
        if not isinstance(report, dict) or set(report) != REPORT_KEYS:
            raise ValidationError(f"Report artifact {index} has invalid report fields.")

        dimension = report["dimension"]
        if dimension not in {"vendor", "account", "month"}:
            raise ValidationError("Invalid report dimension.")

        period = report["period"]
        if not isinstance(period, dict) or set(period) != {
            "start_date",
            "end_date",
        }:
            raise ValidationError("Invalid report period.")

        start_date = period["start_date"]
        end_date = period["end_date"]
        if (
            not _valid_iso_date(start_date)
            or not _valid_iso_date(end_date)
            or start_date > end_date
        ):
            raise ValidationError("Invalid report dates.")

        limit = report["limit_per_currency"]
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError("Invalid report row limit.")

        report_basis = report["report_basis"]
        if not isinstance(report_basis, str) or len(report_basis) > 5_000:
            raise ValidationError("Invalid report basis.")

        currencies = report["currencies"]
        if not isinstance(currencies, list) or len(currencies) > 10:
            raise ValidationError("Invalid report currency groups.")

        for currency_report in currencies:
            if (
                not isinstance(currency_report, dict)
                or set(currency_report) != CURRENCY_REPORT_KEYS
            ):
                raise ValidationError("Invalid currency report structure.")

            currency = currency_report["currency"]
            if currency != "UNKNOWN" and (
                not isinstance(currency, str)
                or not CURRENCY_PATTERN.fullmatch(currency)
            ):
                raise ValidationError("Invalid report currency.")

            for field in (
                "total_expenditure",
                "gross_debits",
                "gross_credits",
                "displayed_rows_expenditure",
            ):
                if not _valid_money(currency_report[field]):
                    raise ValidationError(f"Invalid report amount: {field}.")

            for field in (
                "journal_count",
                "journal_line_count",
                "group_count",
                "returned_group_count",
            ):
                if not _valid_nonnegative_integer(currency_report[field]):
                    raise ValidationError(f"Invalid report count: {field}.")

            rows = currency_report["rows"]
            if not isinstance(rows, list) or len(rows) > limit:
                raise ValidationError("Invalid report rows.")

            if currency_report["returned_group_count"] != len(rows):
                raise ValidationError("Returned group count does not match report rows.")

            if currency_report["group_count"] < len(rows):
                raise ValidationError("Report group count is smaller than returned rows.")

            if type(currency_report["is_truncated"]) is not bool:
                raise ValidationError("Invalid report truncation indicator.")

            if currency_report["is_truncated"] != (
                currency_report["group_count"] > len(rows)
            ):
                raise ValidationError("Report truncation indicator is inconsistent.")

            for row in rows:
                if not isinstance(row, dict):
                    raise ValidationError("Invalid report row.")

                if dimension == "vendor":
                    expected_keys = ROW_ACTIVITY_KEYS | {
                        "vendor_id",
                        "vendor_name",
                    }
                elif dimension == "account":
                    expected_keys = ROW_ACTIVITY_KEYS | {
                        "account_id",
                        "account_code",
                        "account_name",
                    }
                else:
                    expected_keys = ROW_ACTIVITY_KEYS | {"month"}

                if set(row) != expected_keys:
                    raise ValidationError("Report row fields do not match its dimension.")

                for field in ("amount", "gross_debits", "gross_credits"):
                    if not _valid_money(row[field]):
                        raise ValidationError(f"Invalid report row amount: {field}.")

                for field in ("journal_count", "journal_line_count"):
                    if not _valid_nonnegative_integer(row[field]):
                        raise ValidationError(f"Invalid report row count: {field}.")

                if dimension == "vendor":
                    if row["vendor_id"] is not None and not _valid_uuid(row["vendor_id"]):
                        raise ValidationError("Invalid report vendor identifier.")
                    if (
                        not isinstance(row["vendor_name"], str)
                        or not row["vendor_name"].strip()
                        or len(row["vendor_name"]) > 255
                    ):
                        raise ValidationError("Invalid report vendor name.")

                elif dimension == "account":
                    if not _valid_uuid(row["account_id"]):
                        raise ValidationError("Invalid report account identifier.")
                    if (
                        not isinstance(row["account_code"], str)
                        or not row["account_code"].strip()
                        or len(row["account_code"]) > 50
                    ):
                        raise ValidationError("Invalid report account code.")
                    if (
                        not isinstance(row["account_name"], str)
                        or not row["account_name"].strip()
                        or len(row["account_name"]) > 255
                    ):
                        raise ValidationError("Invalid report account name.")

                elif not _valid_iso_date(row["month"]):
                    raise ValidationError("Invalid report month.")
                

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

    report_artifacts = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_report_artifacts],
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
            if self.report_artifacts:
                errors["report_artifacts"] = (
                    "User messages cannot contain financial report artifacts."
                )

        if self.role == self.Role.ASSISTANT:
            if self.tool_call_count != len(self.tool_invocations or []):
                raise ValidationError({
                    "tool_call_count": (
                        "Tool call count must match the invocation metadata."
                    )
                })

    def __str__(self):
        return f"{self.get_role_display()} message {self.sequence}"
