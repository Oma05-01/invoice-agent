from django.urls import path

from approvals.views import (
    ApprovalQueueAPIView,
    ApprovalDetailAPIView,
    ApproveInvoiceAPIView,
    RejectInvoiceAPIView,
    ReturnRejectedInvoiceAPIView,
)


urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/approvals/",
        ApprovalQueueAPIView.as_view(),
        name="approval-queue",
    ),

    path(
        "organizations/<uuid:organization_id>/approvals/<uuid:approval_request_id>/",
        ApprovalDetailAPIView.as_view(),
        name="approval-detail",
    ),

    path(
        "organizations/<uuid:organization_id>/approvals/<uuid:approval_request_id>/approve/",
        ApproveInvoiceAPIView.as_view(),
        name="approval-approve",
    ),

    path(
        "organizations/<uuid:organization_id>/approvals/<uuid:approval_request_id>/reject/",
        RejectInvoiceAPIView.as_view(),
        name="approval-reject",
    ),

    path(
        "organizations/<uuid:organization_id>/approvals/<uuid:approval_request_id>/return-to-review/",
        ReturnRejectedInvoiceAPIView.as_view(),
        name="approval-return-to-review",
    ),
]
