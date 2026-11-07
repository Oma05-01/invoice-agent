from django.urls import path

from documents.views import InvoiceDocumentUploadAPIView, InvoiceDocumentPreviewAPIView


urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/documents/",
        InvoiceDocumentUploadAPIView.as_view(),
        name="invoice-document-upload",
    ),
    path(
        "organizations/<uuid:organization_id>/documents/<uuid:document_id>/preview/",
        InvoiceDocumentPreviewAPIView.as_view(),
        name="invoice-document-preview",
    ),
]