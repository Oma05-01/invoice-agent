from decimal import Decimal
from unittest.mock import patch, Mock
from io import BytesIO
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
from invoices.providers.groq_provider import (
    GroqInvoiceExtractionProvider,
    GroqProviderError,
    build_groq_strict_schema,
    normalize_groq_extraction,
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
    _match_supplier,
)
from invoices.services.evidence import verify_extraction_evidence
from invoices.services.review import synchronize_validation_issues


class AuthenticationAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="auth_test_user",
            email="auth@example.com",
            password="test-password-123",
            first_name="Finance",
            last_name="Operator",
        )

        self.organization = Organization.objects.create(
            name="Authentication Test Company",
            slug="authentication-test-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
            is_active=True,
        )

        self.other_organization = Organization.objects.create(
            name="Inactive Membership Company",
            slug="inactive-membership-company",
        )

        OrganizationMembership.objects.create(
            organization=self.other_organization,
            user=self.user,
            role=OrganizationMembership.Role.READ_ONLY,
            is_active=False,
        )

        self.client = APIClient(enforce_csrf_checks=True)

        self.csrf_url = reverse("auth-csrf")
        self.login_url = reverse("auth-login")
        self.logout_url = reverse("auth-logout")
        self.me_url = reverse("auth-me")

    def obtain_csrf_token(self):
        response = self.client.get(self.csrf_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrfToken", response.data)
        self.assertIn("csrftoken", self.client.cookies)

        return response.data["csrfToken"]

    def login_user(self):
        csrf_token = self.obtain_csrf_token()

        return self.client.post(
            self.login_url,
            {
                "username": "auth_test_user",
                "password": "test-password-123",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

    def test_csrf_endpoint_returns_token(self):
        response = self.client.get(self.csrf_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["csrfToken"])
        self.assertIn("csrftoken", self.client.cookies)

    def test_login_requires_csrf_token(self):
        response = self.client.post(
            self.login_url,
            {
                "username": "auth_test_user",
                "password": "test-password-123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_login_succeeds_with_valid_credentials_and_csrf(self):
        response = self.login_user()

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["message"],
            "Login successful.",
        )

        self.assertEqual(
            response.data["user"]["username"],
            "auth_test_user",
        )

        self.assertTrue(response.data["csrfToken"])

        self.assertTrue(
            self.client.cookies.get("sessionid")
        )

    def test_login_rejects_invalid_credentials(self):
        csrf_token = self.obtain_csrf_token()

        response = self.client.post(
            self.login_url,
            {
                "username": "auth_test_user",
                "password": "incorrect-password",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 400)

        self.assertFalse(
            self.client.cookies.get("sessionid")
        )

    def test_login_rejects_missing_credentials(self):
        csrf_token = self.obtain_csrf_token()

        response = self.client.post(
            self.login_url,
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 400)

    def test_current_user_requires_authentication(self):
        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 403)

    def test_current_user_returns_only_active_organizations(self):
        login_response = self.login_user()

        self.assertEqual(login_response.status_code, 200)

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, 200)

        user_data = response.data["user"]

        self.assertEqual(
            user_data["username"],
            "auth_test_user",
        )

        self.assertEqual(len(user_data["organizations"]), 1)

        organization = user_data["organizations"][0]

        self.assertEqual(
            organization["id"],
            str(self.organization.id),
        )

        self.assertEqual(
            organization["role"],
            OrganizationMembership.Role.OWNER,
        )

    def test_logout_requires_csrf_token(self):
        login_response = self.login_user()

        self.assertEqual(login_response.status_code, 200)

        response = self.client.post(
            self.logout_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_logout_ends_authenticated_session(self):
        login_response = self.login_user()

        self.assertEqual(login_response.status_code, 200)

        csrf_token = login_response.data["csrfToken"]

        logout_response = self.client.post(
            self.logout_url,
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(logout_response.status_code, 200)

        current_user_response = self.client.get(self.me_url)

        self.assertEqual(
            current_user_response.status_code,
            403,
        )


class GroqStrictOutputTests(SimpleTestCase):

    def test_strict_schema_requires_every_property(self):
        original_schema = InvoiceExtractionResult.model_json_schema()

        schema = build_groq_strict_schema(original_schema)

        self.assertEqual(
            set(schema["required"]),
            set(schema["properties"]),
        )

        self.assertEqual(
            schema["properties"]["field_confidence"]["type"],
            "array",
        )

        self.assertEqual(
            schema["properties"]["field_evidence"]["type"],
            "array",
        )

        def inspect_objects(node):
            if isinstance(node, dict):

                if node.get("type") == "object" or "properties" in node:
                    properties = node.get("properties", {})

                    self.assertIs(
                        node.get("additionalProperties"),
                        False,
                    )

                    self.assertEqual(
                        set(node.get("required", [])),
                        set(properties),
                    )

                for value in node.values():
                    inspect_objects(value)

            elif isinstance(node, list):
                for item in node:
                    inspect_objects(item)

        inspect_objects(schema)

    def test_original_pydantic_schema_is_not_modified(self):
        original_schema = InvoiceExtractionResult.model_json_schema()

        original_confidence_schema = original_schema["properties"][
            "field_confidence"
        ].copy()

        build_groq_strict_schema(original_schema)

        self.assertEqual(
            original_schema["properties"]["field_confidence"],
            original_confidence_schema,
        )

    def test_normalize_confidence_and_evidence_arrays(self):
        payload = {
            "field_confidence": [
                {
                    "field": "total_amount",
                    "confidence": 0.99,
                }
            ],
            "field_evidence": [
                {
                    "field": "total_amount",
                    "evidence": [
                        {
                            "page": 1,
                            "quote": "Total (NGN): 322,500.00",
                        }
                    ],
                }
            ],
        }

        result = normalize_groq_extraction(payload)

        self.assertEqual(
            result["field_confidence"],
            {"total_amount": 0.99},
        )

        self.assertEqual(
            result["field_evidence"]["total_amount"][0]["page"],
            1,
        )

    def test_duplicate_confidence_fields_are_rejected(self):
        payload = {
            "field_confidence": [
                {"field": "total_amount", "confidence": 0.9},
                {"field": "total_amount", "confidence": 0.8},
            ],
            "field_evidence": [],
        }

        with self.assertRaises(GroqProviderError):
            normalize_groq_extraction(payload)

    def test_invalid_evidence_structure_is_rejected(self):
        payload = {
            "field_confidence": [],
            "field_evidence": "invalid",
        }

        with self.assertRaises(GroqProviderError):
            normalize_groq_extraction(payload)

    def test_provider_uses_groq_strict_structured_output(self):
        with patch(
            "invoices.providers.groq_provider.Groq"
        ) as groq_factory:

            message = Mock()
            message.content = (
                '{"field_confidence": [], "field_evidence": []}'
            )
            message.refusal = None

            choice = Mock()
            choice.message = message
            choice.finish_reason = "stop"

            groq_factory.return_value.chat.completions.create.return_value.choices = [
                choice
            ]

            provider = GroqInvoiceExtractionProvider(
                api_key="test-key",
                model="openai/gpt-oss-20b",
            )

            result = provider.extract_invoice(
                document_text="Sample invoice text.",
                instructions="Extract invoice information.",
                response_schema=InvoiceExtractionResult.model_json_schema(),
            )

            call_kwargs = (
                groq_factory.return_value
                .chat.completions.create.call_args.kwargs
            )

            response_format = call_kwargs["response_format"]

            self.assertIs(
                response_format["json_schema"]["strict"],
                True,
            )

            self.assertEqual(
                result["field_confidence"],
                {},
            )

            self.assertEqual(
                result["field_evidence"],
                {},
            )

            self.assertEqual(
                call_kwargs["max_completion_tokens"],
                4096,
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

    
    def test_comma_formatted_decimal_values_are_normalized(self):
        payload = self.valid_payload()

        payload["subtotal"] = "580,000.00"
        payload["taxes"][0]["amount"] = "43,500.00"
        payload["other_charges"] = "0.00"
        payload["total_amount"] = "623,500.00"
        payload["amount_due"] = "623,500.00"

        payload["line_items"][0].update({
            "unit_price": "25,000.00",
            "line_total": "400,000.00",
        })

        result = InvoiceExtractionResult.model_validate(payload)

        self.assertEqual(
            result.subtotal,
            Decimal("580000.00"),
        )
        self.assertEqual(
            result.taxes[0].amount,
            Decimal("43500.00"),
        )
        self.assertEqual(
            result.other_charges,
            Decimal("0.00"),
        )
        self.assertEqual(
            result.total_amount,
            Decimal("623500.00"),
        )
        self.assertEqual(
            result.amount_due,
            Decimal("623500.00"),
        )
        self.assertEqual(
            result.line_items[0].unit_price,
            Decimal("25000.00"),
        )
        self.assertEqual(
            result.line_items[0].line_total,
            Decimal("400000.00"),
        )

    def test_large_grouped_decimal_is_normalized(self):
        result = InvoiceExtractionResult.model_validate({
            "subtotal": "1,234,567.89",
        })

        self.assertEqual(
            result.subtotal,
            Decimal("1234567.89"),
        )

    def test_malformed_decimal_grouping_is_rejected(self):
        invalid_values = [
            "58,00.00",
            "12,34,567.00",
        ]

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    InvoiceExtractionResult.model_validate({
                        "subtotal": value,
                    })

    def test_malformed_nested_decimal_is_rejected(self):
        with self.assertRaises(ValidationError):
            InvoiceExtractionResult.model_validate({
                "taxes": [{
                    "name": "VAT",
                    "tax_type": "VAT",
                    "amount": "4,3,500.00",
                }],
            })

        with self.assertRaises(ValidationError):
            InvoiceExtractionResult.model_validate({
                "line_items": [{
                    "description": "Consulting",
                    "unit_price": "25,00.00",
                }],
            })

    
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

    def test_multiline_quote_accepts_interleaved_pdf_column_text(self):
        extraction = InvoiceExtractionResult.model_validate(
            {
                "field_evidence": {
                    "supplier_address": [
                        {
                            "page": 1,
                            "quote": (
                                "14 Industrial Avenue, Ikeja\n"
                                "Lagos, Nigeria"
                            ),
                        }
                    ]
                }
            }
        )

        page_texts = {
            1: (
                "14 Industrial Avenue, Ikeja\n"
                "Invoice Number: DEMO-OUTBOX-001\n"
                "Lagos, Nigeria"
            )
        }

        findings = verify_extraction_evidence(
            extraction,
            page_texts,
        )

        self.assertEqual(findings, [])


    def test_multiline_quote_rejects_excessive_intervening_text(self):
        extraction = InvoiceExtractionResult.model_validate(
            {
                "field_evidence": {
                    "supplier_address": [
                        {
                            "page": 1,
                            "quote": "First address line\nSecond address line",
                        }
                    ]
                }
            }
        )

        page_texts = {
            1: (
                "First address line\n"
                "Unrelated line one\n"
                "Unrelated line two\n"
                "Unrelated line three\n"
                "Second address line"
            )
        }

        findings = verify_extraction_evidence(
            extraction,
            page_texts,
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(
            findings[0].code,
            "EVIDENCE_QUOTE_NOT_FOUND",
        )

    def test_non_contiguous_currency_quote_is_rejected(self):
        extraction = InvoiceExtractionResult.model_validate({
            "currency": "NGN",
            "field_evidence": {
                "currency": [{
                    "page": 1,
                    "quote": "UNIT PRICE (NGN)",
                }]
            },
        })

        page_texts = {
            1: (
                "UNIT PRICE        LINE TOTAL\n"
                " (NGN)             (NGN)"
            )
        }

        findings = verify_extraction_evidence(
            extraction,
            page_texts,
        )

        self.assertIn(
            "EVIDENCE_QUOTE_NOT_FOUND",
            {finding.code for finding in findings},
        )

    def test_exact_currency_marker_is_accepted(self):
        extraction = InvoiceExtractionResult.model_validate({
            "currency": "NGN",
            "field_evidence": {
                "currency": [{
                    "page": 1,
                    "quote": "(NGN)",
                }]
            },
        })

        page_texts = {
            1: (
                "UNIT PRICE        LINE TOTAL\n"
                " (NGN)             (NGN)"
            )
        }

        findings = verify_extraction_evidence(
            extraction,
            page_texts,
        )

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

    def make_supplier_extraction(
            self,
            supplier_name,
            supplier_tin=None,
        ):
            payload = self.valid_extraction_payload()

            payload["supplier_legal_name"] = supplier_name

            if supplier_tin is not None:
                payload["supplier_tin"] = supplier_tin

            return InvoiceExtractionResult.model_validate(payload)

    def test_unique_supplier_name_prefix_matches(self):

        cases = [
            (
                "NORTHSTAR OFFICE SUPPLIES INVOICE",
                "Northstar Office Supplies Ltd",
                "Northstar Office Supplies",
                "ordered_name_prefix",
            ),
            (
                "MERIDIAN ADVISORY",
                "Meridian Advisory Partners Ltd",
                "Meridian Advisory Partners",
                "ordered_name_prefix",
            ),
            (
                "BRIGHTPATH LOGISTICS",
                "BrightPath Logistics Services Ltd",
                "BrightPath Logistics Services",
                "ordered_name_prefix",
            ),
            (
                "CEDARLINE TECHNOLOGY",
                "Cedarline Technology Services Ltd",
                "Cedarline Technology Services",
                "ordered_name_prefix",
            ),
            (
                "GREENFIELD CATERING &",
                "Greenfield Catering & Events Ltd",
                "Greenfield Catering & Events",
                "ordered_name_prefix",
            ),
            (
                "DELTAPRINT MEDIA HOUSE",
                "DeltaPrint Media House Ltd",
                "DeltaPrint Media House",
                "exact_name",
            ),
        ]

        for (
            extracted_name,
            legal_name,
            display_name,
            expected_method,
        ) in cases:

            with self.subTest(supplier=extracted_name):

                vendor = Vendor.objects.create(
                    organization=self.organization,
                    legal_name=legal_name,
                    display_name=display_name,
                )

                extraction = self.make_supplier_extraction(
                    extracted_name
                )

                matched_vendor, findings, method = _match_supplier(
                    self.organization.id,
                    extraction,
                )

                self.assertEqual(
                    matched_vendor,
                    vendor,
                )

                self.assertEqual(
                    findings,
                    [],
                )

                self.assertEqual(
                    method,
                    expected_method,
                )

    def test_ambiguous_supplier_prefix_requires_review(self):

        Vendor.objects.create(
            organization=self.organization,
            legal_name="Meridian Advisory Partners Ltd",
            display_name="Meridian Advisory Partners",
        )

        Vendor.objects.create(
            organization=self.organization,
            legal_name="Meridian Advisory Group Ltd",
            display_name="Meridian Advisory Group",
        )

        extraction = self.make_supplier_extraction(
            "MERIDIAN ADVISORY"
        )

        vendor, findings, method = _match_supplier(
            self.organization.id,
            extraction,
        )

        self.assertIsNone(vendor)
        self.assertIsNone(method)

        self.assertIn(
            "AMBIGUOUS_VENDOR",
            [finding.code for finding in findings],
        )

    def test_prefix_match_with_conflicting_tin_requires_review(self):

        Vendor.objects.create(
            organization=self.organization,
            legal_name="Meridian Advisory Partners Ltd",
            display_name="Meridian Advisory Partners",
            tax_identification_number="TIN-REGISTERED-001",
        )

        extraction = self.make_supplier_extraction(
            "MERIDIAN ADVISORY",
            supplier_tin="TIN-EXTRACTED-999",
        )

        vendor, findings, method = _match_supplier(
            self.organization.id,
            extraction,
        )

        self.assertIsNone(vendor)
        self.assertIsNone(method)

        self.assertIn(
            "SUPPLIER_TIN_MISMATCH",
            [finding.code for finding in findings],
        )

    def test_exact_tin_match_takes_priority(self):

        vendor = Vendor.objects.create(
            organization=self.organization,
            legal_name="Registered Engineering Ltd",
            display_name="Registered Engineering",
            tax_identification_number="TIN-EXACT-001",
        )

        extraction = self.make_supplier_extraction(
            "Different Extracted Company",
            supplier_tin="TIN-EXACT-001",
        )

        matched_vendor, findings, method = _match_supplier(
            self.organization.id,
            extraction,
        )

        self.assertEqual(
            matched_vendor,
            vendor,
        )

        self.assertEqual(
            method,
            "exact_tin",
        )

        self.assertIn(
            "SUPPLIER_NAME_MISMATCH",
            [finding.code for finding in findings],
        )

    def test_ordered_name_prefix_match_creates_audit_event(self):

        # Change the registered vendor name so the extracted name
        # will no longer match it exactly.
        self.vendor.legal_name = "ABC Engineering Services Ltd"
        self.vendor.display_name = "ABC Engineering Services"

        self.vendor.save(
            update_fields=[
                "legal_name",
                "display_name",
            ]
        )

        # The PDF and extraction payload still contain
        # "ABC Engineering Ltd".
        payload = self.valid_extraction_payload()

        service = FakeExtractionService(payload)

        invoice = process_invoice(
            self.invoice.id,
            extraction_service=service,
        )

        invoice.refresh_from_db()

        # Confirm the correct vendor was assigned.
        self.assertEqual(
            invoice.vendor,
            self.vendor,
        )

        # Retrieve field-update audit events.
        audit_events = InvoiceAuditEvent.objects.filter(
            invoice=invoice,
            action=InvoiceAuditEvent.Action.FIELD_UPDATED,
        )

        vendor_events = [
            event
            for event in audit_events
            if (
                event.metadata.get("operation")
                == "deterministic_vendor_matching"
            )
        ]

        self.assertEqual(
            len(vendor_events),
            1,
        )

        event = vendor_events[0]

        # Verify the recorded matching method.
        self.assertEqual(
            event.metadata["method"],
            "ordered_name_prefix",
        )

        # Verify the extracted supplier name.
        self.assertEqual(
            event.metadata["extracted_supplier_name"],
            "ABC Engineering Ltd",
        )

        # Verify the matched vendor ID.
        self.assertEqual(
            event.metadata["matched_vendor_id"],
            str(self.vendor.pk),
        )

        # Verify the before-and-after vendor assignment.
        self.assertIsNone(
            event.changes["vendor"]["before"],
        )

        self.assertEqual(
            event.changes["vendor"]["after"],
            "ABC Engineering Services Ltd",
        )

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



class InvoiceListAPITests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="list_operator",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Invoice List Company",
            slug="invoice-list-company",
        )

        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )

        self.other_organization = Organization.objects.create(
            name="Another Company",
            slug="another-invoice-company",
        )

        self.vendor = Vendor.objects.create(
            organization=self.organization,
            legal_name="ABC Engineering Limited",
            display_name="ABC Engineering",
            is_active=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.list_url = reverse(
            "invoice-list",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

    def create_invoice(
        self,
        invoice_number,
        *,
        organization=None,
        vendor=None,
        invoice_date=None,
        status=None,
    ):
        return Invoice.objects.create(
            organization=organization or self.organization,
            vendor=vendor,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            currency="NGN",
            total_amount=Decimal("1000.00"),
            status=status or Invoice.Status.UPLOADED,
        )

    def test_active_member_can_list_organization_invoices(self):
        invoice = self.create_invoice("INV-001")

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        result = response.data["results"][0]

        self.assertEqual(result["id"], str(invoice.id))
        self.assertEqual(result["invoice_number"], "INV-001")
        self.assertEqual(
            result["vendor"],
            None,
        )
        self.assertEqual(result["currency"], "NGN")
        self.assertEqual(result["total_amount"], "1000.00")

    def test_read_only_member_can_list_invoices(self):
        self.membership.role = OrganizationMembership.Role.READ_ONLY
        self.membership.save()

        self.create_invoice("INV-READ-001")

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_inactive_member_cannot_list_invoices(self):
        self.membership.is_active = False
        self.membership.save()

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 404)

    def test_foreign_organization_invoices_are_not_returned(self):
        own_invoice = self.create_invoice("OWN-001")

        foreign_invoice = self.create_invoice(
            "FOREIGN-001",
            organization=self.other_organization,
        )

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        returned_ids = {
            item["id"]
            for item in response.data["results"]
        }

        self.assertIn(str(own_invoice.id), returned_ids)
        self.assertNotIn(str(foreign_invoice.id), returned_ids)

    def test_member_cannot_access_another_organization_list(self):
        foreign_url = reverse(
            "invoice-list",
            kwargs={
                "organization_id": self.other_organization.id,
            },
        )

        response = self.client.get(foreign_url)

        self.assertEqual(response.status_code, 404)

    def test_search_matches_invoice_number_and_vendor_names(self):
        invoice = self.create_invoice(
            "ACME-001",
            vendor=self.vendor,
        )

        self.create_invoice("OTHER-001")

        search_queries = [
            "ACME-001",
            "ABC Engineering",
            "ABC Engineering Limited",
            "abc engineering",
        ]

        for query in search_queries:
            with self.subTest(search=query):
                response = self.client.get(
                    self.list_url,
                    {"search": query},
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["count"], 1)

                self.assertEqual(
                    response.data["results"][0]["id"],
                    str(invoice.id),
                )

    def test_status_filter_returns_matching_invoices(self):
        self.create_invoice(
            "REVIEW-001",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        self.create_invoice(
            "APPROVED-001",
            status=Invoice.Status.APPROVED,
        )

        response = self.client.get(
            self.list_url,
            {"status": Invoice.Status.NEEDS_REVIEW},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        self.assertEqual(
            response.data["results"][0]["status"],
            Invoice.Status.NEEDS_REVIEW,
        )

    def test_invalid_status_filter_returns_400(self):
        response = self.client.get(
            self.list_url,
            {"status": "not_a_real_status"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("status", response.data)

    def test_invoice_date_range_filter(self):
        self.create_invoice(
            "NOV-001",
            invoice_date="2026-11-01",
        )

        self.create_invoice(
            "NOV-002",
            invoice_date="2026-11-15",
        )

        self.create_invoice(
            "DEC-001",
            invoice_date="2026-12-01",
        )

        response = self.client.get(
            self.list_url,
            {
                "invoice_date_from": "2026-11-01",
                "invoice_date_to": "2026-11-30",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)

        returned_numbers = {
            item["invoice_number"]
            for item in response.data["results"]
        }

        self.assertEqual(
            returned_numbers,
            {"NOV-001", "NOV-002"},
        )

    def test_invalid_invoice_date_returns_400(self):
        response = self.client.get(
            self.list_url,
            {"invoice_date_from": "not-a-date"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("invoice_date_from", response.data)

    def test_start_date_after_end_date_returns_400(self):
        response = self.client.get(
            self.list_url,
            {
                "invoice_date_from": "2026-11-30",
                "invoice_date_to": "2026-11-01",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_search_status_and_date_filters_can_be_combined(self):
        matching_invoice = self.create_invoice(
            "ABC-NOV-001",
            vendor=self.vendor,
            invoice_date="2026-11-15",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        self.create_invoice(
            "ABC-DEC-001",
            vendor=self.vendor,
            invoice_date="2026-12-01",
            status=Invoice.Status.NEEDS_REVIEW,
        )

        self.create_invoice(
            "ABC-NOV-002",
            vendor=self.vendor,
            invoice_date="2026-11-15",
            status=Invoice.Status.APPROVED,
        )

        response = self.client.get(
            self.list_url,
            {
                "search": "ABC",
                "status": Invoice.Status.NEEDS_REVIEW,
                "invoice_date_from": "2026-11-01",
                "invoice_date_to": "2026-11-30",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        self.assertEqual(
            response.data["results"][0]["id"],
            str(matching_invoice.id),
        )

    def test_default_pagination_returns_twenty_invoices(self):
        for number in range(23):
            self.create_invoice(
                f"PAGINATION-{number:03d}"
            )

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 23)
        self.assertEqual(len(response.data["results"]), 20)

        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

        second_page = self.client.get(
            self.list_url,
            {"page": 2},
        )

        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data["results"]), 3)

        self.assertIsNone(second_page.data["next"])
        self.assertIsNotNone(second_page.data["previous"])

    def test_custom_page_size_is_supported(self):
        for number in range(5):
            self.create_invoice(f"CUSTOM-PAGE-{number:03d}")

        response = self.client.get(
            self.list_url,
            {"page_size": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertIsNotNone(response.data["next"])

    def test_invoice_without_vendor_is_included(self):
        invoice = self.create_invoice("UNASSIGNED-001")

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)

        result = next(
            item
            for item in response.data["results"]
            if item["id"] == str(invoice.id)
        )

        self.assertIsNone(result["vendor"])



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

    def test_duplicate_vendor_invoice_number_returns_conflict(self):
        existing_invoice = Invoice.objects.create(
            organization=self.organization,
            vendor=self.vendor,
            invoice_number=self.invoice.invoice_number,
            status=Invoice.Status.PENDING_APPROVAL,
        )

        response = self.assign_vendor()

        self.assertEqual(response.status_code, 409)

        self.assertEqual(
            response.data["code"],
            "DUPLICATE_VENDOR_INVOICE_NUMBER",
        )

        self.assertEqual(
            response.data["conflicting_invoice_id"],
            str(existing_invoice.id),
        )

        self.invoice.refresh_from_db()
        self.issue.refresh_from_db()

        # No partial assignment or validation resolution.
        self.assertIsNone(self.invoice.vendor_id)

        self.assertEqual(
            self.issue.status,
            InvoiceValidationIssue.Status.OPEN,
        )

        self.assertFalse(
            InvoiceAuditEvent.objects.filter(
                invoice=self.invoice,
                action=InvoiceAuditEvent.Action.VENDOR_ASSIGNED,
            ).exists()
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

    def test_submission_resolves_stale_evidence_issue_when_quote_matches_pdf(self):
        quote = (
            "14 Industrial Avenue, Ikeja\n"
            "Lagos, Nigeria"
        )

        page_text = (
            "14 Industrial Avenue, Ikeja\n"
            "Invoice Number: SUBMIT-001\n"
            "Lagos, Nigeria"
        )

        self.invoice.extracted_data = {
            **self.invoice.extracted_data,
            "field_evidence": {
                "supplier_address": [
                    {"page": 1, "quote": quote}
                ],
            },
        }
        self.invoice.save(update_fields=["extracted_data", "updated_at"])

        issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="EVIDENCE_QUOTE_NOT_FOUND",
            severity=InvoiceValidationIssue.Severity.WARNING,
            field_name="supplier_address",
            message="The supplied quotation could not be found.",
            details={"page": 1},
            status=InvoiceValidationIssue.Status.OPEN,
        )

        with patch(
            "django.db.models.fields.files.FieldFile.open",
            return_value=BytesIO(b"mock-pdf"),
        ), patch(
            "invoices.services.review.extract_pdf_text",
            return_value=Mock(page_texts={1: page_text}),
        ):
            response = self.submit()

        self.assertEqual(response.status_code, 200, response.data)

        issue.refresh_from_db()
        self.invoice.refresh_from_db()

        self.assertEqual(
            issue.status,
            InvoiceValidationIssue.Status.RESOLVED,
        )
        self.assertEqual(
            issue.resolved_by,
            self.user,
        )
        self.assertEqual(
            self.invoice.status,
            Invoice.Status.PENDING_APPROVAL,
        )

    def test_invalid_supplier_address_evidence_still_blocks_submission(self):
        page_text = (
            "14 Industrial Avenue, Ikeja\n"
            "Invoice Number: SUBMIT-001\n"
            "Lagos, Nigeria"
        )

        self.invoice.extracted_data = {
            **self.invoice.extracted_data,
            "field_evidence": {
                "supplier_address": [
                    {
                        "page": 1,
                        "quote": "999 Imaginary Road\nAbuja, Nigeria",
                    }
                ],
            },
        }
        self.invoice.save(update_fields=["extracted_data", "updated_at"])

        issue = InvoiceValidationIssue.objects.create(
            invoice=self.invoice,
            code="EVIDENCE_QUOTE_NOT_FOUND",
            severity=InvoiceValidationIssue.Severity.WARNING,
            field_name="supplier_address",
            message="The supplied quotation could not be found.",
            details={"page": 1},
            status=InvoiceValidationIssue.Status.OPEN,
        )

        with patch(
            "django.db.models.fields.files.FieldFile.open",
            return_value=BytesIO(b"mock-pdf"),
        ), patch(
            "invoices.services.review.extract_pdf_text",
            return_value=Mock(page_texts={1: page_text}),
        ):
            response = self.submit()

        self.assertEqual(response.status_code, 409, response.data)

        self.assertIn(
            "EVIDENCE_QUOTE_NOT_FOUND",
            [blocker["code"] for blocker in response.data["blockers"]],
        )

        issue.refresh_from_db()
        self.invoice.refresh_from_db()

        self.assertEqual(
            issue.status,
            InvoiceValidationIssue.Status.OPEN,
        )
        self.assertEqual(
            self.invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )
        self.assertFalse(
            ApprovalRequest.objects.filter(invoice=self.invoice).exists()
        )