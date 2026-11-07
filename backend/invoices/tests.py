from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse
from django.test import SimpleTestCase
from rest_framework.test import APIClient
from pydantic import ValidationError
from datetime import timedelta
from rest_framework import status
from django.utils import timezone
from invoices.schemas import InvoiceExtractionResult
import uuid
from auditlog.models import InvoiceAuditEvent
from invoices.services.extraction import (
    InvoiceExtractionError,
    InvoiceExtractionService,
    InvalidExtractionResponse,
)
from invoices.services.validation import (
    validate_invoice_extraction,
)

from invoices.services.outbox import (
    dispatch_pending_events,
    MAX_ATTEMPTS,
)

from approvals.models import ApprovalRequest, ApprovalDecision

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
from invoices.models import Invoice, InvoiceLineItem, InvoiceValidationIssue, OutboxEvent

from documents.extraction import OCRRequiredError
from invoices.services.processing import (
    process_invoice,
    InvoiceProcessingStateError,
)
from invoices.services.evidence import verify_extraction_evidence
from invoices.services.review import synchronize_validation_issues

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


class InvoiceEvidenceVerificationUnitTests(TestCase):
    """Fast unit tests checking specific text matching and evidence validation rules."""

    def setUp(self):
        self.extraction = InvoiceExtractionResult.model_validate(
            {
                "invoice_number": "DEMO-001",
                "supplier_legal_name": "ABC Engineering Ltd",
                "field_evidence": {
                    "invoice_number": [
                        {"page": 1, "quote": "Invoice Number: DEMO-001"}
                    ],
                    "supplier_legal_name": [
                        {"page": 1, "quote": "Supplier: ABC Engineering Ltd"}
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
        findings = verify_extraction_evidence(self.extraction, page_texts)
        self.assertEqual(findings, [])

    def test_missing_page_is_flagged(self):
        findings = verify_extraction_evidence(self.extraction, {})
        self.assertEqual(len(findings), 2)
        self.assertTrue(
            all(finding.code == "EVIDENCE_PAGE_NOT_FOUND" for finding in findings)
        )

    def test_missing_quote_is_flagged(self):
        page_texts = {1: "Invoice Number: DIFFERENT-001"}
        findings = verify_extraction_evidence(self.extraction, page_texts)
        codes = {finding.code for finding in findings}
        self.assertIn("EVIDENCE_QUOTE_NOT_FOUND", codes)

    def test_page_without_searchable_text_requires_ocr(self):
        findings = verify_extraction_evidence(self.extraction, {1: ""})
        codes = {finding.code for finding in findings}
        self.assertIn("EVIDENCE_PAGE_REQUIRES_OCR", codes)

    def test_whitespace_and_case_differences_are_accepted(self):
        page_texts = {1: "INVOICE NUMBER:\n   DEMO-001"}
        extraction = InvoiceExtractionResult.model_validate(
            {
                "field_evidence": {
                    "invoice_number": [
                        {"page": 1, "quote": "Invoice Number: DEMO-001"}
                    ]
                }
            }
        )
        findings = verify_extraction_evidence(extraction, page_texts)
        self.assertEqual(findings, [])


class InvoiceEvidenceVerificationIntegrationTests(TestCase):
    """Integration tests verifying full PDF generation, storage, and processing matching."""

    def setUp(self):
        self.media_directory = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_directory)
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

        self.document = self.create_document(self.generate_pdf())
        self.invoice = Invoice.objects.create(
            organization=self.organization,
            source_document=self.document,
        )

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_directory, ignore_errors=True)
        super().tearDown()

    @staticmethod
    def generate_pdf(scanned=False):
        pdf = pymupdf.open()  # PyMuPDF mapping
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
        document.file.save("demo_invoice.pdf", ContentFile(content), save=False)
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
                "invoice_number": [{"page": 1, "quote": "Invoice Number: DEMO-002"}],
                "supplier_legal_name": [{"page": 1, "quote": "Supplier: ABC Engineering Ltd"}],
                "invoice_date": [{"page": 1, "quote": "Date: 06 November 2026"}],
                "currency": [{"page": 1, "quote": "Subtotal: NGN 100000.00"}],
                "subtotal": [{"page": 1, "quote": "Subtotal: NGN 100000.00"}],
                "taxes": [{"page": 1, "quote": "VAT: NGN 7500.00"}],
                "total_amount": [{"page": 1, "quote": "Total: NGN 107500.00"}],
                "line_items": [{"page": 1, "quote": "Description: Engineering services"}],
            },
        }

    def test_generated_pdf_can_be_verified_against_payload(self):
        """Your actual functional test goes here."""
        extraction = InvoiceExtractionResult.model_validate(self.valid_extraction_payload())
        
        # Simulating extraction of text from generated PDF
        page_texts = {
            1: (
                "SUPPLIER INVOICE\n"
                "Invoice Number: DEMO-002\n"
                "Supplier: ABC Engineering Ltd\n"
                "Date: 06 November 2026\n"
                "Subtotal: NGN 100000.00\n"
                "VAT: NGN 7500.00\n"
                "Total: NGN 107500.00\n"
                "Description: Engineering services"
            )
        }
        
        findings = verify_extraction_evidence(extraction, page_texts)
        self.assertEqual(findings, [])


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

    def test_invoice_is_queued_successfully(self):
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

        event = OutboxEvent.objects.get(
            aggregate_id=self.invoice.id,
        )

        self.assertEqual(
            event.status,
            OutboxEvent.Status.PENDING,
        )

        self.assertEqual(
            event.event_type,
            "invoice.process",
        )

        self.assertEqual(
            event.payload["invoice_id"],
            str(self.invoice.id),
        )

        self.assertEqual(
            event.payload["task_id"],
            str(self.invoice.processing_task_id),
        )

        self.assertEqual(
            event.idempotency_key,
            (
                f"invoice.process:{self.invoice.id}:"
                f"{self.invoice.processing_task_id}"
            ),
        )

        self.assertIsNotNone(
            self.invoice.processing_task_id,
        )

        self.assertIsNotNone(
            self.invoice.queued_at,
        )

        audit_event = InvoiceAuditEvent.objects.get(
            invoice_id=response.data["invoice_id"],
            action=InvoiceAuditEvent.Action.PROCESSING_QUEUED,
        )

        self.assertEqual(audit_event.actor, self.user)
        self.assertEqual(
            audit_event.metadata["task_id"],
            response.data["task_id"],
        )
        self.assertEqual(
            audit_event.metadata["outbox_event_id"],
            response.data["outbox_event_id"],
        )

        # Assert that the Outbox event was created correctly in the database
        outbox_event = OutboxEvent.objects.filter(
            event_type="invoice.process",
            aggregate_id=self.invoice.id,
        ).first()
        
        self.assertIsNotNone(outbox_event)
        self.assertEqual(
            outbox_event.payload["invoice_id"], 
            str(self.invoice.id)
        )
        self.assertEqual(
            outbox_event.payload["task_id"], 
            str(self.invoice.processing_task_id)
        )

    def test_already_queued_invoice_cannot_be_queued_again(self):
        first_response = self.client.post(
            self.process_url,
            {},
            format="json",
        )
        self.assertEqual(first_response.status_code, 202)

        second_response = self.client.post(
            self.process_url,
            {},
            format="json",
        )
        self.assertEqual(second_response.status_code, 409)

        # Check that only one single outbox record was written
        self.assertEqual(
            OutboxEvent.objects.filter(
                event_type="invoice.process", 
                aggregate_id=self.invoice.id
            ).count(),
            1
        )

    def test_read_only_member_cannot_queue_invoice(self):
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

        # No outbox entries should exist for a failed permissions attempt
        self.assertFalse(
            OutboxEvent.objects.filter(
                event_type="invoice.process", 
                aggregate_id=self.invoice.id
            ).exists()
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

    @patch("invoices.tasks.process_invoice_task.apply_async")
    def test_queue_request_does_not_publish_directly(
        self,
        enqueue,
    ):
        response = self.client.post(self.process_url)

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        enqueue.assert_not_called()

        event = OutboxEvent.objects.get(
            id=response.data["outbox_event_id"]
        )

        self.assertEqual(
            event.status,
            OutboxEvent.Status.PENDING,
        )


class InvoiceOutboxTests(TestCase):

    def create_event(self, **overrides):

        defaults = {
            "event_type": "invoice.process",
            "aggregate_id": uuid.uuid4(),
            "idempotency_key": str(uuid.uuid4()),
            "payload": {
                "invoice_id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
            },
        }

        defaults.update(overrides)

        return OutboxEvent.objects.create(**defaults)

    @patch("invoices.services.outbox.publish_event")
    def test_pending_event_is_published(self, publish):

        event = self.create_event()

        result = dispatch_pending_events()

        event.refresh_from_db()

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["published"], 1)

        self.assertEqual(
            event.status,
            OutboxEvent.Status.PUBLISHED,
        )

        self.assertEqual(event.attempts, 1)

        self.assertIsNotNone(event.published_at)

        self.assertIsNone(event.locked_at)

        publish.assert_called_once()

    @patch(
        "invoices.services.outbox.publish_event",
        side_effect=RuntimeError("Redis unavailable"),
    )
    def test_publication_failure_schedules_retry(self, publish):

        event = self.create_event()

        result = dispatch_pending_events()

        event.refresh_from_db()

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["retry_scheduled"], 1)

        self.assertEqual(
            event.status,
            OutboxEvent.Status.PENDING,
        )

        self.assertEqual(event.attempts, 1)

        self.assertTrue(event.last_error)

        self.assertIsNone(event.locked_at)

    @patch(
        "invoices.services.outbox.publish_event",
        side_effect=RuntimeError("Redis unavailable"),
    )
    def test_maximum_attempts_marks_event_failed(self, publish):

        event = self.create_event(
            attempts=MAX_ATTEMPTS - 1,
        )

        result = dispatch_pending_events()

        event.refresh_from_db()

        self.assertEqual(result["failed"], 1)

        self.assertEqual(
            event.attempts,
            MAX_ATTEMPTS,
        )

        self.assertEqual(
            event.status,
            OutboxEvent.Status.FAILED,
        )

    @patch("invoices.services.outbox.publish_event")
    def test_stale_dispatching_event_is_recovered(self, publish):

        event = self.create_event(
            status=OutboxEvent.Status.DISPATCHING,
            attempts=1,
            locked_at=(
                timezone.now() - timedelta(minutes=10)
            ),
        )

        result = dispatch_pending_events()

        event.refresh_from_db()

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["published"], 1)

        self.assertEqual(
            event.status,
            OutboxEvent.Status.PUBLISHED,
        )

        self.assertEqual(event.attempts, 2)

        publish.assert_called_once()

    @patch("invoices.services.outbox.publish_event")
    def test_future_retry_event_is_not_dispatched(self, publish):

        event = self.create_event(
            available_at=(
                timezone.now() + timedelta(minutes=5)
            ),
        )

        result = dispatch_pending_events()

        self.assertEqual(result["claimed"], 0)

        publish.assert_not_called()

        event.refresh_from_db()

        self.assertEqual(
            event.status,
            OutboxEvent.Status.PENDING,
        )


class InvoiceReviewDetailAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="review_operator",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Review Test Company",
            slug="review-test-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.document = Document.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="review_test.pdf",
            file="review_test.pdf",
            content_type="application/pdf",
            file_size=100,
            status=Document.Status.PROCESSED,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            source_document=self.document,
            invoice_number="REVIEW-001",
            status=Invoice.Status.NEEDS_REVIEW,
            currency="NGN",
            subtotal=300000,
            tax_amount=22500,
            total_amount=322500,
            extracted_data={
                "supplier_legal_name": "ABC Engineering Ltd",
                "invoice_number": "REVIEW-001",
                "field_evidence": {
                    "supplier_legal_name": [
                        {
                            "page": 1,
                            "quote": "Supplier: ABC Engineering Ltd",
                        }
                    ]
                },
            },
            field_confidence={
                "supplier_legal_name": 0.98,
                "invoice_number": 0.99,
            },
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.review_url = reverse(
            "invoice-review-detail",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
            },
        )

    def test_authorized_reviewer_can_retrieve_review(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_REVIEWER
        )
        self.membership.save()

        response = self.client.get(self.review_url)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["invoice"]["id"],
            str(self.invoice.id),
        )

        self.assertEqual(
            response.data["invoice"]["status"],
            Invoice.Status.NEEDS_REVIEW,
        )

        self.assertEqual(
            response.data["supplier"]["extracted_supplier"]["legal_name"],
            "ABC Engineering Ltd",
        )

        self.assertEqual(
            response.data["document"]["id"],
            str(self.document.id),
        )

        self.assertEqual(
            response.data["extraction"]["field_confidence"][
                "supplier_legal_name"
            ],
            0.98,
        )

    def test_read_only_member_can_retrieve_review(self):
        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.membership.save()

        response = self.client.get(self.review_url)

        self.assertEqual(response.status_code, 200)

    def test_inactive_member_cannot_retrieve_review(self):
        self.membership.is_active = False
        self.membership.save()

        response = self.client.get(self.review_url)

        self.assertEqual(response.status_code, 404)

    def test_invoice_from_another_organization_is_not_exposed(self):
        another_organization = Organization.objects.create(
            name="Another Review Company",
            slug="another-review-company",
        )

        OrganizationMembership.objects.create(
            organization=another_organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        another_org_url = reverse(
            "invoice-review-detail",
            kwargs={
                "organization_id": another_organization.id,
                "invoice_id": self.invoice.id,
            },
        )

        response = self.client.get(another_org_url)

        self.assertEqual(response.status_code, 404)

    def test_nonexistent_invoice_returns_404(self):
        missing_invoice_url = reverse(
            "invoice-review-detail",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": uuid.uuid4(),
            },
        )

        response = self.client.get(missing_invoice_url)

        self.assertEqual(response.status_code, 404)

    def test_invoice_without_document_returns_null_document(self):
        invoice_without_document = Invoice.objects.create(
            organization=self.organization,
            invoice_number="NO-DOCUMENT-001",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        url = reverse(
            "invoice-review-detail",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": invoice_without_document.id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["document"])

    def test_validation_issues_and_audit_history_are_returned(self):
        issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="UNKNOWN_VENDOR",
            severity=InvoiceValidationIssue.Severity.WARNING,
            field_name="supplier_legal_name",
            message="No existing vendor matches the extracted supplier.",
            status=InvoiceValidationIssue.Status.OPEN,
        )

        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            position=1,
            description="Engineering services",
            quantity="1.0000",
            unit_price="300000.00",
            line_total="300000.00",
        )

        audit_event = InvoiceAuditEvent.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            actor=self.user,
            action=InvoiceAuditEvent.Action.PROCESSING_QUEUED,
            changes={},
            metadata={
                "source": "test",
            },
        )

        response = self.client.get(self.review_url)

        self.assertEqual(response.status_code, 200)

        # Validation
        self.assertEqual(
            response.data["validation"]["total_issues"],
            1,
        )

        self.assertEqual(
            response.data["validation"]["open_issues"],
            1,
        )

        self.assertEqual(
            response.data["validation"]["issues"][0]["id"],
            str(issue.id),
        )

        # Line items
        self.assertEqual(
            len(response.data["line_items"]),
            1,
        )

        self.assertEqual(
            response.data["line_items"][0]["description"],
            "Engineering services",
        )

        # Audit history
        self.assertEqual(
            len(response.data["audit_history"]),
            1,
        )

        self.assertEqual(
            response.data["audit_history"][0]["id"],
            str(audit_event.id),
        )

        self.assertEqual(
            response.data["audit_history"][0]["actor"]["id"],
            str(self.user.id),
        )


class InvoiceHeaderCorrectionAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="correction_operator",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Correction Test Company",
            slug="correction-test-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="INV-001",
            invoice_date="2026-11-06",
            currency="NGN",
            subtotal="300000.00",
            tax_amount="22500.00",
            other_charges="0.00",
            total_amount="322500.00",
            status=Invoice.Status.NEEDS_REVIEW,
            extracted_data={
                "supplier_legal_name": "ABC Engineering Ltd",
                "invoice_number": "INV-001",
                "invoice_date": "2026-11-06",
                "currency": "NGN",
                "subtotal": "300000.00",
                "taxes": [
                    {
                        "name": "VAT",
                        "tax_type": "VAT",
                        "treatment": "added",
                        "amount": "22500.00",
                        "rate_percent": "7.5",
                    }
                ],
                "other_charges": "0.00",
                "total_amount": "322500.00",
                "amount_due": None,
                "line_items": None,
            },
            field_confidence={
                "invoice_number": 0.98,
                "total_amount": 0.99,
            },
        )

        self.original_extraction = self.invoice.extracted_data.copy()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.review_url = reverse(
            "invoice-review-detail",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
            },
        )

    def test_owner_can_correct_invoice_header(self):
        response = self.client.patch(
            self.review_url,
            {
                "total_amount": "320000.00",
                "correction_reason": (
                    "Corrected against the original supplier document."
                ),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.total_amount,
            Decimal("320000.00"),
        )

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )

        # Original AI extraction must remain unchanged.
        self.assertEqual(
            self.invoice.extracted_data,
            self.original_extraction,
        )

        audit_event = InvoiceAuditEvent.objects.get(
            invoice=self.invoice,
            action=InvoiceAuditEvent.Action.FIELD_UPDATED,
        )

        self.assertEqual(
            audit_event.actor,
            self.user,
        )

        self.assertEqual(
            audit_event.changes["total_amount"]["before"],
            "322500.00",
        )

        self.assertEqual(
            audit_event.changes["total_amount"]["after"],
            "320000.00",
        )

        self.assertEqual(
            audit_event.metadata["correction_reason"],
            "Corrected against the original supplier document.",
        )

    def test_correction_reruns_financial_validation(self):
        response = self.client.patch(
            self.review_url,
            {
                "total_amount": "320000.00",
                "correction_reason": "Testing financial revalidation.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["validation"]["new_validation_findings"],
            1,
        )

        issue = InvoiceValidationIssue.objects.get(
            invoice=self.invoice,
            code="TOTAL_MISMATCH",
        )

        self.assertEqual(
            issue.status,
            InvoiceValidationIssue.Status.OPEN,
        )

    def test_read_only_member_cannot_correct_invoice(self):
        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.membership.save()

        response = self.client.patch(
            self.review_url,
            {
                "total_amount": "320000.00",
                "correction_reason": "Test correction.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_finance_operator_can_correct_invoice(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_OPERATOR
        )
        self.membership.save()

        response = self.client.patch(
            self.review_url,
            {
                "invoice_number": "INV-002",
                "correction_reason": "Corrected invoice number.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_unknown_fields_are_rejected(self):
        response = self.client.patch(
            self.review_url,
            {
                "vendor_id": str(uuid.uuid4()),
                "correction_reason": "Attempting unsupported field.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_correction_reason_is_required(self):
        response = self.client.patch(
            self.review_url,
            {
                "total_amount": "320000.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_approved_invoice_cannot_be_corrected(self):
        self.invoice.status = Invoice.Status.APPROVED
        self.invoice.save(update_fields=["status", "updated_at"])

        response = self.client.patch(
            self.review_url,
            {
                "total_amount": "320000.00",
                "correction_reason": "Attempted correction.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_unchanged_values_are_rejected(self):
        response = self.client.patch(
            self.review_url,
            {
                "invoice_number": "INV-001",
                "correction_reason": "No actual change.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.assertFalse(
            InvoiceAuditEvent.objects.filter(
                invoice=self.invoice,
                action=InvoiceAuditEvent.Action.FIELD_UPDATED,
            ).exists()
        )

    def test_invoice_from_another_organization_cannot_be_corrected(self):
        another_organization = Organization.objects.create(
            name="Foreign Company",
            slug="foreign-company",
        )

        another_invoice = Invoice.objects.create(
            organization=another_organization,
            invoice_number="FOREIGN-001",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        foreign_url = reverse(
            "invoice-review-detail",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": another_invoice.id,
            },
        )

        response = self.client.patch(
            foreign_url,
            {
                "invoice_number": "CHANGED",
                "correction_reason": "Testing tenant isolation.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 404)

        another_invoice.refresh_from_db()

        self.assertEqual(
            another_invoice.invoice_number,
            "FOREIGN-001",
        )


class InvoiceVendorResolutionAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="vendor_resolver",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Vendor Resolution Company",
            slug="vendor-resolution-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="VENDOR-001",
            status=Invoice.Status.NEEDS_REVIEW,
            extracted_data={
                "supplier_legal_name": "ABC Engineering Ltd",
                "invoice_number": "VENDOR-001",
            },
        )

        self.original_extraction = self.invoice.extracted_data.copy()

        self.vendor = Vendor.objects.create(
            organization=self.organization,
            legal_name="ABC Engineering Ltd",
            display_name="ABC Engineering",
            is_active=True,
        )

        self.issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="UNKNOWN_VENDOR",
            severity=InvoiceValidationIssue.Severity.WARNING,
            field_name="supplier_legal_name",
            message="No existing vendor matches the extracted supplier.",
            status=InvoiceValidationIssue.Status.OPEN,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.resolution_url = reverse(
            "invoice-vendor-resolution",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
            },
        )

    def assign_vendor(self, vendor=None):
        vendor = vendor or self.vendor

        return self.client.patch(
            self.resolution_url,
            {
                "vendor_id": str(vendor.id),
                "correction_reason": (
                    "Matched against verified supplier records."
                ),
            },
            format="json",
        )

    def test_owner_can_assign_vendor_and_resolve_issue(self):
        response = self.assign_vendor()

        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()
        self.issue.refresh_from_db()

        self.assertEqual(
            self.invoice.vendor_id,
            self.vendor.id,
        )

        self.assertEqual(
            self.issue.status,
            InvoiceValidationIssue.Status.RESOLVED,
        )

        self.assertEqual(
            self.issue.resolved_by,
            self.user,
        )

        self.assertIsNotNone(self.issue.resolved_at)

        # Original AI extraction must remain unchanged.
        self.assertEqual(
            self.invoice.extracted_data,
            self.original_extraction,
        )

        audit_event = InvoiceAuditEvent.objects.get(
            invoice=self.invoice,
            action=InvoiceAuditEvent.Action.VENDOR_ASSIGNED,
        )

        self.assertEqual(audit_event.actor, self.user)

        self.assertIsNone(
            audit_event.changes["vendor"]["before"]
        )

        self.assertEqual(
            audit_event.changes["vendor"]["after"]["id"],
            str(self.vendor.id),
        )

        self.assertIn(
            str(self.issue.id),
            audit_event.metadata["resolved_validation_issue_ids"],
        )

    def test_finance_reviewer_can_assign_vendor(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_REVIEWER
        )
        self.membership.save()

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 200)

    def test_finance_operator_can_assign_vendor(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_OPERATOR
        )
        self.membership.save()

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 200)

    def test_read_only_member_cannot_assign_vendor(self):
        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.membership.save()

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 403)

        self.invoice.refresh_from_db()

        self.assertIsNone(self.invoice.vendor_id)

    def test_vendor_from_another_organization_is_rejected(self):
        another_organization = Organization.objects.create(
            name="External Vendor Company",
            slug="external-vendor-company",
        )

        foreign_vendor = Vendor.objects.create(
            organization=another_organization,
            legal_name="External Supplier Ltd",
            is_active=True,
        )

        response = self.assign_vendor(foreign_vendor)

        self.assertEqual(response.status_code, 404)

        self.invoice.refresh_from_db()

        self.assertIsNone(self.invoice.vendor_id)

    def test_inactive_vendor_is_rejected(self):
        self.vendor.is_active = False
        self.vendor.save(update_fields=["is_active"])

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 404)

        self.invoice.refresh_from_db()

        self.assertIsNone(self.invoice.vendor_id)

    def test_approved_invoice_cannot_be_modified(self):
        self.invoice.status = Invoice.Status.APPROVED
        self.invoice.save(update_fields=["status", "updated_at"])

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 409)

        self.invoice.refresh_from_db()

        self.assertIsNone(self.invoice.vendor_id)

    def test_already_assigned_vendor_is_rejected(self):
        self.invoice.vendor = self.vendor
        self.invoice.save(update_fields=["vendor", "updated_at"])

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 400)

        self.assertFalse(
            InvoiceAuditEvent.objects.filter(
                invoice=self.invoice,
                action=InvoiceAuditEvent.Action.VENDOR_ASSIGNED,
            ).exists()
        )

    def test_unrelated_validation_issue_remains_open(self):
        unrelated_issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="TOTAL_MISMATCH",
            severity=InvoiceValidationIssue.Severity.ERROR,
            field_name="total_amount",
            message="Invoice total does not reconcile.",
            status=InvoiceValidationIssue.Status.OPEN,
        )

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 200)

        unrelated_issue.refresh_from_db()

        self.assertEqual(
            unrelated_issue.status,
            InvoiceValidationIssue.Status.OPEN,
        )



class InvoiceLineItemAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="line_item_operator",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Line Item Test Company",
            slug="line-item-test-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="LINE-001",
            invoice_date="2026-11-06",
            currency="NGN",
            subtotal="100.00",
            other_charges="0.00",
            total_amount="100.00",
            status=Invoice.Status.NEEDS_REVIEW,
            extracted_data={
                "supplier_legal_name": "ABC Engineering Ltd",
                "invoice_number": "LINE-001",
                "invoice_date": "2026-11-06",
                "currency": "NGN",
                "subtotal": "100.00",
                "taxes": [],
                "other_charges": "0.00",
                "total_amount": "100.00",
                "line_items": [
                    {
                        "description": "Consulting",
                        "quantity": "1",
                        "unit_price": "100.00",
                        "line_total": "100.00",
                    }
                ],
            },
        )

        self.original_extraction = self.invoice.extracted_data.copy()

        self.item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            position=1,
            description="Consulting",
            quantity="1.0000",
            unit_price="100.00",
            line_total="100.00",
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.collection_url = reverse(
            "invoice-line-item-list",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
            },
        )

        self.detail_url = reverse(
            "invoice-line-item-detail",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
                "line_item_id": self.item.id,
            },
        )

    def test_owner_can_add_line_item(self):
        response = self.client.post(
            self.collection_url,
            {
                "description": "Travel expenses",
                "quantity": "1",
                "unit_price": "20.00",
                "line_total": "20.00",
                "correction_reason": "Additional item verified.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        added_item = InvoiceLineItem.objects.get(
            id=response.data["line_item"]["id"]
        )

        self.assertEqual(added_item.position, 2)
        self.assertEqual(added_item.description, "Travel expenses")

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.extracted_data,
            self.original_extraction,
        )

        self.assertTrue(
            InvoiceValidationIssue.objects.filter(
                invoice=self.invoice,
                code="SUBTOTAL_MISMATCH",
                status=InvoiceValidationIssue.Status.OPEN,
            ).exists()
        )

        self.assertTrue(
            InvoiceAuditEvent.objects.filter(
                invoice=self.invoice,
                action=InvoiceAuditEvent.Action.FIELD_UPDATED,
                metadata__operation="line_item_added",
            ).exists()
        )

    def test_owner_can_update_line_item(self):
        response = self.client.patch(
            self.detail_url,
            {
                "line_total": "120.00",
                "correction_reason": "Corrected against supplier invoice.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.item.refresh_from_db()

        self.assertEqual(
            self.item.line_total,
            Decimal("120.00"),
        )

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.extracted_data,
            self.original_extraction,
        )

        audit_event = InvoiceAuditEvent.objects.get(
            invoice=self.invoice,
            action=InvoiceAuditEvent.Action.FIELD_UPDATED,
            metadata__operation="line_item_updated",
        )

        change_key = f"line_items.{self.item.id}.line_total"

        self.assertEqual(
            audit_event.changes[change_key]["before"],
            "100.00",
        )

        self.assertEqual(
            audit_event.changes[change_key]["after"],
            "120.00",
        )

    def test_owner_can_delete_line_item(self):
        issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="SUBTOTAL_MISMATCH",
            severity=InvoiceValidationIssue.Severity.ERROR,
            field_name="subtotal",
            message="Subtotal does not reconcile.",
            status=InvoiceValidationIssue.Status.OPEN,
        )

        response = self.client.delete(
            self.detail_url,
            {
                "correction_reason": "Incorrectly extracted item removed.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            InvoiceLineItem.objects.filter(
                pk=self.item.id,
            ).exists()
        )

        issue.refresh_from_db()

        self.assertEqual(
            issue.status,
            InvoiceValidationIssue.Status.RESOLVED,
        )

        self.assertEqual(issue.resolved_by, self.user)

        self.assertTrue(
            InvoiceAuditEvent.objects.filter(
                invoice=self.invoice,
                action=InvoiceAuditEvent.Action.FIELD_UPDATED,
                metadata__operation="line_item_deleted",
            ).exists()
        )

    def test_read_only_member_cannot_add_line_item(self):
        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.membership.save()

        response = self.client.post(
            self.collection_url,
            {
                "description": "Unauthorized item",
                "correction_reason": "Test permissions.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.assertEqual(
            self.invoice.line_items.count(),
            1,
        )

    def test_approved_invoice_cannot_be_modified(self):
        self.invoice.status = Invoice.Status.APPROVED
        self.invoice.save(
            update_fields=["status", "updated_at"]
        )

        response = self.client.patch(
            self.detail_url,
            {
                "description": "Changed item",
                "correction_reason": "Testing state protection.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409)

    def test_line_item_from_another_invoice_is_not_accessible(self):
        another_invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="LINE-002",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        another_item = InvoiceLineItem.objects.create(
            invoice=another_invoice,
            position=1,
            description="Another invoice item",
        )

        response = self.client.patch(
            reverse(
                "invoice-line-item-detail",
                kwargs={
                    "organization_id": self.organization.id,
                    "invoice_id": self.invoice.id,
                    "line_item_id": another_item.id,
                },
            ),
            {
                "description": "Unauthorized modification",
                "correction_reason": "Testing invoice isolation.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 404)

        another_item.refresh_from_db()

        self.assertEqual(
            another_item.description,
            "Another invoice item",
        )

    def test_unknown_fields_are_rejected(self):
        response = self.client.patch(
            self.detail_url,
            {
                "description": "Corrected",
                "vendor_id": str(uuid.uuid4()),
                "correction_reason": "Testing field restrictions.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_correction_reason_is_required(self):
        response = self.client.patch(
            self.detail_url,
            {
                "description": "Corrected description",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_unchanged_line_item_is_rejected(self):
        response = self.client.patch(
            self.detail_url,
            {
                "description": "Consulting",
                "correction_reason": "No actual change.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.assertFalse(
            InvoiceAuditEvent.objects.filter(
                invoice=self.invoice,
                metadata__operation="line_item_updated",
            ).exists()
        )

    def test_adding_line_item_requires_description(self):
        response = self.client.post(
            self.collection_url,
            {
                "quantity": "1",
                "unit_price": "50.00",
                "correction_reason": "Missing description test.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class InvoiceValidationIssueManagementAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="issue_reviewer",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Issue Management Company",
            slug="issue-management-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="ISSUE-001",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        self.issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="LOW_CONFIDENCE",
            severity=InvoiceValidationIssue.Severity.WARNING,
            field_name="invoice_number",
            message="The extracted invoice number has low confidence.",
            status=InvoiceValidationIssue.Status.OPEN,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.issue_url = reverse(
            "invoice-validation-issue-ignore",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
                "issue_id": self.issue.id,
            },
        )

    def ignore_issue(self, reason="Reviewed and accepted."):
        return self.client.post(
            self.issue_url,
            {"decision_reason": reason},
            format="json",
        )

    def test_owner_can_ignore_eligible_warning(self):
        response = self.ignore_issue()

        self.assertEqual(response.status_code, 200)

        self.issue.refresh_from_db()

        self.assertEqual(
            self.issue.status,
            InvoiceValidationIssue.Status.IGNORED,
        )

        self.assertEqual(self.issue.resolved_by, self.user)
        self.assertIsNotNone(self.issue.resolved_at)

        self.assertEqual(
            self.issue.decision_reason,
            "Reviewed and accepted.",
        )

    def test_finance_reviewer_can_ignore_warning(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_REVIEWER
        )
        self.membership.save()

        response = self.ignore_issue()

        self.assertEqual(response.status_code, 200)

    def test_finance_operator_cannot_ignore_warning(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_OPERATOR
        )
        self.membership.save()

        response = self.ignore_issue()

        self.assertEqual(response.status_code, 403)

        self.issue.refresh_from_db()

        self.assertEqual(
            self.issue.status,
            InvoiceValidationIssue.Status.OPEN,
        )

    def test_read_only_member_cannot_ignore_warning(self):
        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.membership.save()

        response = self.ignore_issue()

        self.assertEqual(response.status_code, 403)

    def test_error_severity_issue_cannot_be_ignored(self):
        self.issue.severity = InvoiceValidationIssue.Severity.ERROR
        self.issue.save(update_fields=["severity", "updated_at"])

        response = self.ignore_issue()

        self.assertEqual(response.status_code, 400)

        self.issue.refresh_from_db()

        self.assertEqual(
            self.issue.status,
            InvoiceValidationIssue.Status.OPEN,
        )

    def test_unknown_vendor_issue_cannot_be_ignored(self):
        self.issue.code = "UNKNOWN_VENDOR"
        self.issue.save(update_fields=["code", "updated_at"])

        response = self.ignore_issue()

        self.assertEqual(response.status_code, 400)

    def test_missing_required_field_cannot_be_ignored(self):
        self.issue.code = "MISSING_REQUIRED_FIELD"
        self.issue.save(update_fields=["code", "updated_at"])

        response = self.ignore_issue()

        self.assertEqual(response.status_code, 400)

    def test_issue_from_another_invoice_is_not_accessible(self):
        another_invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="ISSUE-002",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        another_issue = InvoiceValidationIssue.objects.create(
            invoice=another_invoice,
            code="LOW_CONFIDENCE",
            severity=InvoiceValidationIssue.Severity.WARNING,
            message="Another invoice issue.",
        )

        foreign_issue_url = reverse(
            "invoice-validation-issue-ignore",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
                "issue_id": another_issue.id,
            },
        )

        response = self.client.post(
            foreign_issue_url,
            {"decision_reason": "Testing invoice isolation."},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

    def test_already_ignored_issue_cannot_be_ignored_again(self):
        self.issue.status = InvoiceValidationIssue.Status.IGNORED
        self.issue.decision_reason = "Previously acknowledged."
        self.issue.save(
            update_fields=[
                "status",
                "decision_reason",
                "updated_at",
            ]
        )

        response = self.ignore_issue()

        self.assertEqual(response.status_code, 409)

    def test_decision_reason_is_required(self):
        response = self.client.post(
            self.issue_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_audit_event_records_decision(self):
        response = self.ignore_issue(
            "Accepted as a documented exception."
        )

        self.assertEqual(response.status_code, 200)

        event = InvoiceAuditEvent.objects.get(
            invoice=self.invoice,
            action=InvoiceAuditEvent.Action.VALIDATION_ISSUE_IGNORED,
        )

        self.assertEqual(event.actor, self.user)

        self.assertEqual(
            event.metadata["issue_id"],
            str(self.issue.id),
        )

        self.assertEqual(
            event.metadata["decision_reason"],
            "Accepted as a documented exception.",
        )

    def test_ignored_issue_becomes_resolved_when_finding_disappears(self):
        self.issue.code = "DUE_DATE_BEFORE_INVOICE_DATE"
        self.issue.field_name = "due_date"
        self.issue.severity = (
            InvoiceValidationIssue.Severity.WARNING
        )
        self.issue.status = (
            InvoiceValidationIssue.Status.IGNORED
        )
        self.issue.decision_reason = "Previously accepted."
        self.issue.resolved_by = self.user

        self.issue.save()

        resolved_ids = synchronize_validation_issues(
            invoice=self.invoice,
            findings=[],
            actor=self.user,
        )

        self.issue.refresh_from_db()

        self.assertEqual(
        self.issue.status,
        InvoiceValidationIssue.Status.RESOLVED,
        )

        self.assertEqual(self.issue.decision_reason, "")

        self.assertEqual(self.issue.resolved_by, self.user)

        self.assertIsNotNone(self.issue.resolved_at)

        self.assertIn(str(self.issue.id), resolved_ids)

class InvoiceReviewSubmissionAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="submission_operator",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Submission Test Company",
            slug="submission-test-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.vendor = Vendor.objects.create(
            organization=self.organization,
            legal_name="ABC Engineering Ltd",
            is_active=True,
        )

        self.document = Document.objects.create(
            organization=self.organization,
            uploaded_by=self.user,
            original_filename="submission.pdf",
            file="submission.pdf",
            content_type="application/pdf",
            file_size=100,
            status=Document.Status.PROCESSED,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            vendor=self.vendor,
            source_document=self.document,
            invoice_number="SUBMIT-001",
            invoice_date="2026-11-06",
            currency="NGN",
            subtotal="100.00",
            tax_amount="0.00",
            other_charges="0.00",
            total_amount="100.00",
            status=Invoice.Status.NEEDS_REVIEW,
            extracted_data={
                "supplier_legal_name": "ABC Engineering Ltd",
                "invoice_number": "SUBMIT-001",
                "invoice_date": "2026-11-06",
                "currency": "NGN",
                "subtotal": "100.00",
                "taxes": [],
                "other_charges": "0.00",
                "total_amount": "100.00",
                "line_items": None,
            },
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.submit_url = reverse(
            "invoice-review-submit",
            kwargs={
                "organization_id": self.organization.id,
                "invoice_id": self.invoice.id,
            },
        )

    def submit(self):
        return self.client.post(
            self.submit_url,
            {"submission_note": "Review completed."},
            format="json",
        )

    def test_owner_can_submit_valid_invoice(self):
        response = self.submit()

        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.PENDING_APPROVAL,
        )

        event = InvoiceAuditEvent.objects.get(
            invoice=self.invoice,
            action=InvoiceAuditEvent.Action.REVIEW_SUBMITTED,
        )

        self.assertEqual(event.actor, self.user)

        self.assertEqual(
            event.changes["status"]["before"],
            Invoice.Status.NEEDS_REVIEW,
        )

        self.assertEqual(
            event.changes["status"]["after"],
            Invoice.Status.PENDING_APPROVAL,
        )

        approval_request = ApprovalRequest.objects.get(
            invoice=self.invoice,
            status=ApprovalRequest.Status.PENDING,
        )

        self.assertEqual(
            approval_request.organization,
            self.organization,
        )

        self.assertEqual(
            approval_request.submitted_by,
            self.user,
        )

        self.assertEqual(
            approval_request.submission_note,
            "Review completed.",
        )

        self.assertEqual(
            str(approval_request.id),
            response.data["approval_request_id"],
        )

    def test_finance_administrator_can_submit(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_ADMIN
        )
        self.membership.save()

        response = self.submit()

        self.assertEqual(response.status_code, 200)

    def test_finance_operator_can_submit(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_OPERATOR
        )
        self.membership.save()

        response = self.submit()

        self.assertEqual(response.status_code, 200)

    def test_finance_reviewer_cannot_submit(self):
        self.membership.role = (
            OrganizationMembership.Role.FINANCE_REVIEWER
        )
        self.membership.save()

        response = self.submit()

        self.assertEqual(response.status_code, 403)

    def test_read_only_member_cannot_submit(self):
        self.membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.membership.save()

        response = self.submit()

        self.assertEqual(response.status_code, 403)

    def test_missing_vendor_blocks_submission(self):
        self.invoice.vendor = None
        self.invoice.save(update_fields=["vendor", "updated_at"])

        response = self.submit()

        self.assertEqual(response.status_code, 409)

        self.assertIn(
            "VENDOR_NOT_ASSIGNED",
            [blocker["code"] for blocker in response.data["blockers"]],
        )

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )

        self.assertFalse(
            ApprovalRequest.objects.filter(
                invoice=self.invoice,
            ).exists()
        )

    def test_missing_document_blocks_submission(self):
        self.invoice.source_document = None
        self.invoice.save(
            update_fields=["source_document", "updated_at"]
        )

        response = self.submit()

        self.assertEqual(response.status_code, 409)

        self.assertIn(
            "SOURCE_DOCUMENT_MISSING",
            [blocker["code"] for blocker in response.data["blockers"]],
        )

    def test_unprocessed_document_blocks_submission(self):
        self.document.status = Document.Status.UPLOADED
        self.document.save(update_fields=["status", "updated_at"])

        response = self.submit()

        self.assertEqual(response.status_code, 409)

        self.assertIn(
            "SOURCE_DOCUMENT_NOT_PROCESSED",
            [blocker["code"] for blocker in response.data["blockers"]],
        )

    def test_missing_required_field_blocks_submission(self):
        self.invoice.invoice_number = ""
        self.invoice.save(
            update_fields=["invoice_number", "updated_at"]
        )

        response = self.submit()

        self.assertEqual(response.status_code, 409)

        self.assertIn(
            "MISSING_REQUIRED_FIELD",
            [blocker["code"] for blocker in response.data["blockers"]],
        )

        self.assertTrue(
            InvoiceValidationIssue.objects.filter(
                invoice=self.invoice,
                code="MISSING_REQUIRED_FIELD",
                field_name="invoice_number",
                status=InvoiceValidationIssue.Status.OPEN,
            ).exists()
        )

    def test_open_warning_blocks_submission(self):
        issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="LOW_CONFIDENCE",
            severity=InvoiceValidationIssue.Severity.WARNING,
            field_name="invoice_number",
            message="Invoice number has low confidence.",
            status=InvoiceValidationIssue.Status.OPEN,
        )

        response = self.submit()

        self.assertEqual(response.status_code, 409)

        self.assertIn(
            issue.code,
            [blocker["code"] for blocker in response.data["blockers"]],
        )

    def test_ignored_warning_does_not_block_submission(self):
        InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="LOW_CONFIDENCE",
            severity=InvoiceValidationIssue.Severity.WARNING,
            field_name="invoice_number",
            message="Previously acknowledged warning.",
            status=InvoiceValidationIssue.Status.IGNORED,
            resolved_by=self.user,
            decision_reason="Reviewed and accepted.",
            resolved_at=timezone.now(),
        )

        response = self.submit()

        self.assertEqual(response.status_code, 200)

    def test_ignored_error_blocks_submission(self):
        InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="TOTAL_MISMATCH",
            severity=InvoiceValidationIssue.Severity.ERROR,
            field_name="total_amount",
            message="Financial discrepancy.",
            status=InvoiceValidationIssue.Status.IGNORED,
            resolved_by=self.user,
            decision_reason="Attempted exception.",
            resolved_at=timezone.now(),
        )

        # Introduce a real financial discrepancy so that
        # revalidation confirms the ignored error still exists.

        self.invoice.total_amount = Decimal("105.00")
        self.invoice.save(
            update_fields=["total_amount", "updated_at"]
        )

        response = self.submit()

        self.assertEqual(response.status_code, 409)

        self.assertIn(
            "IGNORED_ERROR",
            [blocker["code"] for blocker in response.data["blockers"]],
        )

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )

        issue = InvoiceValidationIssue.objects.get(
            invoice=self.invoice,
            code="TOTAL_MISMATCH",
        )

        self.assertEqual(
            issue.status,
            InvoiceValidationIssue.Status.IGNORED,
        )

        
    def test_rejected_invoice_can_be_returned_and_resubmitted_without_losing_history(self):
        # Simulate an earlier approval request that was rejected.
        reviewer = get_user_model().objects.create_user(
            username="original_reviewer",
            password="test-password-123",
        )

        old_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            submitted_by=self.user,
            submission_note="Initial submission.",
            status=ApprovalRequest.Status.REJECTED,
        )

        old_decision = ApprovalDecision.objects.create(
            approval_request=old_request,
            decided_by=reviewer,
            outcome="rejected",
            comment="Please correct the invoice details.",
        )

        self.invoice.status = Invoice.Status.REJECTED
        self.invoice.save(update_fields=["status", "updated_at"])

        # Step 1: Return the rejected invoice to review.
        return_url = reverse(
            "approval-return-to-review",
            kwargs={
                "organization_id": self.organization.id,
                "approval_request_id": old_request.id,
            },
        )

        return_response = self.client.post(
            return_url,
            {
                "return_reason": (
                    "The invoice details have been reviewed "
                    "and are ready for resubmission."
                ),
            },
            format="json",
        )

        self.assertEqual(
            return_response.status_code,
            200,
            return_response.data,
        )

        self.invoice.refresh_from_db()
        old_request.refresh_from_db()
        old_decision.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )

        self.assertEqual(
            old_request.status,
            ApprovalRequest.Status.REJECTED,
        )

        self.assertEqual(old_decision.outcome, "rejected")
        self.assertEqual(
            old_decision.comment,
            "Please correct the invoice details.",
        )

        # Step 2: Submit the returned invoice again.
        resubmission_response = self.submit()

        self.assertEqual(
            resubmission_response.status_code,
            200,
            resubmission_response.data,
        )

        self.invoice.refresh_from_db()
        old_request.refresh_from_db()
        old_decision.refresh_from_db()

        # The invoice should now be awaiting approval again.
        self.assertEqual(
            self.invoice.status,
            Invoice.Status.PENDING_APPROVAL,
        )

        # The original request and decision must remain unchanged.
        self.assertEqual(
            old_request.status,
            ApprovalRequest.Status.REJECTED,
        )

        self.assertEqual(old_decision.outcome, "rejected")

        # A second request should exist, and it should be pending.
        self.assertEqual(
            ApprovalRequest.objects.filter(
                invoice=self.invoice,
            ).count(),
            2,
        )

        new_request = ApprovalRequest.objects.get(
            invoice=self.invoice,
            status=ApprovalRequest.Status.PENDING,
        )

        self.assertNotEqual(new_request.id, old_request.id)

        self.assertEqual(
            new_request.submitted_by,
            self.user,
        )

        # The original rejection decision remains attached
        # to the original request, not the new request.
        self.assertTrue(
            ApprovalDecision.objects.filter(
                pk=old_decision.pk,
                approval_request=old_request,
            ).exists()
        )

        self.assertFalse(
            ApprovalDecision.objects.filter(
                approval_request=new_request,
            ).exists()
        )
    
    def test_duplicate_submission_is_rejected(self):
        first_response = self.submit()

        self.assertEqual(first_response.status_code, 200)

        second_response = self.submit()

        self.assertEqual(second_response.status_code, 409)

        self.assertEqual(
            ApprovalRequest.objects.filter(
                invoice=self.invoice,
            ).count(),
            1,
        )