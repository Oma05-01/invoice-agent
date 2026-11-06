from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from django.test import SimpleTestCase
from rest_framework.test import APIClient
from pydantic import ValidationError

from invoices.schemas import InvoiceExtractionResult
from invoices.services.extraction import (
    InvoiceExtractionError,
    InvoiceExtractionService,
    InvalidExtractionResponse,
)
from invoices.services.validation import (
    validate_invoice_extraction,
)

from invoices.services.evidence import (
    verify_extraction_evidence,
)
import shutil
import tempfile

import pymupdf

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from organizations.models import Organization, OrganizationMembership
from vendors.models import Vendor
from documents.models import Document
from invoices.models import Invoice, InvoiceLineItem, InvoiceValidationIssue

from documents.extraction import OCRRequiredError
from invoices.models import Invoice


from invoices.services.processing import (
    process_invoice,
    InvoiceProcessingStateError,
)

class InvoiceExtractionSchemaTests(SimpleTestCase):

    def valid_payload(self):
        return {
            "supplier_legal_name": "ABC Engineering Ltd",
            "supplier_tin": "12345678-0001",
            "invoice_number": "DEMO-001",
            "invoice_date": "2026-11-06",
            "due_date": "2026-11-20",
            "currency": "ngn",
            "subtotal": "100000.00",
            "taxes": [
                {
                    "name": "Value Added Tax",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "rate_percent": "7.5",
                    "amount": "7500.00",
                }
            ],
            "total_amount": "107500.00",
            "amount_due": "107500.00",
            "line_items": [
                {
                    "description": "Engineering consultancy",
                    "quantity": "1",
                    "unit_price": "100000.00",
                    "line_total": "100000.00",
                    "suggested_expense_category": "Professional Services",
                }
            ],
            "field_confidence": {
                "invoice_number": 0.98,
                "total_amount": 0.96,
            },
            "field_evidence": {
                "invoice_number": [
                    {
                        "page": 1,
                        "quote": "Invoice Number: DEMO-001",
                    }
                ]
            },
            "extraction_warnings": [],
        }

    def test_valid_invoice_extraction(self):

        result = InvoiceExtractionResult.model_validate(
            self.valid_payload()
        )

        self.assertEqual(
            result.invoice_number,
            "DEMO-001",
        )

        self.assertEqual(
            result.currency,
            "NGN",
        )

        self.assertEqual(
            result.total_amount,
            Decimal("107500.00"),
        )

        self.assertEqual(
            result.taxes[0].tax_type,
            "VAT",
        )

    def test_missing_values_remain_none(self):

        result = InvoiceExtractionResult.model_validate(
            {
                "supplier_legal_name": "ABC Engineering Ltd",
            }
        )

        self.assertIsNone(result.invoice_number)
        self.assertIsNone(result.due_date)
        self.assertIsNone(result.subtotal)
        self.assertIsNone(result.total_amount)

    def test_currency_is_normalized(self):

        result = InvoiceExtractionResult.model_validate(
            {
                "currency": "ngn",
            }
        )

        self.assertEqual(result.currency, "NGN")

    def test_invalid_currency_is_rejected(self):

        with self.assertRaises(ValidationError):
            InvoiceExtractionResult.model_validate(
                {
                    "currency": "NAIRA",
                }
            )

    def test_confidence_above_one_is_rejected(self):

        with self.assertRaises(ValidationError):
            InvoiceExtractionResult.model_validate(
                {
                    "field_confidence": {
                        "total_amount": 1.5,
                    }
                }
            )

    def test_invalid_evidence_page_is_rejected(self):

        with self.assertRaises(ValidationError):
            InvoiceExtractionResult.model_validate(
                {
                    "field_evidence": {
                        "invoice_number": [
                            {
                                "page": 0,
                                "quote": "Invoice Number: DEMO-001",
                            }
                        ]
                    }
                }
            )

    def test_invalid_invoice_date_is_rejected(self):

        with self.assertRaises(ValidationError):
            InvoiceExtractionResult.model_validate(
                {
                    "invoice_date": "not-a-date",
                }
            )

    def test_unexpected_fields_are_rejected(self):

        with self.assertRaises(ValidationError):
            InvoiceExtractionResult.model_validate(
                {
                    "invoice_number": "DEMO-001",
                    "unauthorised_field": "unexpected",
                }
            )


