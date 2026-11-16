"""Authenticated API endpoint for the FIN-01 financial assistant.

This module deliberately keeps the API boundary separate from the spend
reporting views and the Groq orchestration implementation.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from insights.ai.context import ToolContext
from insights.ai.groq_client import (
    MAX_QUESTION_LENGTH,
    FinancialAssistantConfigurationError,
    FinancialAssistantInputError,
    FinancialAssistantProviderError,
    FinancialAssistantService,
    FinancialAssistantToolExecutionError,
    FinancialAssistantToolLimitError,
)
from insights.views import OrganizationInsightsAPIView

logger = logging.getLogger(__name__)


class FinancialAssistantUserThrottle(UserRateThrottle):
    """Apply a conservative per-user limit to calls that incur LLM cost."""

    scope = "financial_assistant"
    rate = "30/hour"


class FinancialAssistantChatSerializer(serializers.Serializer):
    """Validate the single question accepted by the stateless chat endpoint."""

    question = serializers.CharField(
        trim_whitespace=True,
        allow_blank=False,
        max_length=MAX_QUESTION_LENGTH,
    )

    def to_internal_value(self, data):
        # Reject extra fields instead of silently accepting client-supplied
        # organisation, user, role, or tool context.
        if isinstance(data, Mapping):
            unexpected = set(data.keys()) - {"question"}
            if unexpected:
                raise serializers.ValidationError({
                    "non_field_errors": [
                        "Only the question field is accepted."
                    ]
                })
        return super().to_internal_value(data)


class FinancialAssistantChatAPIView(OrganizationInsightsAPIView):
    """Answer one question using the authenticated organisation's tools."""

    throttle_classes = [FinancialAssistantUserThrottle]

    def post(self, request, organization_id):
        membership = self.get_membership(request, organization_id)

        serializer = FinancialAssistantChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Organisation and role are injected from the verified membership.
        # Neither value is accepted from the request body or model arguments.
        context = ToolContext(
            user=request.user,
            membership=membership,
        )

        try:
            assistant = FinancialAssistantService()
            result = assistant.answer(
                serializer.validated_data["question"],
                context=context,
            )
        except FinancialAssistantInputError as exc:
            raise serializers.ValidationError({"question": str(exc)}) from exc
        except FinancialAssistantToolLimitError as exc:
            raise serializers.ValidationError({"detail": str(exc)}) from exc
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
        except Exception as exc:  # Fail closed at the external API boundary.
            logger.exception(
                "Unexpected financial assistant API failure (%s).",
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
                "report_artifacts": list(
                    getattr(result, "report_artifacts", ()) or ()
                ),
            },
            status=status.HTTP_200_OK,
        )
