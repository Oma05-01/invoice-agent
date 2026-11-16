import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from insights.models import AssistantConversation, AssistantMessage
from organizations.models import Organization


class AssistantConversationModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="assistant_conversation_owner",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Assistant Conversation Company",
            slug="assistant-conversation-company",
            default_currency="NGN",
        )

    def create_conversation(self, **overrides):
        values = {
            "organization": self.organization,
            "created_by": self.user,
        }
        values.update(overrides)
        return AssistantConversation.objects.create(**values)

    def test_conversation_uses_uuid_and_default_title(self):
        conversation = self.create_conversation()

        self.assertIsInstance(conversation.pk, uuid.UUID)
        self.assertEqual(conversation.title, "New conversation")
        self.assertIsNotNone(conversation.created_at)
        self.assertIsNotNone(conversation.updated_at)
        self.assertIsNone(conversation.last_message_at)

    def test_conversation_records_organisation_and_creator(self):
        conversation = self.create_conversation(title="Vendor expenditure")

        self.assertEqual(conversation.organization, self.organization)
        self.assertEqual(conversation.created_by, self.user)
        self.assertEqual(str(conversation), "Vendor expenditure (Assistant Conversation Company)")

    def test_conversations_are_ordered_by_recent_activity(self):
        older = self.create_conversation(title="Older")
        newer = self.create_conversation(title="Newer")
        now = timezone.now()

        AssistantConversation.objects.filter(pk=older.pk).update(
            last_message_at=now - timedelta(hours=1),
        )
        AssistantConversation.objects.filter(pk=newer.pk).update(
            last_message_at=now,
        )

        self.assertEqual(
            list(AssistantConversation.objects.values_list("title", flat=True)),
            ["Newer", "Older"],
        )


class AssistantMessageModelTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="assistant_message_owner",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Assistant Message Company",
            slug="assistant-message-company",
            default_currency="NGN",
        )
        self.conversation = AssistantConversation.objects.create(
            organization=self.organization,
            created_by=self.user,
        )

    def create_message(self, **overrides):
        values = {
            "conversation": self.conversation,
            "sequence": 1,
            "role": AssistantMessage.Role.USER,
            "content": "Show expenditure by vendor.",
        }
        values.update(overrides)
        return AssistantMessage.objects.create(**values)

    def test_message_uses_uuid_and_defaults_to_empty_tool_metadata(self):
        message = self.create_message()

        self.assertIsInstance(message.pk, uuid.UUID)
        self.assertEqual(message.tool_call_count, 0)
        self.assertEqual(message.tool_invocations, [])
        self.assertEqual(message.model, "")
        self.assertIsNotNone(message.created_at)

    def test_messages_are_ordered_by_sequence(self):
        second = self.create_message(
            sequence=2,
            role=AssistantMessage.Role.ASSISTANT,
            content="Total expenditure is NGN 1,250.00.",
        )
        first = self.create_message(sequence=1)

        self.assertEqual(
            list(self.conversation.messages.values_list("pk", flat=True)),
            [first.pk, second.pk],
        )

    def test_duplicate_sequence_is_rejected(self):
        self.create_message(sequence=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_message(sequence=1)

    def test_sequence_must_be_positive(self):
        message = AssistantMessage(
            conversation=self.conversation,
            sequence=0,
            role=AssistantMessage.Role.USER,
            content="Question",
        )

        with self.assertRaises(ValidationError):
            message.full_clean()

    def test_user_message_cannot_store_model_or_tool_metadata(self):
        message = AssistantMessage(
            conversation=self.conversation,
            sequence=1,
            role=AssistantMessage.Role.USER,
            content="Question",
            model="openai/gpt-oss-20b",
            tool_call_count=1,
            tool_invocations=[{"name": "spend_by", "succeeded": True}],
        )

        with self.assertRaises(ValidationError) as context:
            message.full_clean()

        self.assertIn("model", context.exception.message_dict)
        self.assertIn("tool_invocations", context.exception.message_dict)

    def test_assistant_message_accepts_minimal_tool_metadata(self):
        message = AssistantMessage(
            conversation=self.conversation,
            sequence=1,
            role=AssistantMessage.Role.ASSISTANT,
            content="The report shows NGN 1,250.00 in expenditure.",
            model="openai/gpt-oss-20b",
            tool_call_count=1,
            tool_invocations=[{"name": "spend_by", "succeeded": True}],
        )

        message.full_clean()
        message.save()

        self.assertEqual(message.tool_call_count, 1)
        self.assertEqual(
            message.tool_invocations,
            [{"name": "spend_by", "succeeded": True}],
        )

    def test_tool_metadata_rejects_raw_arguments_or_results(self):
        message = AssistantMessage(
            conversation=self.conversation,
            sequence=1,
            role=AssistantMessage.Role.ASSISTANT,
            content="Report summary.",
            tool_call_count=1,
            tool_invocations=[{
                "name": "spend_by",
                "succeeded": True,
                "arguments": {"organization_id": str(self.organization.pk)},
            }],
        )

        with self.assertRaises(ValidationError) as context:
            message.full_clean()

        self.assertIn("tool_invocations", context.exception.message_dict)

    def test_assistant_tool_count_must_match_metadata(self):
        message = AssistantMessage(
            conversation=self.conversation,
            sequence=1,
            role=AssistantMessage.Role.ASSISTANT,
            content="Report summary.",
            tool_call_count=1,
            tool_invocations=[],
        )

        with self.assertRaises(ValidationError) as context:
            message.full_clean()

        self.assertIn("tool_call_count", context.exception.message_dict)

    def test_messages_are_deleted_with_conversation(self):
        self.create_message()
        conversation_id = self.conversation.pk

        self.conversation.delete()

        self.assertFalse(
            AssistantMessage.objects.filter(conversation_id=conversation_id).exists()
        )
