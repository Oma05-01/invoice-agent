from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.authentication import (
    BasicAuthentication,
    SessionAuthentication,
)
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.http import FileResponse

from organizations.models import OrganizationMembership
from documents.models import Document
from documents.services import (
    UploadValidationError,
    validate_invoice_file,
    calculate_sha256,
)
from invoices.models import Invoice


UPLOAD_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
    OrganizationMembership.Role.FINANCE_OPERATOR,
)


class InvoiceDocumentUploadAPIView(APIView):

    authentication_classes = [
        SessionAuthentication,
        BasicAuthentication,
    ]

    permission_classes = [IsAuthenticated]

    parser_classes = [
        MultiPartParser,
        FormParser,
    ]

    def post(self, request, organization_id):

        membership = (
            OrganizationMembership.objects
            .select_related("organization")
            .filter(
                organization_id=organization_id,
                user=request.user,
                is_active=True,
            )
            .first()
        )

        if membership is None:
            return Response(
                {"detail": "Organization not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if membership.role not in UPLOAD_ROLES:
            return Response(
                {"detail": "You are not permitted to upload invoices."},
                status=status.HTTP_403_FORBIDDEN,
            )

        uploaded_file = request.FILES.get("file")

        if uploaded_file is None:
            return Response(
                {"file": ["An invoice document is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            original_filename, detected_content_type = (
                validate_invoice_file(uploaded_file)
            )

            file_hash = calculate_sha256(uploaded_file)

        except UploadValidationError as exc:
            return Response(
                {"file": [str(exc)]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing_document = Document.objects.filter(
            organization=membership.organization,
            sha256=file_hash,
        ).first()

        if existing_document:
            return Response(
                {
                    "detail": "An identical document already exists.",
                    "existing_document_id": str(existing_document.id),
                },
                status=status.HTTP_409_CONFLICT,
            )

        document = None

        try:
            with transaction.atomic():

                document = Document(
                    organization=membership.organization,
                    uploaded_by=request.user,
                    original_filename=original_filename,
                    content_type=detected_content_type,
                    file_size=uploaded_file.size,
                    sha256=file_hash,
                    source=Document.Source.UPLOAD,
                    status=Document.Status.UPLOADED,
                )

                document.file = uploaded_file
                document.save()

                invoice = Invoice.objects.create(
                    organization=membership.organization,
                    source_document=document,
                    status=Invoice.Status.UPLOADED,
                )

        except IntegrityError:

            if document and document.file:
                document.file.storage.delete(document.file.name)

            existing_document = Document.objects.filter(
                organization=membership.organization,
                sha256=file_hash,
            ).first()

            if existing_document:
                return Response(
                    {
                        "detail": "An identical document already exists.",
                        "existing_document_id": str(
                            existing_document.id
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            raise

        except Exception:

            if document and document.file:
                document.file.storage.delete(document.file.name)

            raise

        return Response(
            {
                "message": "Invoice document uploaded successfully.",
                "document": {
                    "id": str(document.id),
                    "filename": document.original_filename,
                    "content_type": document.content_type,
                    "size": document.file_size,
                    "sha256": document.sha256,
                    "status": document.status,
                },
                "invoice": {
                    "id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "status": invoice.status,
                },
            },
            status=status.HTTP_201_CREATED,
        )



class InvoiceDocumentPreviewAPIView(APIView):
    """
    Stream an organization's PDF document to an authenticated member.

    Access is scoped by active organization membership and document
    ownership. The original storage URL is never exposed.
    """

    authentication_classes = [
        SessionAuthentication,
        BasicAuthentication,
    ]

    permission_classes = [IsAuthenticated]

    def get(self, request, organization_id, document_id):

        membership = OrganizationMembership.objects.filter(
            organization_id=organization_id,
            user=request.user,
            is_active=True,
        ).first()

        if membership is None:
            return Response(
                {"detail": "Organization not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        document = Document.objects.filter(
            pk=document_id,
            organization_id=organization_id,
        ).first()

        if document is None:
            return Response(
                {"detail": "Document not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only serve documents that are recorded as PDFs.
        if (
            document.content_type != "application/pdf"
            or not document.file
        ):
            return Response(
                {"detail": "PDF document is unavailable."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            file_handle = document.file.open("rb")

        except (FileNotFoundError, OSError):
            return Response(
                {"detail": "The stored PDF file could not be found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        response = FileResponse(
            file_handle,
            as_attachment=False,
            filename=document.original_filename,
            content_type="application/pdf",
        )

        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"

        # Permit embedding in the same-origin FIN-01 review page.
        response["X-Frame-Options"] = "SAMEORIGIN"

        return response
