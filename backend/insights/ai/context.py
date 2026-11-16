from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone as django_timezone
from organizations.models import OrganizationMembership


@dataclass(frozen=True)
class ToolContext:
    """Trusted server-side identity and organisation context for a tool call.

    Construct this from the active membership resolved for the authenticated
    request. Do not populate it with organisation or user values supplied by
    the LLM.
    """

    user: Any
    membership: OrganizationMembership

    def __post_init__(self) -> None:
        if not getattr(self.user, "is_authenticated", False):
            raise ValueError("An authenticated user is required for tool context.")

        if self.membership.user_id != self.user.pk:
            raise ValueError("The membership does not belong to the current user.")

        if not self.membership.is_active:
            raise ValueError("An active organisation membership is required.")

        if not self.membership.organization.is_active:
            raise ValueError("The organisation is inactive.")

    @property
    def organization(self):
        return self.membership.organization

    @property
    def role(self) -> str:
        return self.membership.role

    @property
    def timezone_name(self) -> str:
        """Return the organisation's configured IANA timezone."""
        return self.organization.timezone or "UTC"

    @property
    def local_today(self) -> date:
        """Return today's date in the organisation's timezone."""
        try:
            organization_timezone = ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, TypeError) as exc:
            raise ValueError("The organisation timezone is invalid.") from exc
        return django_timezone.now().astimezone(organization_timezone).date()
