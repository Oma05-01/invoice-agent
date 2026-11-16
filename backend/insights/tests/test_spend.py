from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounting.models import Account, JournalEntry
from accounting.services import (
    create_draft_journal_for_approved_invoice,
    initialize_chart_of_accounts,
    post_journal_entry,
    reverse_journal_entry,
    update_draft_journal_line,
)
from approvals.models import ApprovalDecision, ApprovalRequest
from insights.services.spend import SpendReportError, spend_by
from invoices.models import Invoice
from organizations.models import Organization, OrganizationMembership
from vendors.models import Vendor


class SpendReportServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()

        self.operator = User.objects.create_user(
            username="spend_report_operator",
            password="test-password-123",
        )
        self.admin = User.objects.create_user(
            username="spend_report_admin",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Spend Report Company",
            slug="spend-report-company",
            default_currency="NGN",
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

        self.accounts = initialize_chart_of_accounts(
            organization=self.organization,
        )
        self.today = timezone.localdate()

    def create_vendor(
        self,
        *,
        organization=None,
        vendor_code="VEND-001",
        display_name="Northstar Office Supplies",
        legal_name=None,
    ):
        organization = organization or self.organization
        legal_name = legal_name or display_name
        return Vendor.objects.create(
            organization=organization,
            vendor_code=vendor_code,
            legal_name=legal_name,
            display_name=display_name,
            tax_identification_number="",
            email="",
            phone="",
            address="",
            is_active=True,
        )

    def create_posted_expense(
        self,
        *,
        invoice_number,
        amount,
        vendor=None,
        entry_date=None,
        currency="NGN",
        expense_account_code="5000",
        organization=None,
        operator=None,
        admin=None,
        accounts=None,
        post=True,
    ):
        organization = organization or self.organization
        operator = operator or self.operator
        admin = admin or self.admin
        accounts = accounts or self.accounts
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
            submission_note="Approved for spend report test.",
            status=ApprovalRequest.Status.APPROVED,
        )
        decision = ApprovalDecision.objects.create(
            approval_request=approval_request,
            decided_by=admin,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Approved for spend report test.",
        )

        entry, created = create_draft_journal_for_approved_invoice(
            invoice=invoice,
            approval_decision=decision,
            actor=admin,
        )
        self.assertTrue(created)

        if expense_account_code != "5000":
            expense_line = entry.lines.get(
                account__account_type=Account.AccountType.EXPENSE,
            )
            update_draft_journal_line(
                organization_id=organization.id,
                journal_entry_id=entry.id,
                journal_line_id=expense_line.id,
                actor=operator,
                corrections={
                    "account_id": accounts[expense_account_code].id,
                },
                correction_reason="Verified expense classification for test.",
            )

        # Set reporting date and currency explicitly in fixture setup. The
        # journal is still draft and is posted through the accounting service.
        JournalEntry.objects.filter(pk=entry.pk).update(
            entry_date=entry_date,
            currency=currency,
        )

        if post:
            entry = post_journal_entry(
                organization_id=organization.id,
                journal_entry_id=entry.id,
                actor=admin,
            )
        else:
            entry.refresh_from_db()

        return invoice, entry

    @staticmethod
    def get_currency_report(result, currency="NGN"):
        return next(
            item for item in result["currencies"]
            if item["currency"] == currency
        )

    def test_vendor_dimension_groups_and_sums_invoices(self):
        northstar = self.create_vendor()
        brightpath = self.create_vendor(
            vendor_code="VEND-002",
            display_name="BrightPath Services",
        )
        start_date = self.today - timedelta(days=30)

        self.create_posted_expense(
            invoice_number="NS-001",
            amount="100.00",
            vendor=northstar,
        )
        self.create_posted_expense(
            invoice_number="NS-002",
            amount="50.00",
            vendor=northstar,
        )
        self.create_posted_expense(
            invoice_number="BP-001",
            amount="75.00",
            vendor=brightpath,
        )

        result = spend_by(
            self.organization,
            dimension="vendor",
            start_date=start_date,
            end_date=self.today,
        )
        report = self.get_currency_report(result)
        rows = {row["vendor_id"]: row for row in report["rows"]}

        self.assertEqual(report["total_expenditure"], "225.00")
        self.assertEqual(report["group_count"], 2)
        self.assertEqual(rows[str(northstar.id)]["vendor_name"], northstar.display_name)
        self.assertEqual(rows[str(northstar.id)]["amount"], "150.00")
        self.assertEqual(rows[str(brightpath.id)]["amount"], "75.00")

    def test_account_dimension_groups_expense_accounts(self):
        vendor = self.create_vendor()
        self.create_posted_expense(
            invoice_number="ACC-001",
            amount="1200.00",
            vendor=vendor,
            expense_account_code="5000",
        )
        self.create_posted_expense(
            invoice_number="ACC-002",
            amount="800.00",
            vendor=vendor,
            expense_account_code="5200",
        )

        result = spend_by(
            self.organization,
            dimension="account",
            start_date=self.today - timedelta(days=1),
            end_date=self.today,
        )
        report = self.get_currency_report(result)
        rows = {row["account_code"]: row for row in report["rows"]}

        self.assertEqual(report["total_expenditure"], "2000.00")
        self.assertEqual(rows["5000"]["amount"], "1200.00")
        self.assertEqual(rows["5200"]["amount"], "800.00")

    def test_month_dimension_groups_by_journal_entry_month(self):
        vendor = self.create_vendor()
        september = date(2026, 9, 15)
        october = date(2026, 10, 12)

        self.create_posted_expense(
            invoice_number="MONTH-001",
            amount="250.00",
            vendor=vendor,
            entry_date=september,
        )
        self.create_posted_expense(
            invoice_number="MONTH-002",
            amount="400.00",
            vendor=vendor,
            entry_date=october,
        )

        result = spend_by(
            self.organization,
            dimension="month",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 10, 31),
        )
        report = self.get_currency_report(result)

        self.assertEqual(
            [row["month"] for row in report["rows"]],
            ["2026-09-01", "2026-10-01"],
        )
        self.assertEqual(
            [row["amount"] for row in report["rows"]],
            ["250.00", "400.00"],
        )
        self.assertEqual(report["total_expenditure"], "650.00")

    def test_currencies_are_reported_separately(self):
        vendor = self.create_vendor()
        self.create_posted_expense(
            invoice_number="FX-001",
            amount="1000.00",
            vendor=vendor,
            currency="NGN",
        )
        self.create_posted_expense(
            invoice_number="FX-002",
            amount="500.00",
            vendor=vendor,
            currency="USD",
        )

        result = spend_by(
            self.organization,
            dimension="vendor",
            start_date=self.today - timedelta(days=1),
            end_date=self.today,
        )

        self.assertEqual(
            [item["currency"] for item in result["currencies"]],
            ["NGN", "USD"],
        )
        self.assertEqual(
            self.get_currency_report(result, "NGN")["total_expenditure"],
            "1000.00",
        )
        self.assertEqual(
            self.get_currency_report(result, "USD")["total_expenditure"],
            "500.00",
        )

    def test_reversal_is_attributed_to_original_vendor_and_its_own_period(self):
        vendor = self.create_vendor()
        original_date = self.today - timedelta(days=10)
        _invoice, original_entry = self.create_posted_expense(
            invoice_number="REV-001",
            amount="900.00",
            vendor=vendor,
            entry_date=original_date,
        )

        reversal = reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=original_entry.id,
            actor=self.admin,
            reversal_reason="Spend report reversal attribution test.",
        )

        original_period = spend_by(
            self.organization,
            dimension="vendor",
            start_date=original_date,
            end_date=original_date,
        )
        original_report = self.get_currency_report(original_period)
        self.assertEqual(original_report["total_expenditure"], "900.00")
        self.assertEqual(
            original_report["rows"][0]["vendor_id"],
            str(vendor.id),
        )

        reversal_period = spend_by(
            self.organization,
            dimension="vendor",
            start_date=reversal.entry_date,
            end_date=reversal.entry_date,
        )
        reversal_report = self.get_currency_report(reversal_period)

        self.assertEqual(reversal_report["total_expenditure"], "-900.00")
        self.assertEqual(reversal_report["rows"][0]["vendor_id"], str(vendor.id))
        self.assertEqual(
            reversal_report["rows"][0]["vendor_name"],
            vendor.display_name,
        )
        self.assertEqual(reversal_report["rows"][0]["amount"], "-900.00")

    def test_draft_journals_are_excluded(self):
        vendor = self.create_vendor()
        self.create_posted_expense(
            invoice_number="DRAFT-001",
            amount="700.00",
            vendor=vendor,
            post=False,
        )

        result = spend_by(
            self.organization,
            dimension="vendor",
            start_date=self.today - timedelta(days=1),
            end_date=self.today,
        )
        report = self.get_currency_report(result)

        self.assertEqual(report["rows"], [])
        self.assertEqual(report["total_expenditure"], "0.00")
        self.assertEqual(report["group_count"], 0)

    def test_foreign_organization_expenditure_is_not_included(self):
        own_vendor = self.create_vendor()
        self.create_posted_expense(
            invoice_number="OWN-001",
            amount="100.00",
            vendor=own_vendor,
        )

        User = get_user_model()
        foreign_operator = User.objects.create_user(
            username="foreign_spend_operator",
            password="test-password-123",
        )
        foreign_admin = User.objects.create_user(
            username="foreign_spend_admin",
            password="test-password-123",
        )
        foreign_organization = Organization.objects.create(
            name="Other Spend Company",
            slug="other-spend-company",
            default_currency="USD",
        )
        OrganizationMembership.objects.create(
            organization=foreign_organization,
            user=foreign_operator,
            role=OrganizationMembership.Role.FINANCE_OPERATOR,
        )
        OrganizationMembership.objects.create(
            organization=foreign_organization,
            user=foreign_admin,
            role=OrganizationMembership.Role.FINANCE_ADMIN,
        )
        foreign_accounts = initialize_chart_of_accounts(
            organization=foreign_organization,
        )
        foreign_vendor = self.create_vendor(
            organization=foreign_organization,
            vendor_code="OTHER-001",
            display_name="Other Organisation Vendor",
        )
        self.create_posted_expense(
            invoice_number="OTHER-001",
            amount="9999.00",
            vendor=foreign_vendor,
            organization=foreign_organization,
            operator=foreign_operator,
            admin=foreign_admin,
            accounts=foreign_accounts,
            currency="USD",
        )

        result = spend_by(
            self.organization,
            dimension="vendor",
            start_date=self.today - timedelta(days=1),
            end_date=self.today,
        )

        self.assertEqual(
            [item["currency"] for item in result["currencies"]],
            ["NGN"],
        )
        report = self.get_currency_report(result)
        self.assertEqual(report["total_expenditure"], "100.00")
        self.assertEqual(report["group_count"], 1)
        self.assertEqual(report["rows"][0]["vendor_name"], own_vendor.display_name)

    def test_null_vendor_is_grouped_as_unattributed(self):
        self.create_posted_expense(
            invoice_number="NO-VENDOR-001",
            amount="325.00",
            vendor=None,
        )

        result = spend_by(
            self.organization,
            dimension="vendor",
            start_date=self.today - timedelta(days=1),
            end_date=self.today,
        )
        report = self.get_currency_report(result)

        self.assertEqual(report["rows"][0]["vendor_id"], None)
        self.assertEqual(report["rows"][0]["vendor_name"], "Unattributed")
        self.assertEqual(report["rows"][0]["amount"], "325.00")

    def test_invalid_dimension_and_date_range_are_rejected(self):
        with self.assertRaises(SpendReportError):
            spend_by(
                self.organization,
                dimension="customer",
                start_date=self.today,
                end_date=self.today,
            )

        with self.assertRaises(SpendReportError):
            spend_by(
                self.organization,
                dimension="vendor",
                start_date=self.today,
                end_date=self.today - timedelta(days=1),
            )
