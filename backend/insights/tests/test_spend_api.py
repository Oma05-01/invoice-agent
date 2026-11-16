from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounting.services import (
    create_draft_journal_for_approved_invoice,
    initialize_chart_of_accounts,
    post_journal_entry,
)
from approvals.models import ApprovalDecision, ApprovalRequest
from invoices.models import Invoice
from organizations.models import Organization, OrganizationMembership
from vendors.models import Vendor


class SpendReportAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.reader = User.objects.create_user(
            username="insights_api_reader",
            password="test-password-123",
        )
        self.operator = User.objects.create_user(
            username="insights_api_operator",
            password="test-password-123",
        )
        self.admin = User.objects.create_user(
            username="insights_api_admin",
            password="test-password-123",
        )
        self.outsider = User.objects.create_user(
            username="insights_api_outsider",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Insights API Company",
            slug="insights-api-company",
            default_currency="NGN",
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.reader,
            role=OrganizationMembership.Role.READ_ONLY,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.operator,
            role=OrganizationMembership.Role.FINANCE_OPERATOR,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationMembership.Role.FINANCE_ADMIN,
        )

        initialize_chart_of_accounts(organization=self.organization)
        self.vendor = Vendor.objects.create(
            organization=self.organization,
            vendor_code="INS-API-001",
            legal_name="Insights API Vendor Ltd",
            display_name="Insights API Vendor",
            tax_identification_number="",
            email="",
            phone="",
            address="",
            is_active=True,
        )
        self.today = timezone.localdate()
        self.client = APIClient()
        self.url = reverse(
            "insights-spend",
            kwargs={"organization_id": self.organization.id},
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def create_posted_expense(
        self,
        *,
        invoice_number="INS-API-INV-001",
        amount="1250.00",
        organization=None,
        vendor=None,
        currency="NGN",
        entry_date=None,
        operator=None,
        admin=None,
    ):
        organization = organization or self.organization
        vendor = self.vendor if vendor is None else vendor
        operator = operator or self.operator
        admin = admin or self.admin
        entry_date = entry_date or self.today
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))

        invoice = Invoice.objects.create(
            organization=organization,
            vendor=vendor,
            invoice_number=invoice_number,
            invoice_date=entry_date,
            currency=currency,
            subtotal=amount,
            total_amount=amount,
            status=Invoice.Status.APPROVED,
        )
        approval_request = ApprovalRequest.objects.create(
            organization=organization,
            invoice=invoice,
            submitted_by=operator,
            submission_note="Approved for Insights API test.",
            status=ApprovalRequest.Status.APPROVED,
        )
        decision = ApprovalDecision.objects.create(
            approval_request=approval_request,
            decided_by=admin,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Approved for Insights API test.",
        )
        entry, created = create_draft_journal_for_approved_invoice(
            invoice=invoice,
            approval_decision=decision,
            actor=admin,
        )
        self.assertTrue(created)

        # The normal creation service selects the organisation's default
        # currency and current date; set test values before posting.
        from accounting.models import JournalEntry

        JournalEntry.objects.filter(pk=entry.pk).update(
            entry_date=entry_date,
            currency=currency,
        )
        return post_journal_entry(
            organization_id=organization.id,
            journal_entry_id=entry.id,
            actor=admin,
        )

    def query_params(self, **overrides):
        params = {
            "dimension": "vendor",
            "start_date": (self.today - timedelta(days=1)).isoformat(),
            "end_date": (self.today + timedelta(days=1)).isoformat(),
        }
        params.update(overrides)
        return params

    def test_read_only_member_can_retrieve_spend_report(self):
        self.create_posted_expense()
        self.authenticate_as(self.reader)

        response = self.client.get(self.url, self.query_params())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["dimension"], "vendor")
        self.assertEqual(len(response.data["currencies"]), 1)
        currency_report = response.data["currencies"][0]
        self.assertEqual(currency_report["currency"], "NGN")
        self.assertEqual(currency_report["total_expenditure"], "1250.00")
        self.assertEqual(
            currency_report["rows"][0]["vendor_name"],
            self.vendor.display_name,
        )

    def test_report_uses_membership_organization_not_request_data(self):
        self.create_posted_expense()
        self.authenticate_as(self.reader)

        response = self.client.get(
            self.url,
            self.query_params(organization_id="another-organization"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["currencies"][0]["total_expenditure"],
            "1250.00",
        )

    def test_unauthenticated_user_cannot_retrieve_report(self):
        response = self.client.get(self.url, self.query_params())
        self.assertIn(response.status_code, (401, 403))

    def test_user_without_membership_receives_not_found(self):
        self.authenticate_as(self.outsider)
        response = self.client.get(self.url, self.query_params())
        self.assertEqual(response.status_code, 404)

    def test_inactive_membership_cannot_retrieve_report(self):
        membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.reader,
        )
        membership.is_active = False
        membership.save(update_fields=["is_active"])
        self.authenticate_as(self.reader)

        response = self.client.get(self.url, self.query_params())

        self.assertEqual(response.status_code, 404)

    def test_invalid_dimension_is_rejected(self):
        self.authenticate_as(self.reader)
        response = self.client.get(
            self.url,
            self.query_params(dimension="customer"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("dimension", response.data)

    def test_invalid_date_range_is_rejected(self):
        self.authenticate_as(self.reader)
        response = self.client.get(
            self.url,
            self.query_params(
                start_date=self.today.isoformat(),
                end_date=(self.today - timedelta(days=1)).isoformat(),
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("end_date", response.data)

    def test_missing_required_dates_are_rejected(self):
        self.authenticate_as(self.reader)
        response = self.client.get(
            self.url,
            {"dimension": "vendor"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("start_date", response.data)
        self.assertIn("end_date", response.data)

    def test_invalid_currency_is_rejected(self):
        self.authenticate_as(self.reader)
        response = self.client.get(
            self.url,
            self.query_params(currency="N1G"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("currency", response.data)

    def test_limit_is_bounded(self):
        self.authenticate_as(self.reader)
        response = self.client.get(
            self.url,
            self.query_params(limit="101"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("limit", response.data)

    def test_currency_is_normalized_to_uppercase(self):
        self.authenticate_as(self.reader)
        response = self.client.get(
            self.url,
            self.query_params(currency="ngn"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["currencies"][0]["currency"], "NGN")
