from django.urls import path

from documents.views import InvoiceDocumentUploadAPIView


urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/documents/",
        InvoiceDocumentUploadAPIView.as_view(),
        name="invoice-document-upload",
    ),
]