import json
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from insights.ai.context import ToolContext
from insights.ai.registry import (
    ToolArgumentError,
    ToolDefinition,
    ToolPermissionError,
    ToolRegistry,
    UnknownToolError,
    build_tool_registry,
)
from insights.ai.schemas import SpendByArguments
from organizations.models import Organization, OrganizationMembership


class SpendToolSchemaTests(TestCase):
    def test_valid_arguments_are_parsed_and_currency_is_normalized(self):
        arguments = SpendByArguments.model_validate({
            "dimension": "vendor",
            "start_date": "2026-01-01",
            "end_date": "2026-11-16",
            "currency": " ngn ",
        })

        self.assertEqual(arguments.start_date, date(2026, 1, 1))
        self.assertEqual(arguments.end_date, date(2026, 11, 16))
        self.assertEqual(arguments.currency, "NGN")
        self.assertEqual(arguments.limit, 20)

    def test_invalid_dimension_is_rejected(self):
        with self.assertRaises(Exception):
            SpendByArguments.model_validate({
                "dimension": "customer",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
            })

    def test_end_date_before_start_date_is_rejected(self):
        with self.assertRaises(Exception):
            SpendByArguments.model_validate({
                "dimension": "vendor",
                "start_date": "2026-02-01",
                "end_date": "2026-01-31",
            })

    def test_limit_is_bounded(self):
        with self.assertRaises(Exception):
            SpendByArguments.model_validate({
                "dimension": "vendor",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "limit": 101,
            })

    def test_model_cannot_supply_organisation_or_user_context(self):
        with self.assertRaises(Exception):
            SpendByArguments.model_validate({
                "dimension": "vendor",
                "start_date": "2026-01-01",
                "end_date": "2026-01-31",
                "organization_id": "attacker-controlled-id",
            })


class ToolContextTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="insights_tool_user",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Insights Tool Company",
            slug="insights-tool-company",
            default_currency="NGN",
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.READ_ONLY,
        )

    def test_context_uses_membership_organisation_and_role(self):
        context = ToolContext(user=self.user, membership=self.membership)

        self.assertEqual(context.organization, self.organization)
        self.assertEqual(context.role, OrganizationMembership.Role.READ_ONLY)

    def test_context_rejects_membership_for_another_user(self):
        User = get_user_model()
        other_user = User.objects.create_user(
            username="different_insights_user",
            password="test-password-123",
        )
        with self.assertRaises(ValueError):
            ToolContext(user=other_user, membership=self.membership)

    def test_context_rejects_inactive_membership(self):
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])

        with self.assertRaises(ValueError):
            ToolContext(user=self.user, membership=self.membership)

    def test_context_rejects_inactive_organisation(self):
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])

        with self.assertRaises(ValueError):
            ToolContext(user=self.user, membership=self.membership)


class ToolRegistryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="insights_registry_user",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Insights Registry Company",
            slug="insights-registry-company",
            default_currency="NGN",
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.READ_ONLY,
        )
        self.context = ToolContext(
            user=self.user,
            membership=self.membership,
        )
        self.registry = build_tool_registry()
        self.valid_arguments = {
            "dimension": "vendor",
            "start_date": "2026-01-01",
            "end_date": "2026-11-16",
            "currency": "ngn",
        }

    @patch("insights.ai.registry.spend_by")
    def test_spend_tool_executes_with_server_side_organisation(self, spend_mock):
        expected = {"dimension": "vendor", "currencies": []}
        spend_mock.return_value = expected

        result = self.registry.execute(
            "spend_by",
            json.dumps(self.valid_arguments),
            self.context,
        )

        self.assertEqual(result, expected)
        spend_mock.assert_called_once()
        args, kwargs = spend_mock.call_args
        self.assertEqual(args[0], self.organization)
        self.assertEqual(kwargs["dimension"], "vendor")
        self.assertEqual(kwargs["currency"], "NGN")
        self.assertEqual(kwargs["start_date"], date(2026, 1, 1))

    @patch("insights.ai.registry.spend_by")
    def test_invalid_arguments_do_not_execute_tool(self, spend_mock):
        invalid = {**self.valid_arguments, "limit": 1000}

        with self.assertRaises(ToolArgumentError):
            self.registry.execute("spend_by", invalid, self.context)

        spend_mock.assert_not_called()

    def test_unknown_tool_is_rejected(self):
        with self.assertRaises(UnknownToolError):
            self.registry.execute("delete_journal", {}, self.context)

    def test_malformed_json_is_rejected(self):
        with self.assertRaises(ToolArgumentError):
            self.registry.execute("spend_by", "{not-json", self.context)

    def test_tool_schema_does_not_expose_user_or_organisation_arguments(self):
        tools = self.registry.available_tools(self.context)
        self.assertEqual(len(tools), 1)
        function = tools[0]["function"]
        self.assertEqual(function["name"], "spend_by")
        properties = function["parameters"]["properties"]
        self.assertNotIn("organization_id", properties)
        self.assertNotIn("user_id", properties)

    def test_role_restricted_tool_is_hidden_and_rejected(self):
        restricted = ToolDefinition(
            name="owner_only_report",
            description="Owner-only test tool.",
            arguments_model=SpendByArguments,
            allowed_roles=frozenset({OrganizationMembership.Role.OWNER}),
            handler=lambda _context, _arguments: {"ok": True},
        )
        self.registry.register(restricted)

        available_names = {
            item["function"]["name"]
            for item in self.registry.available_tools(self.context)
        }
        self.assertNotIn("owner_only_report", available_names)

        with self.assertRaises(ToolPermissionError):
            self.registry.execute("owner_only_report", self.valid_arguments, self.context)

    def test_all_existing_read_roles_can_access_read_only_spend_tool(self):
        allowed_roles = {
            OrganizationMembership.Role.OWNER,
            OrganizationMembership.Role.FINANCE_ADMIN,
            OrganizationMembership.Role.FINANCE_OPERATOR,
            OrganizationMembership.Role.FINANCE_REVIEWER,
            OrganizationMembership.Role.READ_ONLY,
        }
        definition = self.registry._tools["spend_by"]
        self.assertEqual(definition.allowed_roles, allowed_roles)