class FakeInvoiceExtractionProvider:

    def extract_invoice(
        self,
        *,
        document_text,
        instructions,
        response_schema,
    ):

        assert document_text
        assert "untrusted data" in instructions
        assert "properties" in response_schema

        return {
            "supplier_legal_name": "ABC Engineering Ltd",
            "invoice_number": "DEMO-001",
            "currency": "NGN",
            "subtotal": "100000.00",
            "taxes": [],
            "total_amount": "100000.00",
            "amount_due": "100000.00",
            "line_items": [],
        }


class InvoiceExtractionServiceTests(SimpleTestCase):

    def setUp(self):
        self.provider = FakeInvoiceExtractionProvider()

        self.service = InvoiceExtractionService(
            provider=self.provider,
        )

    def test_empty_document_text_is_rejected(self):

        with self.assertRaises(InvoiceExtractionError):
            self.service.extract("")

    def test_provider_response_is_validated(self):

        result = self.service.extract(
            "[PAGE 1]\nInvoice Number: DEMO-001"
        )

        self.assertEqual(
            result.invoice_number,
            "DEMO-001",
        )

        self.assertEqual(
            result.currency,
            "NGN",
        )

    def test_invalid_provider_response_is_rejected(self):

        class InvalidProvider:

            def extract_invoice(self, **kwargs):
                return {
                    "invoice_number": "DEMO-001",
                    "currency": "INVALID",
                }

        service = InvoiceExtractionService(
            provider=InvalidProvider(),
        )

        with self.assertRaises(InvalidExtractionResponse):
            service.extract(
                "[PAGE 1]\nInvoice Number: DEMO-001"
            )


