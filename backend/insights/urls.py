from django.urls import path

from insights.views import SpendReportAPIView


urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/insights/spend/",
        SpendReportAPIView.as_view(),
        name="insights-spend",
    ),
]
