from django.urls import path

from insights.views import SpendReportAPIView
from insights.conversation_api import (
    AssistantConversationDetailAPIView,
    AssistantConversationListAPIView,
    FinancialAssistantChatAPIView,
)

urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/insights/spend/",
        SpendReportAPIView.as_view(),
        name="insights-spend",
    ),
    path(
    "organizations/<uuid:organization_id>/insights/assistant/chat/",
    FinancialAssistantChatAPIView.as_view(),
    name="insights-assistant-chat",
),
    path(
        "organizations/<uuid:organization_id>/insights/assistant/conversations/",
        AssistantConversationListAPIView.as_view(),
        name="insights-assistant-conversations",
    ),
    path(
        "organizations/<uuid:organization_id>/insights/assistant/conversations/<uuid:conversation_id>/",
        AssistantConversationDetailAPIView.as_view(),
        name="insights-assistant-conversation-detail",
    ),
]
