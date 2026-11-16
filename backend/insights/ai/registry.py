import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ValidationError

from insights.ai.context import ToolContext
from insights.ai.schemas import SpendByArguments
from insights.services.spend import SpendReportError, spend_by
from organizations.models import OrganizationMembership


class ToolRegistryError(Exception):
    """Base class for expected tool-registry failures."""


class UnknownToolError(ToolRegistryError):
    """Raised when the model requests a tool that is not registered."""


class ToolPermissionError(ToolRegistryError):
    """Raised when the current membership cannot execute a tool."""


class ToolArgumentError(ToolRegistryError):
    """Raised when tool arguments are malformed or fail schema validation."""


class ToolExecutionError(ToolRegistryError):
    """Raised for an expected domain error during tool execution."""


ToolHandler = Callable[[ToolContext, BaseModel], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments_model: type[BaseModel]
    allowed_roles: frozenset[str]
    handler: ToolHandler

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", self.name):
            raise ValueError("Tool names must be lowercase snake_case identifiers.")
        if not self.description.strip():
            raise ValueError("A tool description is required.")
        if not self.allowed_roles:
            raise ValueError("At least one allowed role is required.")

    def as_groq_tool(self) -> dict[str, Any]:
        """Return the function-tool schema expected by Groq chat completions."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }


class ToolRegistry:
    """Small explicit registry for server-executed, permissioned tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool '{definition.name}' is already registered.")
        self._tools[definition.name] = definition

    def available_tools(self, context: ToolContext) -> list[dict[str, Any]]:
        """Return only the tools the current membership is allowed to use."""
        return [
            definition.as_groq_tool()
            for definition in self._tools.values()
            if context.role in definition.allowed_roles
        ]

    def execute(
        self,
        name: str,
        arguments: str | Mapping[str, Any],
        context: ToolContext,
    ) -> Any:
        definition = self._tools.get(name)
        if definition is None:
            raise UnknownToolError(f"Unknown tool: {name}.")

        if context.role not in definition.allowed_roles:
            raise ToolPermissionError("Your organisation role cannot use this tool.")

        payload = self._decode_arguments(arguments)
        try:
            validated_arguments = definition.arguments_model.model_validate(payload)
        except ValidationError as exc:
            messages = []
            for issue in exc.errors(include_input=False):
                location = ".".join(str(part) for part in issue.get("loc", ()))
                message = issue.get("msg", "Invalid value")
                messages.append(f"{location}: {message}" if location else message)
            raise ToolArgumentError("; ".join(messages)) from exc

        try:
            return definition.handler(context, validated_arguments)
        except SpendReportError as exc:
            raise ToolExecutionError(str(exc)) from exc

    @staticmethod
    def _decode_arguments(
        arguments: str | Mapping[str, Any],
    ) -> dict[str, Any]:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ToolArgumentError("Tool arguments must be valid JSON.") from exc

        if not isinstance(arguments, Mapping):
            raise ToolArgumentError("Tool arguments must be a JSON object.")

        return dict(arguments)


def _run_spend_by(context: ToolContext, arguments: SpendByArguments) -> dict[str, Any]:
    """Run expenditure reporting without permitting future accounting dates."""
    current_date = context.local_today
    if arguments.start_date > current_date:
        raise SpendReportError(
            f"start_date {arguments.start_date.isoformat()} is after "
            f"the organisation's current date ({current_date.isoformat()})."
        )
    if arguments.end_date > current_date:
        raise SpendReportError(
            f"end_date {arguments.end_date.isoformat()} is after the "
            f"organisation's current date ({current_date.isoformat()})."
        )

    return spend_by(
        context.organization,
        dimension=arguments.dimension,
        start_date=arguments.start_date,
        end_date=arguments.end_date,
        limit=arguments.limit,
        currency=arguments.currency,
    )


def build_tool_registry() -> ToolRegistry:
    """Build the initial read-only financial tool registry.

    Every active organisation role may read reports, matching the existing
    accounting-report API. Future write-capable tools must declare a narrower
    permission set and receive their own server-side authorization checks.
    """
    registry = ToolRegistry()
    report_roles = frozenset({
        OrganizationMembership.Role.OWNER,
        OrganizationMembership.Role.FINANCE_ADMIN,
        OrganizationMembership.Role.FINANCE_OPERATOR,
        OrganizationMembership.Role.FINANCE_REVIEWER,
        OrganizationMembership.Role.READ_ONLY,
    })
    registry.register(ToolDefinition(
        name="spend_by",
        description=(
            "Return posted expenditure for the authenticated organisation, "
            "grouped by vendor, expense account, or accounting month. "
            "The report keeps currencies separate and includes reversal "
            "journals on their own accounting entry dates. Use this tool "
            "for questions about expenditure totals or breakdowns."
        ),
        arguments_model=SpendByArguments,
        allowed_roles=report_roles,
        handler=_run_spend_by,
    ))
    return registry
