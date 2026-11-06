from django.urls import path

from invoices.views import (
    InvoiceProcessingAPIView,
    InvoiceProcessingStatusAPIView,
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
]