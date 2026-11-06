from decimal import Decimal

from django.test import SimpleTestCase

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