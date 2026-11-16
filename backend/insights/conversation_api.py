"""Persistent, organisation-scoped financial assistant conversation APIs."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

# Keep the service lookup through this module: existing API tests and any
# configured service substitutions patch insights.assistant_api.FinancialAssistantService.
from insights import assistant_api as assistant_api_module
from insights.ai.context import ToolContext
from insights.ai.groq_client import (
    MAX_CONVERSATION_HISTORY_MESSAGES,
    MAX_QUESTION_LENGTH,
    FinancialAssistantConfigurationError,
    FinancialAssistantInputError,
    FinancialAssistantProviderError,
    FinancialAssistantToolExecutionError,
    FinancialAssistantToolLimitError,
)
from insights.models import AssistantConversation, AssistantMessage
from insights.views import OrganizationInsightsAPIView

logger = logging.getLogger(__name__)
MAX_LISTED_CONVERSATIONS = 50


class PersistentFinancialAssistantChatSerializer(serializers.Serializer):
    """Validate a question and optional conversation identifier."""

    question = serializers.CharField(
        trim_whitespace=True,
        allow_blank=False,
        max_length=MAX_QUESTION_LENGTH,
    )
    conversation_id = serializers.UUIDField(required=False)

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            unexpected = set(data.keys()) - {"question", "conversation_id"}
            if unexpected:
                raise serializers.ValidationError({
                    "non_field_errors": [
                        "Only question and conversation_id fields are accepted."
                    ]
                })
        return super().to_internal_value(data)


class FinancialAssistantUserThrottle(UserRateThrottle):
    """Apply the existing conservative per-user limit to LLM requests."""

    scope = "financial_assistant"
    rate = "30/hour"


def _conversation_queryset(*, organization, user):
    return AssistantConversation.objects.filter(
        organization=organization,
        created_by=user,
    )


def _get_owned_conversation(*, organization, user, conversation_id):
    conversation = (
        _conversation_queryset(organization=organization, user=user)
        .filter(pk=conversation_id)
        .first()
    )
    if conversation is None:
        # Deliberately do not disclose whether an ID exists in another tenant
        # or belongs to another member of this organisation.
        raise NotFound("Conversation not found or access denied.")
    return conversation


def _message_data(message: AssistantMessage) -> dict:
    return {
        "id": str(message.id),
        "sequence": message.sequence,
        "role": message.role,
        "content": message.content,
        "model": message.model,
        "tool_call_count": message.tool_call_count,
        "tool_invocations": message.tool_invocations,
        "created_at": message.created_at.isoformat(),
    }


def _conversation_data(conversation: AssistantConversation) -> dict:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "last_message_at": (
            conversation.last_message_at.isoformat()
            if conversation.last_message_at
            else None
        ),
    }


def _make_title(question: str) -> str:
    title = " ".join(question.split())
    if len(title) <= 160:
        return title
    return f"{title[:157].rstrip()}..."


def _persist_exchange(
    *,
    conversation: AssistantConversation | None,
    organization,
    user,
    question: str,
    result,
) -> AssistantConversation:
    """Atomically persist a complete exchange, never a half-finished turn."""
    now = timezone.now()
    with transaction.atomic():
        if conversation is None:
            conversation = AssistantConversation.objects.create(
                organization=organization,
                created_by=user,
                title=_make_title(question),
            )
        else:
            # Re-lock and re-read the owned row before allocating sequence IDs.
            conversation = (
                AssistantConversation.objects.select_for_update()
                .get(
                    pk=conversation.pk,
                    organization=organization,
                    created_by=user,
                )
            )

        current_max = conversation.messages.aggregate(
            value=Max("sequence"),
        )["value"] or 0

        user_message = AssistantMessage(
            conversation=conversation,
            sequence=current_max + 1,
            role=AssistantMessage.Role.USER,
            content=question,
        )
        user_message.full_clean()
        user_message.save(force_insert=True)

        invocations = [
            {
                "name": invocation.name,
                "succeeded": invocation.succeeded,
            }
            for invocation in result.tool_invocations
        ]
        assistant_message = AssistantMessage(
            conversation=conversation,
            sequence=current_max + 2,
            role=AssistantMessage.Role.ASSISTANT,
            content=result.answer,
            model=result.model,
            tool_call_count=result.tool_call_count,
            tool_invocations=invocations,
        )
        assistant_message.full_clean()
        assistant_message.save(force_insert=True)

        conversation.last_message_at = now
        conversation.save(update_fields=["last_message_at", "updated_at"])

    return conversation


class FinancialAssistantChatAPIView(OrganizationInsightsAPIView):
    """Create or continue a private conversation using the member's tools."""

    throttle_classes = [FinancialAssistantUserThrottle]

    def post(self, request, organization_id):
        membership = self.get_membership(request, organization_id)
        serializer = PersistentFinancialAssistantChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data

        conversation = None
        history = []
        conversation_id = values.get("conversation_id")
        if conversation_id is not None:
            conversation = _get_owned_conversation(
                organization=membership.organization,
                user=request.user,
                conversation_id=conversation_id,
            )
            previous = list(
                conversation.messages.order_by("-sequence")
                .values("role", "content")[:MAX_CONVERSATION_HISTORY_MESSAGES]
            )
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in reversed(previous)
            ]

        context = ToolContext(user=request.user, membership=membership)
        question = values["question"]

        try:
            # Resolve through assistant_api_module for compatibility with the
            # established patch point used by the original API test suite.
            assistant = assistant_api_module.FinancialAssistantService()
            result = assistant.answer(
                question,
                context=context,
                history=history,
            )
            conversation = _persist_exchange(
                conversation=conversation,
                organization=membership.organization,
                user=request.user,
                question=question,
                result=result,
            )
        except FinancialAssistantInputError as exc:
            raise serializers.ValidationError({"question": str(exc)}) from exc
        except FinancialAssistantToolLimitError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
        except NotFound:
            raise
        except AssistantConversation.DoesNotExist as exc:
            raise NotFound("Conversation not found or access denied.") from exc
        except FinancialAssistantConfigurationError as exc:
            logger.error(
                "Financial assistant configuration unavailable (%s).",
                type(exc).__name__,
            )
            return Response(
                {"detail": "The financial assistant is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except (
            FinancialAssistantProviderError,
            FinancialAssistantToolExecutionError,
        ) as exc:
            logger.warning(
                "Financial assistant request unavailable (%s).",
                type(exc).__name__,
            )
            return Response(
                {
                    "detail": (
                        "The financial assistant is temporarily unavailable. "
                        "Please try again."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            logger.exception(
                "Unexpected persistent financial assistant failure (%s).",
                type(exc).__name__,
            )
            return Response(
                {
                    "detail": (
                        "The financial assistant is temporarily unavailable. "
                        "Please try again."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "conversation_id": str(conversation.id),
                "answer": result.answer,
                "model": result.model,
                "tool_call_count": result.tool_call_count,
                "tool_invocations": [
                    {
                        "name": invocation.name,
                        "succeeded": invocation.succeeded,
                    }
                    for invocation in result.tool_invocations
                ],
            },
            status=status.HTTP_200_OK,
        )


class AssistantConversationListAPIView(OrganizationInsightsAPIView):
    """List only conversations created by the authenticated member."""

    def get(self, request, organization_id):
        membership = self.get_membership(request, organization_id)
        conversations = (
            _conversation_queryset(
                organization=membership.organization,
                user=request.user,
            )
            .annotate(message_count=Count("messages"))
            .order_by("-last_message_at", "-created_at")[:MAX_LISTED_CONVERSATIONS]
        )
        return Response(
            {
                "results": [
                    {
                        **_conversation_data(conversation),
                        "message_count": conversation.message_count,
                    }
                    for conversation in conversations
                ],
                "limit": MAX_LISTED_CONVERSATIONS,
            },
            status=status.HTTP_200_OK,
        )


class AssistantConversationDetailAPIView(OrganizationInsightsAPIView):
    """Retrieve a member-owned conversation and its ordered messages."""

    def get(self, request, organization_id, conversation_id: UUID):
        membership = self.get_membership(request, organization_id)
        conversation = _get_owned_conversation(
            organization=membership.organization,
            user=request.user,
            conversation_id=conversation_id,
        )
        messages = conversation.messages.order_by("sequence")
        return Response(
            {
                "conversation": _conversation_data(conversation),
                "messages": [_message_data(message) for message in messages],
            },
            status=status.HTTP_200_OK,
        )