class InvoiceFinancialValidationTests(SimpleTestCase):

    def make_extraction(self, **overrides):

        payload = {
            "supplier_legal_name": "ABC Engineering Ltd",
            "invoice_number": "DEMO-001",
            "invoice_date": "2026-11-06",
            "currency": "NGN",
            "subtotal": "100000.00",
            "other_charges": "0.00",
            "taxes": [
                {
                    "name": "VAT",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "rate_percent": "7.5",
                    "amount": "7500.00",
                }
            ],
            "total_amount": "107500.00",
            "amount_due": "107500.00",
            "line_items": [
                {
                    "description": "Engineering services",
                    "quantity": "1",
                    "unit_price": "100000.00",
                    "line_total": "100000.00",
                }
            ],
        }

        payload.update(overrides)

        return InvoiceExtractionResult.model_validate(payload)

    def test_valid_invoice_has_no_findings(self):

        extraction = self.make_extraction()

        findings = validate_invoice_extraction(extraction)

        self.assertEqual(findings, [])

    def test_missing_required_fields_are_reported(self):

        extraction = self.make_extraction(
            supplier_legal_name=None,
            invoice_number=None,
        )

        findings = validate_invoice_extraction(extraction)

        codes = {item.code for item in findings}

        self.assertIn("MISSING_REQUIRED_FIELD", codes)

        missing_fields = {
            item.field_name for item in findings
        }

        self.assertIn("supplier_legal_name", missing_fields)
        self.assertIn("invoice_number", missing_fields)

    def test_line_item_mismatch_is_detected(self):

        extraction = self.make_extraction(
            line_items=[
                {
                    "description": "Engineering services",
                    "quantity": "2",
                    "unit_price": "10000.00",
                    "line_total": "15000.00",
                }
            ],
            subtotal="15000.00",
            total_amount="16125.00",
            amount_due="16125.00",
            taxes=[
                {
                    "name": "VAT",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "amount": "1125.00",
                }
            ],
        )

        findings = validate_invoice_extraction(extraction)

        self.assertIn(
            "LINE_TOTAL_MISMATCH",
            {item.code for item in findings},
        )

    def test_subtotal_mismatch_is_detected(self):

        extraction = self.make_extraction(
            subtotal="90000.00",
            line_items=[
                {
                    "description": "Engineering services",
                    "quantity": "1",
                    "unit_price": "100000.00",
                    "line_total": "100000.00",
                }
            ],
            total_amount="97500.00",
            taxes=[
                {
                    "name": "VAT",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "amount": "7500.00",
                }
            ],
        )

        findings = validate_invoice_extraction(extraction)

        self.assertIn(
            "SUBTOTAL_MISMATCH",
            {item.code for item in findings},
        )

    def test_invoice_total_mismatch_is_detected(self):

        extraction = self.make_extraction(
            total_amount="105000.00",
        )

        findings = validate_invoice_extraction(extraction)

        self.assertIn(
            "TOTAL_MISMATCH",
            {item.code for item in findings},
        )

    def test_withholding_is_deducted_from_amount_due(self):

        extraction = self.make_extraction(
            taxes=[
                {
                    "name": "VAT",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "amount": "7500.00",
                },
                {
                    "name": "Withholding Tax",
                    "tax_type": "WHT",
                    "treatment": "withheld",
                    "amount": "5000.00",
                },
            ],
            total_amount="107500.00",
            amount_due="102500.00",
        )

        findings = validate_invoice_extraction(extraction)

        self.assertEqual(findings, [])

    def test_incorrect_amount_due_after_withholding_is_detected(self):

        extraction = self.make_extraction(
            taxes=[
                {
                    "name": "VAT",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "amount": "7500.00",
                },
                {
                    "name": "Withholding Tax",
                    "tax_type": "WHT",
                    "treatment": "withheld",
                    "amount": "5000.00",
                },
            ],
            total_amount="107500.00",
            amount_due="107500.00",
        )

        findings = validate_invoice_extraction(extraction)

        self.assertIn(
            "AMOUNT_DUE_MISMATCH",
            {item.code for item in findings},
        )

    def test_due_date_before_invoice_date_is_flagged(self):

        extraction = self.make_extraction(
            due_date="2026-11-01",
        )

        findings = validate_invoice_extraction(extraction)

        self.assertIn(
            "DUE_DATE_BEFORE_INVOICE_DATE",
            {item.code for item in findings},
        )

    def test_uncertain_tax_treatment_skips_total_validation(self):

        extraction = self.make_extraction(
            taxes=[
                {
                    "name": "Tax",
                    "tax_type": "OTHER",
                    "treatment": "unknown",
                    "amount": "7500.00",
                }
            ],
            total_amount="90000.00",
        )

        findings = validate_invoice_extraction(extraction)

        self.assertNotIn(
            "TOTAL_MISMATCH",
            {item.code for item in findings},
        )

    def test_missing_tax_information_skips_total_validation(self):

        extraction = self.make_extraction(
            taxes=None,
            total_amount="90000.00",
            amount_due="80000.00",
        )

        findings = validate_invoice_extraction(extraction)

        codes = {item.code for item in findings}

        self.assertNotIn("TOTAL_MISMATCH", codes)
        self.assertNotIn("AMOUNT_DUE_MISMATCH", codes)  


    def test_line_items_are_validated_without_subtotal(self):

        extraction = self.make_extraction(
            subtotal=None,
            line_items=[
                {
                    "description": "Engineering services",
                    "quantity": "2",
                    "unit_price": "10000.00",
                    "line_total": "15000.00",
                }
            ],
        )

        findings = validate_invoice_extraction(extraction)

        self.assertIn(
            "LINE_TOTAL_MISMATCH",
            {item.code for item in findings},
        )

