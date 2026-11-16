from django.urls import path

from insights.views import SpendReportAPIView
from insights.assistant_api import FinancialAssistantChatAPIView

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
]
