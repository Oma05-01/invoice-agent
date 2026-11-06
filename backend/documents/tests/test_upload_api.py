import shutil
import tempfile

import pymupdf

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from rest_framework.test import APIClient

from organizations.models import (
    Organization,
    OrganizationMembership,
)
from documents.models import Document
from invoices.models import Invoice


User = get_user_model()


class InvoiceDocumentUploadTests(TestCase):

    def setUp(self):
        self.media_directory = tempfile.mkdtemp()

        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory,
        )
        self.settings_override.enable()

        self.user = User.objects.create_user(
            username="finance_admin",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Test Engineering Company",
            legal_name="Test Engineering Company Ltd",
            slug="test-engineering",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.url = reverse(
            "invoice-document-upload",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_directory, ignore_errors=True)
        super().tearDown()

    @staticmethod
    def generate_pdf():
        """Create a valid synthetic PDF in memory."""

        pdf = pymupdf.open()

        page = pdf.new_page()

        page.insert_text(
            (72, 72),
            "SUPPLIER INVOICE\n"
            "Invoice Number: TEST-001\n"
            "Supplier: ABC Engineering Ltd\n"
            "Subtotal: 100000.00\n"
            "VAT: 7500.00\n"
            "Total: 107500.00",
        )

        content = pdf.tobytes()
        pdf.close()

        return content

    def upload(self, content, filename="sample_invoice.pdf"):
        uploaded_file = SimpleUploadedFile(
            name=filename,
            content=content,
            content_type="application/pdf",
        )

        return self.client.post(
            self.url,
            {"file": uploaded_file},
            format="multipart",
        )

    def test_valid_pdf_upload_creates_document_and_invoice(self):

        response = self.upload(self.generate_pdf())

        self.assertEqual(response.status_code, 201)

        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(Invoice.objects.count(), 1)

        document = Document.objects.get()
        invoice = Invoice.objects.get()

        self.assertEqual(
            document.organization,
            self.organization,
        )

        self.assertEqual(
            invoice.source_document,
            document,
        )

        self.assertEqual(
            invoice.status,
            Invoice.Status.UPLOADED,
        )

        self.assertTrue(document.file.storage.exists(document.file.name))

        self.assertTrue(document.sha256)

    def test_duplicate_document_is_rejected(self):

        pdf_content = self.generate_pdf()

        first_response = self.upload(pdf_content)

        second_response = self.upload(pdf_content)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 409)

        self.assertEqual(Document.objects.count(), 1)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_unsupported_file_is_rejected(self):

        response = self.upload(
            b"some text content",
            filename="invoice.txt",
        )

        self.assertEqual(response.status_code, 400)

        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(Invoice.objects.count(), 0)

    def test_extension_mismatch_is_rejected(self):

        response = self.upload(
            self.generate_pdf(),
            filename="invoice.png",
        )

        self.assertEqual(response.status_code, 400)

        self.assertEqual(Document.objects.count(), 0)

    def test_empty_document_is_rejected(self):

        response = self.upload(
            b"",
            filename="empty.pdf",
        )

        self.assertEqual(response.status_code, 400)

        self.assertEqual(Document.objects.count(), 0)

    def test_user_without_membership_cannot_upload(self):

        other_user = User.objects.create_user(
            username="unauthorised_user",
            password="test-password-123",
        )

        self.client.force_authenticate(user=other_user)

        response = self.upload(self.generate_pdf())

        self.assertEqual(response.status_code, 404)

        self.assertEqual(Document.objects.count(), 0)

    def test_read_only_member_cannot_upload(self):

        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )

        self.membership.save()

        response = self.upload(self.generate_pdf())

        self.assertEqual(response.status_code, 403)

        self.assertEqual(Document.objects.count(), 0)

    def test_same_document_can_exist_in_different_organizations(self):

        second_organization = Organization.objects.create(
            name="Second Engineering Company",
            slug="second-engineering",
        )

        OrganizationMembership.objects.create(
            organization=second_organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        pdf_content = self.generate_pdf()

        first_response = self.upload(pdf_content)

        self.url = reverse(
            "invoice-document-upload",
            kwargs={
                "organization_id": second_organization.id,
            },
        )

        second_response = self.upload(pdf_content)

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 201)

        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(Invoice.objects.count(), 2)