class InvoiceEvidenceVerificationTests(SimpleTestCase):

    def setUp(self):

        self.extraction = InvoiceExtractionResult.model_validate(
            {
                "invoice_number": "DEMO-001",
                "supplier_legal_name": "ABC Engineering Ltd",
                "field_evidence": {
                    "invoice_number": [
                        {
                            "page": 1,
                            "quote": "Invoice Number: DEMO-001",
                        }
                    ],
                    "supplier_legal_name": [
                        {
                            "page": 1,
                            "quote": "Supplier: ABC Engineering Ltd",
                        }
                    ],
                },
            }
        )

    def test_valid_evidence_is_accepted(self):

        page_texts = {
            1: (
                "SUPPLIER INVOICE\n"
                "Invoice Number: DEMO-001\n"
                "Supplier: ABC Engineering Ltd"
            )
        }

        findings = verify_extraction_evidence(
            self.extraction,
            page_texts,
        )

        self.assertEqual(findings, [])

    def test_missing_page_is_flagged(self):

        findings = verify_extraction_evidence(
            self.extraction,
            {},
        )

        self.assertEqual(len(findings), 2)

        self.assertTrue(
            all(
                finding.code == "EVIDENCE_PAGE_NOT_FOUND"
                for finding in findings
            )
        )

    def test_missing_quote_is_flagged(self):

        page_texts = {
            1: "Invoice Number: DIFFERENT-001"
        }

        findings = verify_extraction_evidence(
            self.extraction,
            page_texts,
        )

        codes = {
            finding.code
            for finding in findings
        }

        self.assertIn(
            "EVIDENCE_QUOTE_NOT_FOUND",
            codes,
        )

    def test_page_without_searchable_text_requires_ocr(self):

        findings = verify_extraction_evidence(
            self.extraction,
            {
                1: "",
            },
        )

        codes = {
            finding.code
            for finding in findings
        }

        self.assertIn(
            "EVIDENCE_PAGE_REQUIRES_OCR",
            codes,
        )

    def test_whitespace_and_case_differences_are_accepted(self):

        page_texts = {
            1: (
                "INVOICE NUMBER:\n"
                "   DEMO-001"
            )
        }

        extraction = InvoiceExtractionResult.model_validate(
            {
                "field_evidence": {
                    "invoice_number": [
                        {
                            "page": 1,
                            "quote": "Invoice Number: DEMO-001",
                        }
                    ]
                }
            }
        )

        findings = verify_extraction_evidence(
            extraction,
            page_texts,
        )

        self.assertEqual(findings, [])


