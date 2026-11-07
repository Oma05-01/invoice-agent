from django.urls import path

from invoices.views import (
    InvoiceProcessingAPIView,
    InvoiceProcessingStatusAPIView,
    InvoiceReviewDetailAPIView,
    InvoiceVendorResolutionAPIView,
    InvoiceLineItemCollectionAPIView,
    InvoiceLineItemDetailAPIView,
    InvoiceValidationIssueIgnoreAPIView, 
    InvoiceReviewSubmissionAPIView
)


urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/process/",
        InvoiceProcessingAPIView.as_view(),
        name="invoice-process",
    ),

    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/",
        InvoiceProcessingStatusAPIView.as_view(),
        name="invoice-processing-status",
    ),
    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/review/",
        InvoiceReviewDetailAPIView.as_view(),
        name="invoice-review-detail",
    ),
    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/vendor/",
        InvoiceVendorResolutionAPIView.as_view(),
        name="invoice-vendor-resolution",
    ),
    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/line-items/",
        InvoiceLineItemCollectionAPIView.as_view(),
        name="invoice-line-item-list",
    ),

    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/line-items/<uuid:line_item_id>/",
        InvoiceLineItemDetailAPIView.as_view(),
        name="invoice-line-item-detail",
    ),

    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/validation-issues/<uuid:issue_id>/ignore/",
        InvoiceValidationIssueIgnoreAPIView.as_view(),
        name="invoice-validation-issue-ignore",
    ),
    path(
        "organizations/<uuid:organization_id>/invoices/<uuid:invoice_id>/submit-review/",
        InvoiceReviewSubmissionAPIView.as_view(),
        name="invoice-review-submit",
    ),
]

