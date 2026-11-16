from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from insights.ai.groq_client import (
    FinancialAssistantProviderError,
    FinancialAssistantResponse,
    ToolInvocation,
)
from insights.models import AssistantConversation, AssistantMessage
from organizations.models import Organization, OrganizationMembership


class PersistentFinancialAssistantAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="persistent_assistant_owner",
            password="test-password-123",
        )
        self.other_member = User.objects.create_user(
            username="persistent_assistant_other",
            password="test-password-123",
        )
        self.outsider = User.objects.create_user(
            username="persistent_assistant_outsider",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Persistent Assistant Company",
            slug="persistent-assistant-company",
            default_currency="NGN",
        )
        self.other_organization = Organization.objects.create(
            name="Other Persistent Assistant Company",
            slug="other-persistent-assistant-company",
            default_currency="NGN",
        )
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=OrganizationMembership.Role.READ_ONLY,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.other_member,
            role=OrganizationMembership.Role.READ_ONLY,
        )
        OrganizationMembership.objects.create(
            organization=self.other_organization,
            user=self.owner,
            role=OrganizationMembership.Role.FINANCE_ADMIN,
        )
        self.client = APIClient()
        self.chat_url = reverse(
            "insights-assistant-chat",
            kwargs={"organization_id": self.organization.id},
        )
        self.list_url = reverse(
            "insights-assistant-conversations",
            kwargs={"organization_id": self.organization.id},
        )
        self.other_org_chat_url = reverse(
            "insights-assistant-chat",
            kwargs={"organization_id": self.other_organization.id},
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def make_result(self, answer="Grounded financial answer."):
        return FinancialAssistantResponse(
            answer=answer,
            model="openai/gpt-oss-20b",
            tool_invocations=(ToolInvocation("call_1", "spend_by", True),),
        )

    def create_conversation(self, *, creator=None, organization=None):
        conversation = AssistantConversation.objects.create(
            organization=organization or self.organization,
            created_by=creator or self.owner,
            title="Prior expenditure question",
        )
        AssistantMessage.objects.create(
            conversation=conversation,
            sequence=1,
            role=AssistantMessage.Role.USER,
            content="Show expenditure by vendor in October.",
        )
        AssistantMessage.objects.create(
            conversation=conversation,
            sequence=2,
            role=AssistantMessage.Role.ASSISTANT,
            content="The reported total was NGN 1,250.00.",
            model="openai/gpt-oss-20b",
        )
        return conversation

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_first_question_creates_conversation_and_persists_complete_exchange(
        self, service_class
    ):
        service_class.return_value.answer.return_value = self.make_result()
        self.authenticate_as(self.owner)

        response = self.client.post(
            self.chat_url,
            {"question": "Show expenditure by vendor this month."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("conversation_id", response.data)
        conversation = AssistantConversation.objects.get(
            pk=response.data["conversation_id"]
        )
        self.assertEqual(conversation.organization, self.organization)
        self.assertEqual(conversation.created_by, self.owner)
        self.assertEqual(
            conversation.title,
            "Show expenditure by vendor this month.",
        )
        messages = list(conversation.messages.order_by("sequence"))
        self.assertEqual([item.sequence for item in messages], [1, 2])
        self.assertEqual(messages[0].role, AssistantMessage.Role.USER)
        self.assertEqual(messages[1].role, AssistantMessage.Role.ASSISTANT)
        self.assertEqual(messages[1].tool_call_count, 1)
        self.assertEqual(
            messages[1].tool_invocations,
            [{"name": "spend_by", "succeeded": True}],
        )
        self.assertEqual(service_class.return_value.answer.call_args.kwargs["history"], [])

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_follow_up_loads_ordered_history_and_appends_next_exchange(
        self, service_class
    ):
        conversation = self.create_conversation()
        service_class.return_value.answer.return_value = self.make_result(
            "October expenditure was NGN 1,250.00."
        )
        self.authenticate_as(self.owner)

        response = self.client.post(
            self.chat_url,
            {
                "question": "Compare that with September.",
                "conversation_id": str(conversation.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["conversation_id"], str(conversation.id))
        service_class.return_value.answer.assert_called_once()
        self.assertEqual(
            service_class.return_value.answer.call_args.kwargs["history"],
            [
                {"role": "user", "content": "Show expenditure by vendor in October."},
                {"role": "assistant", "content": "The reported total was NGN 1,250.00."},
            ],
        )
        messages = list(conversation.messages.order_by("sequence"))
        self.assertEqual([item.sequence for item in messages], [1, 2, 3, 4])
        self.assertEqual(messages[2].content, "Compare that with September.")
        self.assertEqual(messages[3].content, "October expenditure was NGN 1,250.00.")

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_failed_first_request_does_not_create_conversation_or_messages(
        self, service_class
    ):
        service_class.return_value.answer.side_effect = FinancialAssistantProviderError(
            "Provider unavailable."
        )
        self.authenticate_as(self.owner)

        response = self.client.post(
            self.chat_url,
            {"question": "Show expenditure."},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(AssistantConversation.objects.count(), 0)
        self.assertEqual(AssistantMessage.objects.count(), 0)

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_failed_follow_up_does_not_append_partial_exchange(self, service_class):
        conversation = self.create_conversation()
        service_class.return_value.answer.side_effect = FinancialAssistantProviderError(
            "Provider unavailable."
        )
        self.authenticate_as(self.owner)

        response = self.client.post(
            self.chat_url,
            {
                "question": "And September?",
                "conversation_id": str(conversation.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(conversation.messages.count(), 2)

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_other_member_cannot_continue_conversation(self, service_class):
        conversation = self.create_conversation()
        self.authenticate_as(self.other_member)

        response = self.client.post(
            self.chat_url,
            {
                "question": "Continue this conversation.",
                "conversation_id": str(conversation.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        service_class.assert_not_called()

    @patch("insights.assistant_api.FinancialAssistantService")
    def test_conversation_from_another_organisation_cannot_be_continued(
        self, service_class
    ):
        conversation = self.create_conversation()
        self.authenticate_as(self.owner)

        response = self.client.post(
            self.other_org_chat_url,
            {
                "question": "Continue this conversation.",
                "conversation_id": str(conversation.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        service_class.assert_not_called()

    def test_malformed_conversation_id_is_rejected(self):
        self.authenticate_as(self.owner)
        response = self.client.post(
            self.chat_url,
            {"question": "Hello", "conversation_id": "not-a-uuid"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("conversation_id", response.data)

    def test_client_cannot_supply_user_or_organisation_context(self):
        self.authenticate_as(self.owner)
        response = self.client.post(
            self.chat_url,
            {
                "question": "Hello",
                "organization_id": str(self.other_organization.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_conversation_list_contains_only_current_users_conversations(self):
        own = self.create_conversation()
        self.create_conversation(creator=self.other_member)
        self.authenticate_as(self.owner)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(own.id))
        self.assertEqual(response.data["results"][0]["message_count"], 2)

    def test_conversation_list_requires_active_organisation_membership(self):
        self.authenticate_as(self.outsider)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 404)

    def test_conversation_detail_returns_ordered_messages_and_minimal_metadata(self):
        conversation = self.create_conversation()
        self.authenticate_as(self.owner)
        detail_url = reverse(
            "insights-assistant-conversation-detail",
            kwargs={
                "organization_id": self.organization.id,
                "conversation_id": conversation.id,
            },
        )

        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["conversation"]["id"], str(conversation.id))
        self.assertEqual(
            [message["sequence"] for message in response.data["messages"]],
            [1, 2],
        )
        self.assertEqual(
            response.data["messages"][1]["tool_invocations"],
            [],
        )
        self.assertNotIn("tool_arguments", response.data["messages"][1])
        self.assertNotIn("tool_results", response.data["messages"][1])

    def test_other_member_cannot_read_conversation_detail(self):
        conversation = self.create_conversation()
        self.authenticate_as(self.other_member)
        detail_url = reverse(
            "insights-assistant-conversation-detail",
            kwargs={
                "organization_id": self.organization.id,
                "conversation_id": conversation.id,
            },
        )

        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 404)

    def test_conversation_detail_is_organisation_scoped(self):
        conversation = self.create_conversation()
        self.authenticate_as(self.owner)
        detail_url = reverse(
            "insights-assistant-conversation-detail",
            kwargs={
                "organization_id": self.other_organization.id,
                "conversation_id": conversation.id,
            },
        )

        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_user_cannot_list_conversations(self):
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (401, 403))