class InvoiceProcessingTests(TestCase):

    def setUp(self):

        self.media_directory = tempfile.mkdtemp()

        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory,
        )
        self.settings_override.enable()

        User = get_user_model()

        self.user = User.objects.create_user(
            username="processing_admin",
            password="temporary-test-password",
        )

        self.organization = Organization.objects.create(
            name="Processing Test Company",
            slug="processing-test-company",
        )

        self.vendor = Vendor.objects.create(
            organization=self.organization,
            legal_name="ABC Engineering Ltd",
            display_name="ABC Engineering",
        )

        self.document = self.create_document(
            self.generate_pdf(),
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            source_document=self.document,
        )

    def tearDown(self):

        self.settings_override.disable()

        shutil.rmtree(
            self.media_directory,
            ignore_errors=True,
        )

        super().tearDown()

    @staticmethod
    def generate_pdf(scanned=False):

        pdf = pymupdf.open()

        page = pdf.new_page()

        if not scanned:
            page.insert_text(
                (72, 72),
                "SUPPLIER INVOICE\n"
                "Invoice Number: DEMO-002\n"
                "Supplier: ABC Engineering Ltd\n"
                "Date: 06 November 2026\n"
                "Subtotal: NGN 100000.00\n"
                "VAT: NGN 7500.00\n"
                "Total: NGN 107500.00\n"
                "Description: Engineering services\n"
                "Quantity: 1\n"
                "Unit Price: NGN 100000.00\n"
                "Line Total: NGN 100000.00",
            )

        content = pdf.tobytes()

        pdf.close()

        return content

    def create_document(self, content):

        document = Document(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="demo_invoice.pdf",
            content_type="application/pdf",
            file_size=len(content),
        )

        document.file.save(
            "demo_invoice.pdf",
            ContentFile(content),
            save=False,
        )

        document.save()

        return document

    def valid_extraction_payload(self):

        return {
            "supplier_legal_name": "ABC Engineering Ltd",
            "invoice_number": "DEMO-002",
            "invoice_date": "2026-11-06",
            "currency": "NGN",
            "subtotal": "100000.00",
            "taxes": [
                {
                    "name": "VAT",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "rate_percent": "7.5",
                    "amount": "7500.00",
                }
            ],
            "other_charges": "0.00",
            "total_amount": "107500.00",
            "line_items": [
                {
                    "description": "Engineering services",
                    "quantity": "1",
                    "unit_price": "100000.00",
                    "line_total": "100000.00",
                    "suggested_expense_category": "Professional Services",
                }
            ],
            "field_evidence": {
                "invoice_number": [
                    {
                        "page": 1,
                        "quote": "Invoice Number: DEMO-002",
                    }
                ],
                "supplier_legal_name": [
                    {
                        "page": 1,
                        "quote": "Supplier: ABC Engineering Ltd",
                    }
                ],
                "invoice_date": [
                    {
                        "page": 1,
                        "quote": "Date: 06 November 2026",
                    }
                ],
                "currency": [
                    {
                        "page": 1,
                        "quote": "Subtotal: NGN 100000.00",
                    }
                ],
                "subtotal": [
                    {
                        "page": 1,
                        "quote": "Subtotal: NGN 100000.00",
                    }
                ],
                "taxes": [
                    {
                        "page": 1,
                        "quote": "VAT: NGN 7500.00",
                    }
                ],
                "total_amount": [
                    {
                        "page": 1,
                        "quote": "Total: NGN 107500.00",
                    }
                ],
                "line_items": [
                    {
                        "page": 1,
                        "quote": (
                            "Description: Engineering services"
                        ),
                    }
                ],
            },
        }

class FakeExtractionService:

    def __init__(self, payload):
        self.payload = payload

    def extract(self, *, document_text):

        assert "DEMO-002" in document_text

        return InvoiceExtractionResult.model_validate(
            self.payload
        )


