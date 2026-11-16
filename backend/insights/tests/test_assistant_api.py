from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from insights.ai.context import ToolContext
from insights.ai.groq_client import (
    FinancialAssistantConfigurationError,
    FinancialAssistantProviderError,
    FinancialAssistantResponse,
    FinancialAssistantToolLimitError,
    ToolInvocation,
)
from organizations.models import Organization, OrganizationMembership


class FinancialAssistantChatAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.reader = User.objects.create_user(
            username="assistant_api_reader",
            password="test-password-123",
        )
        self.outsider = User.objects.create_user(
            username="assistant_api_outsider",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Assistant API Company",
            slug="assistant-api-company",
            default_currency="NGN",
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.reader,
            role=OrganizationMembership.Role.READ_ONLY,
        )
        self.client = APIClient()
        self.url = reverse(
            "insights-assistant-chat",
            kwargs={"organization_id": self.organization.id},
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_member_can_submit_question_and_receive_answer(self, service_class):
        service = service_class.return_value
        service.answer.return_value = FinancialAssistantResponse(
            answer="Total expenditure was NGN 1,250.00 for the requested period.",
            model="openai/gpt-oss-20b",
            tool_invocations=(ToolInvocation("call_1", "spend_by", True),),
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "How much did we spend this month?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["answer"],
            "Total expenditure was NGN 1,250.00 for the requested period.",
        )
        self.assertEqual(response.data["model"], "openai/gpt-oss-20b")
        self.assertEqual(response.data["tool_call_count"], 1)
        self.assertEqual(
            response.data["tool_invocations"],
            [{"name": "spend_by", "succeeded": True}],
        )
        service.answer.assert_called_once()
        question = service.answer.call_args.args[0]
        context = service.answer.call_args.kwargs["context"]
        self.assertEqual(question, "How much did we spend this month?")
        self.assertIsInstance(context, ToolContext)
        self.assertEqual(context.user, self.reader)
        self.assertEqual(context.membership, self.membership)
        self.assertEqual(context.organization, self.organization)
        self.assertEqual(context.role, OrganizationMembership.Role.READ_ONLY)

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_question_is_trimmed_before_service_call(self, service_class):
        service = service_class.return_value
        service.answer.return_value = FinancialAssistantResponse(
            answer="No matching records were found.",
            model="openai/gpt-oss-20b",
            tool_invocations=(),
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "  Show monthly expenditure  "},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            service.answer.call_args.args[0],
            "Show monthly expenditure",
        )

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_client_cannot_supply_organisation_or_user_context(self, service_class):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {
                "question": "Show expenditure.",
                "organization_id": "another-organization",
                "user_id": 999,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("non_field_errors", response.data)
        service_class.assert_not_called()

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_missing_question_is_rejected(self, service_class):
        self.authenticate_as(self.reader)

        response = self.client.post(self.url, {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("question", response.data)
        service_class.assert_not_called()

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_blank_question_is_rejected(self, service_class):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("question", response.data)
        service_class.assert_not_called()

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_oversized_question_is_rejected(self, service_class):
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "x" * 8001},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("question", response.data)
        service_class.assert_not_called()

    def test_unauthenticated_user_cannot_use_assistant(self):
        response = self.client.post(
            self.url,
            {"question": "Show expenditure."},
            format="json",
        )
        self.assertIn(response.status_code, (401, 403))

    def test_user_without_membership_receives_not_found(self):
        self.authenticate_as(self.outsider)

        response = self.client.post(
            self.url,
            {"question": "Show expenditure."},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_inactive_membership_receives_not_found(self):
        self.membership.is_active = False
        self.membership.save(update_fields=["is_active"])
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "Show expenditure."},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_missing_groq_configuration_returns_safe_503(self, service_class):
        service_class.side_effect = FinancialAssistantConfigurationError(
            "Sensitive configuration detail"
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "Show expenditure."},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Sensitive configuration detail", str(response.data))
        self.assertIn("not configured", response.data["detail"])

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_provider_failure_returns_safe_503(self, service_class):
        service_class.return_value.answer.side_effect = FinancialAssistantProviderError(
            "Sensitive upstream response"
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "Show expenditure."},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Sensitive upstream response", str(response.data))
        self.assertIn("temporarily unavailable", response.data["detail"])

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_tool_budget_error_returns_actionable_400(self, service_class):
        service_class.return_value.answer.side_effect = FinancialAssistantToolLimitError(
            "Narrow the reporting period and try again."
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "Compare every vendor across all years."},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Narrow the reporting period", response.data["detail"])

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_unexpected_service_failure_returns_safe_503(self, service_class):
        service_class.return_value.answer.side_effect = RuntimeError(
            "Database connection string must not be exposed"
        )
        self.authenticate_as(self.reader)

        response = self.client.post(
            self.url,
            {"question": "Show expenditure."},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("Database connection string", str(response.data))
        self.assertIn("temporarily unavailable", response.data["detail"])