class InvoiceProcessingTests(TestCase):

    def setUp(self):

        self.media_directory = tempfile.mkdtemp()

        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory,
        )
        self.settings_override.enable()

        User = get_user_model()

        self.user = User.objects.create_user(
            username="processing_admin",
            password="temporary-test-password",
        )

        self.organization = Organization.objects.create(
            name="Processing Test Company",
            slug="processing-test-company",
        )

        self.vendor = Vendor.objects.create(
            organization=self.organization,
            legal_name="ABC Engineering Ltd",
            display_name="ABC Engineering",
        )

        self.document = self.create_document(
            self.generate_pdf()
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            source_document=self.document,
        )

    def tearDown(self):

        self.settings_override.disable()

        shutil.rmtree(
            self.media_directory,
            ignore_errors=True,
        )

        super().tearDown()

    @staticmethod
    def generate_pdf(scanned=False):

        pdf = pymupdf.open()
        page = pdf.new_page()

        if not scanned:
            page.insert_text(
                (72, 72),
                "SUPPLIER INVOICE\n"
                "Invoice Number: DEMO-002\n"
                "Supplier: ABC Engineering Ltd\n"
                "Date: 06 November 2026\n"
                "Subtotal: NGN 100000.00\n"
                "VAT: NGN 7500.00\n"
                "Total: NGN 107500.00\n"
                "Description: Engineering services\n"
                "Quantity: 1\n"
                "Unit Price: NGN 100000.00\n"
                "Line Total: NGN 100000.00",
            )

        content = pdf.tobytes()
        pdf.close()

        return content

    def create_document(self, content):

        document = Document(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="demo_invoice.pdf",
            content_type="application/pdf",
            file_size=len(content),
        )

        document.file.save(
            "demo_invoice.pdf",
            ContentFile(content),
            save=False,
        )

        document.save()

        return document

    def valid_extraction_payload(self):

        return {
            "supplier_legal_name": "ABC Engineering Ltd",
            "invoice_number": "DEMO-002",
            "invoice_date": "2026-11-06",
            "currency": "NGN",
            "subtotal": "100000.00",
            "taxes": [
                {
                    "name": "VAT",
                    "tax_type": "VAT",
                    "treatment": "added",
                    "rate_percent": "7.5",
                    "amount": "7500.00",
                }
            ],
            "other_charges": "0.00",
            "total_amount": "107500.00",
            "line_items": [
                {
                    "description": "Engineering services",
                    "quantity": "1",
                    "unit_price": "100000.00",
                    "line_total": "100000.00",
                    "suggested_expense_category": (
                        "Professional Services"
                    ),
                }
            ],
            "field_evidence": {
                "invoice_number": [
                    {
                        "page": 1,
                        "quote": "Invoice Number: DEMO-002",
                    }
                ],
                "supplier_legal_name": [
                    {
                        "page": 1,
                        "quote": "Supplier: ABC Engineering Ltd",
                    }
                ],
                "invoice_date": [
                    {
                        "page": 1,
                        "quote": "Date: 06 November 2026",
                    }
                ],
                "currency": [
                    {
                        "page": 1,
                        "quote": "Subtotal: NGN 100000.00",
                    }
                ],
                "subtotal": [
                    {
                        "page": 1,
                        "quote": "Subtotal: NGN 100000.00",
                    }
                ],
                "taxes": [
                    {
                        "page": 1,
                        "quote": "VAT: NGN 7500.00",
                    }
                ],
                "total_amount": [
                    {
                        "page": 1,
                        "quote": "Total: NGN 107500.00",
                    }
                ],
                "line_items": [
                    {
                        "page": 1,
                        "quote": "Description: Engineering services",
                    }
                ],
            },
        }

    def test_complete_invoice_processing(self):

        service = FakeExtractionService(
            self.valid_extraction_payload()
        )

        invoice = process_invoice(
            self.invoice.id,
            extraction_service=service,
        )

        invoice.refresh_from_db()
        self.document.refresh_from_db()

        self.assertEqual(
            invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )

        self.assertEqual(
            self.document.status,
            Document.Status.PROCESSED,
        )

        self.assertEqual(invoice.vendor, self.vendor)

        self.assertEqual(invoice.currency, "NGN")

        self.assertEqual(
            invoice.total_amount,
            Decimal("107500.00"),
        )

        self.assertIsNone(invoice.amount_due)

        self.assertEqual(
            invoice.extracted_data["invoice_number"],
            "DEMO-002",
        )

        self.assertEqual(
            InvoiceLineItem.objects.filter(
                invoice=invoice
            ).count(),
            1,
        )

        self.assertEqual(
            InvoiceValidationIssue.objects.filter(
                invoice=invoice
            ).count(),
            0,
        )

    def test_financial_validation_findings_are_persisted(self):

        payload = self.valid_extraction_payload()
        payload["total_amount"] = "105000.00"

        service = FakeExtractionService(payload)

        invoice = process_invoice(
            self.invoice.id,
            extraction_service=service,
        )

        issues = InvoiceValidationIssue.objects.filter(
            invoice=invoice
        )

        self.assertTrue(
            issues.filter(
                code="TOTAL_MISMATCH"
            ).exists()
        )

        self.assertEqual(
            invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )

    def test_scanned_pdf_is_marked_as_failed(self):

        scanned_document = self.create_document(
            self.generate_pdf(scanned=True)
        )

        scanned_invoice = Invoice.objects.create(
            organization=self.organization,
            source_document=scanned_document,
        )

        with self.assertRaises(OCRRequiredError):

            process_invoice(
                scanned_invoice.id,
                extraction_service=FakeExtractionService(
                    self.valid_extraction_payload()
                ),
            )

        scanned_invoice.refresh_from_db()
        scanned_document.refresh_from_db()

        self.assertEqual(
            scanned_invoice.status,
            Invoice.Status.FAILED,
        )

        self.assertEqual(
            scanned_document.status,
            Document.Status.FAILED,
        )

        self.assertTrue(
            scanned_document.processing_error
        )

    def test_completed_invoice_cannot_be_processed_again(self):

        service = FakeExtractionService(
            self.valid_extraction_payload()
        )

        process_invoice(
            self.invoice.id,
            extraction_service=service,
        )

        with self.assertRaises(InvoiceProcessingStateError):

            process_invoice(
                self.invoice.id,
                extraction_service=service,
            )

        self.assertEqual(
            InvoiceLineItem.objects.filter(
                invoice=self.invoice
            ).count(),
            1,
        )

class InvoiceQueueAPITests(TestCase):

    def setUp(self):

        self.user = get_user_model().objects.create_user(
            username="queue_operator",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Queue Test Company",
            slug="queue-test-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.document = Document.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="queue_test.pdf",
            file="queue_test.pdf",
            content_type="application/pdf",
            file_size=100,
            status=Document.Status.UPLOADED,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            source_document=self.document,
            status=Invoice.Status.UPLOADED,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.process_url = reverse(
            "invoice-process",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
            },
        )

        self.status_url = reverse(
            "invoice-processing-status",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
            },
        )

    @patch("invoices.views.process_invoice_task.apply_async")
    def test_invoice_is_queued_successfully(self, enqueue):

        response = self.client.post(
            self.process_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 202)

        self.invoice.refresh_from_db()
        self.document.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.QUEUED,
        )

        self.assertEqual(
            self.document.status,
            Document.Status.QUEUED,
        )

        self.assertIsNotNone(
            self.invoice.processing_task_id,
        )

        self.assertIsNotNone(
            self.invoice.queued_at,
        )

        enqueue.assert_called_once_with(
            args=[
                str(self.invoice.id),
                str(self.invoice.processing_task_id),
            ],
            task_id=str(self.invoice.processing_task_id),
        )

    @patch("invoices.views.process_invoice_task.apply_async")
    def test_already_queued_invoice_cannot_be_queued_again(
        self,
        enqueue,
    ):

        first_response = self.client.post(
            self.process_url,
            {},
            format="json",
        )

        second_response = self.client.post(
            self.process_url,
            {},
            format="json",
        )

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(second_response.status_code, 409)

        enqueue.assert_called_once()

    @patch("invoices.views.process_invoice_task.apply_async")
    def test_read_only_member_cannot_queue_invoice(
        self,
        enqueue,
    ):

        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )

        self.membership.save()

        response = self.client.post(
            self.process_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.UPLOADED,
        )

        enqueue.assert_not_called()

    @patch(
        "invoices.views.process_invoice_task.apply_async",
        side_effect=RuntimeError("Redis unavailable"),
    )
    def test_broker_failure_marks_invoice_failed(
        self,
        enqueue,
    ):

        response = self.client.post(
            self.process_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 503)

        self.invoice.refresh_from_db()
        self.document.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.FAILED,
        )

        self.assertEqual(
            self.document.status,
            Document.Status.FAILED,
        )

        self.assertTrue(
            self.document.processing_error,
        )

    def test_invoice_processing_status_is_accessible(self):

        response = self.client.get(
            self.status_url,
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["status"],
            Invoice.Status.UPLOADED,
        )

        self.assertEqual(
            response.data["document"]["status"],
            Document.Status.UPLOADED,
        )
        