from decimal import Decimal
from datetime import date, timedelta
from django.utils import timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from auditlog.models import JournalAuditEvent
from accounting.models import (
    Account,
    JournalAdjustment,
    JournalEntry,
    JournalLine,
)

from accounting.services import (
    DEFAULT_CHART_OF_ACCOUNTS,
    AccountingConfigurationError,
    AccountingStateError,
    create_draft_journal_for_approved_invoice,
    initialize_chart_of_accounts,
    AccountingPermissionError,
    AccountingStateError,
    update_draft_journal_line,
    post_journal_entry,
    reverse_journal_entry,
    record_journal_audit,
    create_adjustment_journal
)

from approvals.models import ApprovalRequest, ApprovalDecision
from invoices.models import Invoice
from organizations.models import Organization, OrganizationMembership


from django.urls import reverse
from rest_framework.test import APIClient


class AccountingServiceTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.submitter = User.objects.create_user(
            username="accounting_submitter",
            password="test-password-123",
        )

        self.approver = User.objects.create_user(
            username="accounting_approver",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Accounting Test Company",
            slug="accounting-test-company",
            default_currency="NGN",
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="ACC-001",
            invoice_date=date(2026, 11, 6),
            currency="NGN",
            subtotal=Decimal("300000.00"),
            tax_amount=Decimal("22500.00"),
            total_amount=Decimal("322500.00"),
            status=Invoice.Status.APPROVED,
        )

        self.approval_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            submitted_by=self.submitter,
            submission_note="Approved for accounting.",
            status=ApprovalRequest.Status.APPROVED,
        )

        self.decision = ApprovalDecision.objects.create(
            approval_request=self.approval_request,
            decided_by=self.approver,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Verified and approved.",
        )

    def test_chart_of_accounts_initializes(self):
        accounts = initialize_chart_of_accounts(
            organization=self.organization,
        )

        self.assertEqual(
            len(accounts),
            len(DEFAULT_CHART_OF_ACCOUNTS),
        )

        self.assertEqual(
            Account.objects.filter(
                organization=self.organization,
            ).count(),
            len(accounts),
        )

        self.assertIn("2000", accounts)
        self.assertIn("5000", accounts)

    def test_chart_initialization_is_idempotent(self):
        first = initialize_chart_of_accounts(
            organization=self.organization,
        )

        second = initialize_chart_of_accounts(
            organization=self.organization,
        )

        self.assertEqual(
            set(first.keys()),
            set(second.keys()),
        )

        self.assertEqual(
            Account.objects.filter(
                organization=self.organization,
            ).count(),
            len(first),
        )

        for code in first:
            self.assertEqual(first[code].id, second[code].id)

    def test_chart_accounts_are_organization_scoped(self):
        another_organization = Organization.objects.create(
            name="Another Accounting Company",
            slug="another-accounting-company",
        )

        first = initialize_chart_of_accounts(
            organization=self.organization,
        )

        second = initialize_chart_of_accounts(
            organization=another_organization,
        )

        self.assertNotEqual(
            first["5000"].id,
            second["5000"].id,
        )

        self.assertNotEqual(
            first["5000"].organization_id,
            second["5000"].organization_id,
        )

    def test_existing_account_with_wrong_type_is_rejected(self):
        Account.objects.create(
            organization=self.organization,
            code="5000",
            name="Incorrect Classification",
            account_type=Account.AccountType.ASSET,
        )

        with self.assertRaises(AccountingConfigurationError):
            initialize_chart_of_accounts(
                organization=self.organization,
            )

    def test_approved_invoice_generates_balanced_draft_journal(self):
        entry, created = create_draft_journal_for_approved_invoice(
            invoice=self.invoice,
            approval_decision=self.decision,
            actor=self.approver,
        )

        self.assertTrue(created)

        self.assertEqual(
            entry.status,
            JournalEntry.Status.DRAFT,
        )

        self.assertEqual(
            entry.source_invoice_id,
            self.invoice.id,
        )

        self.assertEqual(
            entry.approval_decision_id,
            self.decision.id,
        )

        self.assertEqual(
            entry.created_by,
            self.approver,
        )

        self.assertEqual(entry.currency, "NGN")
        self.assertEqual(entry.entry_date, date(2026, 11, 6))

        lines = list(entry.lines.select_related("account"))

        self.assertEqual(len(lines), 2)

        total_debit = sum(
            (line.debit for line in lines),
            Decimal("0.00"),
        )

        total_credit = sum(
            (line.credit for line in lines),
            Decimal("0.00"),
        )

        self.assertEqual(total_debit, Decimal("322500.00"))
        self.assertEqual(total_credit, Decimal("322500.00"))
        self.assertEqual(total_debit, total_credit)

        self.assertEqual(
            {line.account.code for line in lines},
            {"2000", "5000"},
        )

        self.assertEqual(
            JournalEntry.objects.filter(
                source_invoice=self.invoice,
            ).count(),
            1,
        )

    def test_repeated_generation_returns_existing_journal(self):
        first_entry, first_created = (
            create_draft_journal_for_approved_invoice(
                invoice=self.invoice,
                approval_decision=self.decision,
                actor=self.approver,
            )
        )

        second_entry, second_created = (
            create_draft_journal_for_approved_invoice(
                invoice=self.invoice,
                approval_decision=self.decision,
                actor=self.approver,
            )
        )

        self.assertTrue(first_created)
        self.assertFalse(second_created)

        self.assertEqual(first_entry.id, second_entry.id)

        self.assertEqual(
            JournalLine.objects.filter(entry=first_entry).count(),
            2,
        )

    def test_unapproved_invoice_cannot_generate_journal(self):
        self.invoice.status = Invoice.Status.PENDING_APPROVAL
        self.invoice.save(update_fields=["status", "updated_at"])

        with self.assertRaises(AccountingStateError):
            create_draft_journal_for_approved_invoice(
                invoice=self.invoice,
                approval_decision=self.decision,
                actor=self.approver,
            )

        self.assertFalse(
            JournalEntry.objects.filter(
                source_invoice=self.invoice,
            ).exists()
        )

    def test_rejected_decision_cannot_generate_journal(self):
        rejected_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            submitted_by=self.submitter,
            status=ApprovalRequest.Status.REJECTED,
        )

        rejected_decision = ApprovalDecision.objects.create(
            approval_request=rejected_request,
            decided_by=self.approver,
            outcome=ApprovalDecision.Outcome.REJECTED,
            comment="Rejected.",
        )

        with self.assertRaises(AccountingStateError):
            create_draft_journal_for_approved_invoice(
                invoice=self.invoice,
                approval_decision=rejected_decision,
                actor=self.approver,
            )

    def test_non_positive_invoice_total_is_rejected(self):
        self.invoice.total_amount = Decimal("0.00")
        self.invoice.save(
            update_fields=["total_amount", "updated_at"],
        )

        with self.assertRaises(AccountingStateError):
            create_draft_journal_for_approved_invoice(
                invoice=self.invoice,
                approval_decision=self.decision,
                actor=self.approver,
            )

        self.assertFalse(
            JournalEntry.objects.filter(
                source_invoice=self.invoice,
            ).exists()
        )

    def test_inactive_organization_cannot_initialize_chart(self):
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])

        with self.assertRaises(AccountingStateError):
            initialize_chart_of_accounts(
                organization=self.organization,
            )

class AccountingJournalLifecycleTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.operator = User.objects.create_user(
            username="journal_operator",
            password="test-password-123",
        )

        self.admin = User.objects.create_user(
            username="journal_admin",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Journal Lifecycle Company",
            slug="journal-lifecycle-company",
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

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="LIFECYCLE-001",
            invoice_date=date(2026, 11, 6),
            currency="NGN",
            subtotal=Decimal("250000.00"),
            total_amount=Decimal("250000.00"),
            status=Invoice.Status.APPROVED,
        )

        self.approval_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            submitted_by=self.operator,
            status=ApprovalRequest.Status.APPROVED,
        )

        self.decision = ApprovalDecision.objects.create(
            approval_request=self.approval_request,
            decided_by=self.admin,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Approved.",
        )

        self.accounts = initialize_chart_of_accounts(
            organization=self.organization,
        )

    def create_draft(self):
        entry, created = create_draft_journal_for_approved_invoice(
            invoice=self.invoice,
            approval_decision=self.decision,
            actor=self.admin,
        )

        self.assertTrue(created)
        return entry

    def post_entry(self, entry):
        return post_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            actor=self.admin,
        )

    def test_finance_operator_can_classify_draft_line(self):
        entry = self.create_draft()

        line = entry.lines.get(line_number=1)
        expense_account = self.accounts["5100"]

        updated_line = update_draft_journal_line(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            journal_line_id=line.id,
            actor=self.operator,
            corrections={
                "account_id": expense_account.id,
                "description": "Professional services expense",
            },
            correction_reason="Verified against the supplier invoice.",
        )

        self.assertEqual(
            updated_line.account_id,
            expense_account.id,
        )

        self.assertEqual(
            updated_line.description,
            "Professional services expense",
        )

        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.Status.DRAFT)

    def test_read_only_member_cannot_edit_draft(self):
        entry = self.create_draft()

        readonly_user = get_user_model().objects.create_user(
            username="journal_readonly",
            password="test-password-123",
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=readonly_user,
            role=OrganizationMembership.Role.READ_ONLY,
        )

        line = entry.lines.get(line_number=1)

        with self.assertRaises(AccountingPermissionError):
            update_draft_journal_line(
                organization_id=self.organization.id,
                journal_entry_id=entry.id,
                journal_line_id=line.id,
                actor=readonly_user,
                corrections={"description": "Unauthorized change"},
                correction_reason="Test.",
            )

    def test_finance_operator_cannot_post_journal(self):
        entry = self.create_draft()

        with self.assertRaises(AccountingPermissionError):
            post_journal_entry(
                organization_id=self.organization.id,
                journal_entry_id=entry.id,
                actor=self.operator,
            )

        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.Status.DRAFT)

    def test_finance_admin_can_post_balanced_journal(self):
        entry = self.create_draft()

        posted = self.post_entry(entry)

        self.assertEqual(
            posted.status,
            JournalEntry.Status.POSTED,
        )

        self.assertEqual(posted.posted_by, self.admin)
        self.assertIsNotNone(posted.posted_at)

        lines = list(posted.lines.all())

        total_debit = sum(
            (line.debit for line in lines),
            Decimal("0.00"),
        )

        total_credit = sum(
            (line.credit for line in lines),
            Decimal("0.00"),
        )

        self.assertEqual(total_debit, Decimal("250000.00"))
        self.assertEqual(total_credit, Decimal("250000.00"))

    def test_unbalanced_journal_cannot_be_posted(self):
        entry = self.create_draft()

        expense_line = entry.lines.get(line_number=1)
        expense_line.debit = Decimal("200000.00")
        expense_line.save(update_fields=["debit", "updated_at"])

        with self.assertRaises(AccountingStateError):
            self.post_entry(entry)

        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.Status.DRAFT)

    def test_journal_without_account_assignment_cannot_be_posted(self):
        entry = self.create_draft()

        expense_line = entry.lines.get(line_number=1)
        expense_line.account = None
        expense_line.save(update_fields=["account", "updated_at"])

        with self.assertRaises(AccountingStateError):
            self.post_entry(entry)

        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.Status.DRAFT)

    def test_inactive_account_cannot_be_posted(self):
        entry = self.create_draft()

        expense_line = entry.lines.get(line_number=1)
        expense_line.account.is_active = False
        expense_line.account.save(update_fields=["is_active"])

        with self.assertRaises(AccountingStateError):
            self.post_entry(entry)

        entry.refresh_from_db()
        self.assertEqual(entry.status, JournalEntry.Status.DRAFT)

    def test_posted_journal_cannot_be_edited(self):
        entry = self.create_draft()
        self.post_entry(entry)

        line = entry.lines.get(line_number=1)

        with self.assertRaises(AccountingStateError):
            update_draft_journal_line(
                organization_id=self.organization.id,
                journal_entry_id=entry.id,
                journal_line_id=line.id,
                actor=self.admin,
                corrections={"description": "Attempted change"},
                correction_reason="Testing immutability.",
            )

    def test_finance_admin_can_reverse_posted_journal(self):
        entry = self.create_draft()
        self.post_entry(entry)

        reversal = reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            actor=self.admin,
            reversal_reason="Correction of the original journal.",
        )

        entry.refresh_from_db()

        self.assertEqual(
            entry.status,
            JournalEntry.Status.REVERSED,
        )

        self.assertEqual(
            reversal.status,
            JournalEntry.Status.POSTED,
        )

        self.assertEqual(reversal.reversal_of_id, entry.id)
        self.assertEqual(reversal.reversal_reason, "Correction of the original journal.")

        original_lines = list(entry.lines.order_by("line_number"))
        reversal_lines = list(reversal.lines.order_by("line_number"))

        self.assertEqual(len(original_lines), len(reversal_lines))

        for original_line, reversal_line in zip(
            original_lines,
            reversal_lines,
        ):
            self.assertEqual(
                reversal_line.debit,
                original_line.credit,
            )
            self.assertEqual(
                reversal_line.credit,
                original_line.debit,
            )
            self.assertEqual(
                reversal_line.account_id,
                original_line.account_id,
            )

    def test_unposted_journal_cannot_be_reversed(self):
        entry = self.create_draft()

        with self.assertRaises(AccountingStateError):
            reverse_journal_entry(
                organization_id=self.organization.id,
                journal_entry_id=entry.id,
                actor=self.admin,
                reversal_reason="Attempted reversal.",
            )

    def test_journal_cannot_be_reversed_twice(self):
        entry = self.create_draft()
        self.post_entry(entry)

        reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            actor=self.admin,
            reversal_reason="First reversal.",
        )

        with self.assertRaises(AccountingStateError):
            reverse_journal_entry(
                organization_id=self.organization.id,
                journal_entry_id=entry.id,
                actor=self.admin,
                reversal_reason="Second reversal attempt.",
            )

        self.assertEqual(
            JournalEntry.objects.filter(
                reversal_of=entry,
            ).count(),
            1,
        )

    def test_invoice_draft_creation_records_journal_audit(self):
        entry = self.create_draft()

        event = JournalAuditEvent.objects.get(
            journal_entry=entry,
            operation="journal_draft_created",
        )

        self.assertEqual(event.actor, self.admin)
        self.assertEqual(
            event.changes["journal_status"]["after"],
            JournalEntry.Status.DRAFT,
        )
        self.assertEqual(
            event.metadata["source_invoice_id"],
            str(self.invoice.id),
        )
        self.assertEqual(event.metadata["line_count"], 2)

    def test_posting_records_journal_audit(self):
        entry = self.create_draft()
        self.post_entry(entry)

        event = JournalAuditEvent.objects.get(
            journal_entry=entry,
            operation="journal_posted",
        )

        self.assertEqual(event.actor, self.admin)
        self.assertEqual(
            event.changes["journal_status"]["before"],
            JournalEntry.Status.DRAFT,
        )
        self.assertEqual(
            event.changes["journal_status"]["after"],
            JournalEntry.Status.POSTED,
        )

    def test_reversal_records_audit_for_both_entries(self):
        entry = self.create_draft()
        self.post_entry(entry)

        reversal = reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            actor=self.admin,
            reversal_reason="Testing journal audit history.",
        )

        reversal_event = JournalAuditEvent.objects.get(
            journal_entry=reversal,
            operation="journal_reversal_created",
        )

        original_event = JournalAuditEvent.objects.get(
            journal_entry=entry,
            operation="journal_reversed",
        )

        self.assertEqual(reversal_event.actor, self.admin)
        self.assertEqual(
            reversal_event.metadata["reversal_of_id"],
            str(entry.id),
        )
        self.assertEqual(original_event.actor, self.admin)

    def test_standalone_journal_can_be_audited_without_invoice(self):
        entry = JournalEntry(
            organization=self.organization,
            entry_date=date(2026, 11, 10),
            currency="NGN",
            reference="MANUAL-AUDIT-001",
            description="Standalone journal audit test.",
            status=JournalEntry.Status.DRAFT,
            created_by=self.admin,
        )

        entry.full_clean()
        entry.save(force_insert=True)

        event = record_journal_audit(
            entry=entry,
            actor=self.admin,
            operation="adjustment_draft_created",
            changes={
                "journal_status": {
                    "before": None,
                    "after": JournalEntry.Status.DRAFT,
                }
            },
            metadata={
                "adjustment_reason": "Testing standalone journal auditing.",
            },
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.journal_entry, entry)
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(
            event.metadata["adjustment_reason"],
            "Testing standalone journal auditing.",
        )

    def test_finance_operator_can_create_balanced_adjustment(self):
        original = self.create_draft()
        self.post_entry(original)

        # Simulate an original journal that has already been reversed.
        reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=original.id,
            actor=self.admin,
            reversal_reason="Testing adjustment after reversal.",
        )

        adjustment = create_adjustment_journal(
            organization_id=self.organization.id,
            original_journal_id=original.id,
            actor=self.operator,
            entry_date=date(2026, 10, 31),
            reason="Correct ClearWave expense classification.",
            description="ClearWave expense reclassification.",
            lines=[
                {
                    "account_id": self.accounts["5100"].id,
                    "debit": "752500.00",
                    "credit": "0.00",
                    "description": "Professional services expense",
                },
                {
                    "account_id": self.accounts["5000"].id,
                    "debit": "0.00",
                    "credit": "752500.00",
                    "description": "Reclassification from unclassified expense",
                },
            ],
        )

        adjustment.refresh_from_db()

        self.assertEqual(
            adjustment.status,
            JournalEntry.Status.DRAFT,
        )
        self.assertEqual(
            adjustment.entry_date,
            date(2026, 10, 31),
        )
        self.assertEqual(
            adjustment.currency,
            original.currency,
        )
        self.assertIsNone(adjustment.source_invoice_id)
        self.assertIsNone(adjustment.approval_decision_id)
        self.assertIsNone(adjustment.reversal_of_id)

        adjustment_record = JournalAdjustment.objects.get(
            adjustment_journal=adjustment,
        )

        self.assertEqual(
            adjustment_record.original_journal,
            original,
        )
        self.assertEqual(
            adjustment_record.reason,
            "Correct ClearWave expense classification.",
        )
        self.assertEqual(
            adjustment_record.created_by,
            self.operator,
        )

        debit_total = sum(
            line.debit
            for line in adjustment.lines.all()
        )
        credit_total = sum(
            line.credit
            for line in adjustment.lines.all()
        )

        self.assertEqual(debit_total, Decimal("752500.00"))
        self.assertEqual(credit_total, Decimal("752500.00"))

        self.assertTrue(
            JournalAuditEvent.objects.filter(
                journal_entry=adjustment,
                operation="adjustment_draft_created",
            ).exists()
        )

        self.assertTrue(
            JournalAuditEvent.objects.filter(
                journal_entry=original,
                operation="journal_adjustment_created",
            ).exists()
        )

    def test_unbalanced_adjustment_is_rolled_back(self):
        original = self.create_draft()
        self.post_entry(original)

        journal_count_before = JournalEntry.objects.count()

        with self.assertRaises(AccountingStateError):
            create_adjustment_journal(
                organization_id=self.organization.id,
                original_journal_id=original.id,
                actor=self.operator,
                entry_date=date(2026, 10, 31),
                reason="Test unbalanced adjustment.",
                lines=[
                    {
                        "account_id": self.accounts["5100"].id,
                        "debit": "100000.00",
                        "credit": "0.00",
                    },
                    {
                        "account_id": self.accounts["5000"].id,
                        "debit": "0.00",
                        "credit": "90000.00",
                    },
                ],
            )

        self.assertEqual(
            JournalEntry.objects.count(),
            journal_count_before,
        )

        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

    def test_adjustment_requires_posted_or_reversed_original(self):
        original = self.create_draft()

        with self.assertRaises(AccountingStateError):
            create_adjustment_journal(
                organization_id=self.organization.id,
                original_journal_id=original.id,
                actor=self.operator,
                entry_date=date(2026, 10, 31),
                reason="Attempt to adjust a draft.",
                lines=[
                    {
                        "account_id": self.accounts["5100"].id,
                        "debit": "100000.00",
                        "credit": "0.00",
                    },
                    {
                        "account_id": self.accounts["5000"].id,
                        "debit": "0.00",
                        "credit": "100000.00",
                    },
                ],
            )

        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

    def test_reversal_entry_cannot_be_adjustment_target(self):
        original = self.create_draft()
        self.post_entry(original)

        reversal = reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=original.id,
            actor=self.admin,
            reversal_reason="Testing reversal target restriction.",
        )

        with self.assertRaises(AccountingStateError):
            create_adjustment_journal(
                organization_id=self.organization.id,
                original_journal_id=reversal.id,
                actor=self.operator,
                entry_date=date(2026, 10, 31),
                reason="Attempt to adjust reversal directly.",
                lines=[
                    {
                        "account_id": self.accounts["5100"].id,
                        "debit": "100000.00",
                        "credit": "0.00",
                    },
                    {
                        "account_id": self.accounts["5000"].id,
                        "debit": "0.00",
                        "credit": "100000.00",
                    },
                ],
            )

        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

    def test_read_only_user_cannot_create_adjustment(self):
        original = self.create_draft()
        self.post_entry(original)

        readonly_user = get_user_model().objects.create_user(
            username="adjustment_readonly",
            password="test-password-123",
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=readonly_user,
            role=OrganizationMembership.Role.READ_ONLY,
        )

        with self.assertRaises(AccountingPermissionError):
            create_adjustment_journal(
                organization_id=self.organization.id,
                original_journal_id=original.id,
                actor=readonly_user,
                entry_date=date(2026, 10, 31),
                reason="Unauthorized adjustment.",
                lines=[
                    {
                        "account_id": self.accounts["5100"].id,
                        "debit": "100000.00",
                        "credit": "0.00",
                    },
                    {
                        "account_id": self.accounts["5000"].id,
                        "debit": "0.00",
                        "credit": "100000.00",
                    },
                ],
            )

        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

class AccountingAPITests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_user(
            username="accounting_api_admin",
            password="test-password-123",
        )

        self.operator = User.objects.create_user(
            username="accounting_api_operator",
            password="test-password-123",
        )

        self.readonly = User.objects.create_user(
            username="accounting_api_readonly",
            password="test-password-123",
        )

        self.outsider = User.objects.create_user(
            username="accounting_api_outsider",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Accounting API Company",
            slug="accounting-api-company",
            default_currency="NGN",
        )

        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationMembership.Role.FINANCE_ADMIN,
        )

        self.operator_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.operator,
            role=OrganizationMembership.Role.FINANCE_OPERATOR,
        )

        self.readonly_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.readonly,
            role=OrganizationMembership.Role.READ_ONLY,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="API-001",
            invoice_date=date(2026, 11, 6),
            currency="NGN",
            subtotal=Decimal("250000.00"),
            total_amount=Decimal("250000.00"),
            status=Invoice.Status.APPROVED,
        )

        self.approval_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            submitted_by=self.operator,
            status=ApprovalRequest.Status.APPROVED,
        )

        self.decision = ApprovalDecision.objects.create(
            approval_request=self.approval_request,
            decided_by=self.admin,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Approved for accounting.",
        )

        self.accounts = initialize_chart_of_accounts(
            organization=self.organization,
        )

        self.entry, created = (
            create_draft_journal_for_approved_invoice(
                invoice=self.invoice,
                approval_decision=self.decision,
                actor=self.admin,
            )
        )

        self.assertTrue(created)

        self.client = APIClient()

        self.accounts_url = reverse(
            "accounting-account-list",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        self.initialize_accounts_url = reverse(
            "accounting-account-initialize",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        self.journals_url = reverse(
            "accounting-journal-list",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        self.journal_detail_url = reverse(
            "accounting-journal-detail",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": self.entry.id,
            },
        )

        self.expense_line = self.entry.lines.get(line_number=1)

        self.expense_line_url = reverse(
            "accounting-journal-line-correction",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": self.entry.id,
                "journal_line_id": self.expense_line.id,
            },
        )

        self.post_url = reverse(
            "accounting-journal-post",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": self.entry.id,
            },
        )

        self.reverse_url = reverse(
            "accounting-journal-reverse",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": self.entry.id,
            },
        )

    def authenticate_as(self, user):
        self.client.force_authenticate(user=user)

    def test_read_only_member_can_list_accounts_and_journals(self):
        self.authenticate_as(self.readonly)

        accounts_response = self.client.get(self.accounts_url)
        journals_response = self.client.get(self.journals_url)

        self.assertEqual(accounts_response.status_code, 200)
        self.assertEqual(
            accounts_response.data["count"],
            len(DEFAULT_CHART_OF_ACCOUNTS),
        )

        self.assertEqual(journals_response.status_code, 200)
        self.assertEqual(journals_response.data["count"], 1)

        self.assertEqual(
            journals_response.data["journals"][0]["id"],
            str(self.entry.id),
        )

    def test_journal_detail_returns_nested_lines(self):
        self.authenticate_as(self.readonly)

        response = self.client.get(self.journal_detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], str(self.entry.id))
        self.assertEqual(len(response.data["lines"]), 2)

        expense_line = response.data["lines"][0]

        self.assertEqual(
            expense_line["account"]["code"],
            "5000",
        )

        self.assertEqual(
            expense_line["debit"],
            "250000.00",
        )

    def test_non_member_cannot_access_organization_accounts(self):
        self.authenticate_as(self.outsider)

        response = self.client.get(self.accounts_url)

        self.assertEqual(response.status_code, 404)

    def test_inactive_membership_cannot_access_accounting_data(self):
        self.readonly_membership.is_active = False
        self.readonly_membership.save(
            update_fields=["is_active", "updated_at"]
        )

        self.authenticate_as(self.readonly)

        response = self.client.get(self.journals_url)

        self.assertEqual(response.status_code, 404)

    
    def test_foreign_organization_journal_is_not_accessible(self):
        foreign_organization = Organization.objects.create(
            name="Foreign Accounting Company",
            slug="foreign-accounting-company",
        )

        foreign_submitter = get_user_model().objects.create_user(
            username="foreign_invoice_submitter",
            password="test-password-123",
        )

        foreign_approver = get_user_model().objects.create_user(
            username="foreign_invoice_approver",
            password="test-password-123",
        )

        OrganizationMembership.objects.create(
            organization=foreign_organization,
            user=foreign_submitter,
            role=OrganizationMembership.Role.FINANCE_OPERATOR,
        )

        OrganizationMembership.objects.create(
            organization=foreign_organization,
            user=foreign_approver,
            role=OrganizationMembership.Role.FINANCE_ADMIN,
        )

        foreign_invoice = Invoice.objects.create(
            organization=foreign_organization,
            invoice_number="FOREIGN-API-001",
            currency="NGN",
            total_amount=Decimal("100000.00"),
            status=Invoice.Status.APPROVED,
        )

        foreign_request = ApprovalRequest.objects.create(
            organization=foreign_organization,
            invoice=foreign_invoice,
            submitted_by=foreign_submitter,
            status=ApprovalRequest.Status.APPROVED,
        )

        foreign_decision = ApprovalDecision.objects.create(
            approval_request=foreign_request,
            decided_by=foreign_approver,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Foreign approval.",
        )

        foreign_entry, created = (
            create_draft_journal_for_approved_invoice(
                invoice=foreign_invoice,
                approval_decision=foreign_decision,
                actor=foreign_approver,
            )
        )

        self.assertTrue(created)

        self.authenticate_as(self.admin)

        foreign_detail_url = reverse(
            "accounting-journal-detail",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": foreign_entry.id,
            },
        )

        response = self.client.get(foreign_detail_url)

        self.assertEqual(response.status_code, 404)

    def test_finance_admin_can_initialize_chart_of_accounts(self):
        self.authenticate_as(self.admin)

        response = self.client.post(
            self.initialize_accounts_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["count"],
            len(DEFAULT_CHART_OF_ACCOUNTS),
        )

        self.assertEqual(
            Account.objects.filter(
                organization=self.organization,
            ).count(),
            len(DEFAULT_CHART_OF_ACCOUNTS),
        )

    def test_finance_operator_cannot_initialize_chart_of_accounts(self):
        self.authenticate_as(self.operator)

        response = self.client.post(
            self.initialize_accounts_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_finance_operator_can_correct_draft_journal_line(self):
        self.authenticate_as(self.operator)

        response = self.client.patch(
            self.expense_line_url,
            {
                "account_id": str(self.accounts["5100"].id),
                "description": "Professional services expense",
                "correction_reason": (
                    "Verified against the supplier invoice."
                ),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["account"]["code"],
            "5100",
        )

        self.assertEqual(
            response.data["description"],
            "Professional services expense",
        )

        self.expense_line.refresh_from_db()

        self.assertEqual(
            self.expense_line.account_id,
            self.accounts["5100"].id,
        )

    def test_read_only_member_cannot_correct_draft_journal_line(self):
        self.authenticate_as(self.readonly)

        response = self.client.patch(
            self.expense_line_url,
            {
                "description": "Unauthorized correction",
                "correction_reason": "Testing access control.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.expense_line.refresh_from_db()

        self.assertEqual(
            self.expense_line.description,
            "Unclassified supplier expense",
        )

    def test_journal_line_correction_requires_a_correction(self):
        self.authenticate_as(self.operator)

        response = self.client.patch(
            self.expense_line_url,
            {
                "correction_reason": "No actual correction supplied.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_finance_operator_cannot_post_journal(self):
        self.authenticate_as(self.operator)

        response = self.client.post(
            self.post_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.entry.refresh_from_db()

        self.assertEqual(
            self.entry.status,
            JournalEntry.Status.DRAFT,
        )

    def test_finance_admin_can_post_journal(self):
        self.authenticate_as(self.admin)

        response = self.client.post(
            self.post_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["status"],
            JournalEntry.Status.POSTED,
        )

        self.entry.refresh_from_db()

        self.assertEqual(
            self.entry.status,
            JournalEntry.Status.POSTED,
        )

        self.assertEqual(
            self.entry.posted_by,
            self.admin,
        )

    def test_unbalanced_journal_cannot_be_posted_through_api(self):
        self.expense_line.debit = Decimal("200000.00")
        self.expense_line.save(
            update_fields=["debit", "updated_at"]
        )

        self.authenticate_as(self.admin)

        response = self.client.post(
            self.post_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.entry.refresh_from_db()

        self.assertEqual(
            self.entry.status,
            JournalEntry.Status.DRAFT,
        )

    def test_finance_admin_can_reverse_posted_journal(self):
        self.authenticate_as(self.admin)

        post_response = self.client.post(
            self.post_url,
            {},
            format="json",
        )

        self.assertEqual(post_response.status_code, 200)

        reverse_response = self.client.post(
            self.reverse_url,
            {
                "reversal_reason": (
                    "Correction of the original accounting entry."
                )
            },
            format="json",
        )

        self.assertEqual(reverse_response.status_code, 201)

        self.entry.refresh_from_db()

        self.assertEqual(
            self.entry.status,
            JournalEntry.Status.REVERSED,
        )

        reversal = JournalEntry.objects.get(
            reversal_of=self.entry,
        )

        self.assertEqual(
            reversal.status,
            JournalEntry.Status.POSTED,
        )

        self.assertEqual(
            reverse_response.data["id"],
            str(reversal.id),
        )

    def test_finance_operator_cannot_reverse_journal(self):
        self.authenticate_as(self.admin)

        post_response = self.client.post(
            self.post_url,
            {},
            format="json",
        )

        self.assertEqual(post_response.status_code, 200)

        self.authenticate_as(self.operator)

        response = self.client.post(
            self.reverse_url,
            {
                "reversal_reason": "Unauthorized reversal attempt.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.entry.refresh_from_db()

        self.assertEqual(
            self.entry.status,
            JournalEntry.Status.POSTED,
        )

    def test_reversal_requires_a_reason(self):
        self.authenticate_as(self.admin)

        self.client.post(
            self.post_url,
            {},
            format="json",
        )

        response = self.client.post(
            self.reverse_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def create_posted_original_for_adjustment(self):
        post_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=self.entry.id,
            actor=self.admin,
        )

        self.entry.refresh_from_db()
        return self.entry

    def adjustment_payload(self):
        return {
            "entry_date": "2026-10-31",
            "reason": "Correct expense account classification.",
            "description": "Expense reclassification adjustment.",
            "lines": [
                {
                    "account_id": str(self.accounts["5100"].id),
                    "debit": "752500.00",
                    "credit": "0.00",
                    "description": "Professional services expense",
                },
                {
                    "account_id": str(self.accounts["5000"].id),
                    "debit": "0.00",
                    "credit": "752500.00",
                    "description": "Reclassification from unclassified expense",
                },
            ],
        }

    def adjustment_url(self, journal_id=None):
        return reverse(
            "accounting-journal-adjustment-create",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": journal_id or self.entry.id,
            },
        )

    def test_finance_operator_can_create_adjustment_through_api(self):
        original = self.create_posted_original_for_adjustment()
        self.authenticate_as(self.operator)

        response = self.client.post(
            self.adjustment_url(original.id),
            self.adjustment_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 201)

        journal_data = response.data["journal"]
        adjustment_data = response.data["adjustment"]

        adjustment = JournalEntry.objects.get(
            pk=journal_data["id"],
        )

        self.assertEqual(
            adjustment.status,
            JournalEntry.Status.DRAFT,
        )
        self.assertEqual(
            adjustment.entry_date,
            date(2026, 10, 31),
        )
        self.assertEqual(adjustment.currency, "NGN")
        self.assertIsNone(adjustment.source_invoice_id)

        record = JournalAdjustment.objects.get(
            adjustment_journal=adjustment,
        )

        self.assertEqual(record.original_journal, original)
        self.assertEqual(
            record.created_by,
            self.operator,
        )

        self.assertEqual(
            adjustment_data["original_journal_id"],
            str(original.id),
        )

        self.assertEqual(
            adjustment_data["reason"],
            "Correct expense account classification.",
        )

        self.assertEqual(
            len(journal_data["lines"]),
            2,
        )

        self.assertTrue(
            JournalAuditEvent.objects.filter(
                journal_entry=adjustment,
                operation="adjustment_draft_created",
            ).exists()
        )

    def test_read_only_member_cannot_create_adjustment_through_api(self):
        original = self.create_posted_original_for_adjustment()
        self.authenticate_as(self.readonly)

        response = self.client.post(
            self.adjustment_url(original.id),
            self.adjustment_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

    def test_unbalanced_adjustment_is_rejected_through_api(self):
        original = self.create_posted_original_for_adjustment()
        self.authenticate_as(self.operator)

        payload = self.adjustment_payload()
        payload["lines"][1]["credit"] = "700000.00"

        journal_count_before = JournalEntry.objects.count()

        response = self.client.post(
            self.adjustment_url(original.id),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            JournalEntry.objects.count(),
            journal_count_before,
        )

        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

    def test_foreign_organization_account_is_rejected_through_api(self):
        original = self.create_posted_original_for_adjustment()
        self.authenticate_as(self.operator)

        other_organization = Organization.objects.create(
            name="Other Accounting Company",
            slug="other-accounting-company",
            default_currency="NGN",
        )

        other_accounts = initialize_chart_of_accounts(
            organization=other_organization,
        )

        payload = self.adjustment_payload()

        payload["lines"][0]["account_id"] = str(
            other_accounts["5100"].id
        )

        journal_count_before = JournalEntry.objects.count()

        response = self.client.post(
            self.adjustment_url(original.id),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            JournalEntry.objects.count(),
            journal_count_before,
        )

        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

    def test_missing_original_journal_returns_404(self):
        self.authenticate_as(self.operator)

        missing_journal_id = (
            "00000000-0000-0000-0000-000000000001"
        )

        response = self.client.post(
            self.adjustment_url(missing_journal_id),
            self.adjustment_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            JournalAdjustment.objects.count(),
            0,
        )

    def test_finance_operator_can_update_draft_journal_date(self):
        self.authenticate_as(self.operator)

        url = reverse(
            "accounting-journal-date-update",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": self.entry.id,
            },
        )

        response = self.client.patch(
            url,
            {
                "entry_date": "2026-11-10",
                "correction_reason": (
                    "Correct the date of the ClearWave post-reversal "
                    "balance restoration adjustment."
                ),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.entry.refresh_from_db()

        self.assertEqual(
            self.entry.entry_date,
            date(2026, 11, 10),
        )

        self.assertTrue(
            JournalAuditEvent.objects.filter(
                journal_entry=self.entry,
                operation="journal_entry_date_updated",
            ).exists()
        )


    def test_read_only_member_cannot_update_draft_journal_date(self):
        self.authenticate_as(self.readonly)

        url = reverse(
            "accounting-journal-date-update",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": self.entry.id,
            },
        )

        response = self.client.patch(
            url,
            {
                "entry_date": "2026-11-10",
                "correction_reason": "Test permission restriction.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)


    def test_posted_journal_date_cannot_be_updated(self):
        self.authenticate_as(self.admin)

        post_response = self.client.post(self.post_url)

        self.assertEqual(post_response.status_code, 200)

        self.authenticate_as(self.operator)

        url = reverse(
            "accounting-journal-date-update",
            kwargs={
                "organization_id": self.organization.id,
                "journal_entry_id": self.entry.id,
            },
        )

        response = self.client.patch(
            url,
            {
                "entry_date": "2026-11-10",
                "correction_reason": "Test posted journal protection.",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class AccountingReportingAPITests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.operator = User.objects.create_user(
            username="reporting_operator",
            password="test-password-123",
        )

        self.admin = User.objects.create_user(
            username="reporting_admin",
            password="test-password-123",
        )

        self.viewer = User.objects.create_user(
            username="reporting_viewer",
            password="test-password-123",
        )

        self.outsider = User.objects.create_user(
            username="reporting_outsider",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Reporting Test Company",
            slug="reporting-test-company",
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

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.viewer,
            role=OrganizationMembership.Role.READ_ONLY,
        )

        self.accounts = initialize_chart_of_accounts(
            organization=self.organization,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.viewer)

        self.today = timezone.localdate()

    def create_posted_entry(
        self,
        *,
        invoice_number,
        amount,
        invoice_date=None,
        currency="NGN",
        expense_account_code="5000",
    ):
        invoice_date = invoice_date or self.today

        invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            currency=currency,
            subtotal=amount,
            total_amount=amount,
            status=Invoice.Status.APPROVED,
        )

        approval_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=invoice,
            submitted_by=self.operator,
            submission_note="Approved for reporting test.",
            status=ApprovalRequest.Status.APPROVED,
        )

        decision = ApprovalDecision.objects.create(
            approval_request=approval_request,
            decided_by=self.admin,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Approved.",
        )

        entry, created = (
            create_draft_journal_for_approved_invoice(
                invoice=invoice,
                approval_decision=decision,
                actor=self.admin,
            )
        )

        self.assertTrue(created)

        # Use a specific expense account when requested.
        if expense_account_code != "5000":
            expense_line = entry.lines.get(line_number=1)

            update_draft_journal_line(
                organization_id=self.organization.id,
                journal_entry_id=entry.id,
                journal_line_id=expense_line.id,
                actor=self.operator,
                corrections={
                    "account_id": self.accounts[
                        expense_account_code
                    ].id,
                },
                correction_reason=(
                    "Verified the expense classification."
                ),
            )

        post_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            actor=self.admin,
        )

        return entry

    def test_ledger_includes_original_and_reversal(self):
        original = self.create_posted_entry(
            invoice_number="REPORT-REV-001",
            amount=Decimal("215000.00"),
            invoice_date=self.today - timedelta(days=2),
        )

        reversal = reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=original.id,
            actor=self.admin,
            reversal_reason="Testing ledger reversal history.",
        )

        url = reverse(
            "accounting-account-ledger",
            kwargs={
                "organization_id": self.organization.id,
                "account_id": self.accounts["5000"].id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        transactions = response.data["transactions"]

        self.assertEqual(len(transactions), 2)

        transaction_by_id = {
            item["journal_entry_id"]: item
            for item in transactions
        }

        self.assertEqual(
            transaction_by_id[str(original.id)]["journal_status"],
            JournalEntry.Status.REVERSED,
        )

        self.assertEqual(
            transaction_by_id[str(reversal.id)]["journal_status"],
            JournalEntry.Status.POSTED,
        )

        self.assertEqual(
            response.data["totals_by_currency"][0]["debit"],
            "215000.00",
        )

        self.assertEqual(
            response.data["totals_by_currency"][0]["credit"],
            "215000.00",
        )

        closing = response.data["closing_balances"][0]

        self.assertEqual(closing["amount"], "0.00")
        self.assertEqual(closing["side"], "zero")

    def test_ledger_calculates_opening_balance_before_period(self):
        original = self.create_posted_entry(
            invoice_number="REPORT-OPENING-001",
            amount=Decimal("215000.00"),
            invoice_date=self.today - timedelta(days=2),
        )

        reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=original.id,
            actor=self.admin,
            reversal_reason="Testing opening balance.",
        )

        url = reverse(
            "accounting-account-ledger",
            kwargs={
                "organization_id": self.organization.id,
                "account_id": self.accounts["5000"].id,
            },
        )

        response = self.client.get(
            url,
            {"start_date": self.today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)

        # Original debit is before the period.
        opening = response.data["opening_balances"][0]

        self.assertEqual(opening["amount"], "215000.00")
        self.assertEqual(opening["side"], "debit")

        # Reversal credit falls inside the period.
        self.assertEqual(
            len(response.data["transactions"]),
            1,
        )

        closing = response.data["closing_balances"][0]

        self.assertEqual(closing["amount"], "0.00")
        self.assertEqual(closing["side"], "zero")

    def test_trial_balance_includes_reversal_history_and_separates_currencies(
        self,
    ):
        original = self.create_posted_entry(
            invoice_number="REPORT-TB-001",
            amount=Decimal("215000.00"),
            invoice_date=self.today - timedelta(days=2),
            currency="NGN",
        )

        reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=original.id,
            actor=self.admin,
            reversal_reason="Testing trial balance reversal history.",
        )

        # A remaining NGN transaction.
        self.create_posted_entry(
            invoice_number="REPORT-TB-002",
            amount=Decimal("100000.00"),
            invoice_date=self.today - timedelta(days=1),
            currency="NGN",
            expense_account_code="5100",
        )

        # A separate USD transaction.
        self.create_posted_entry(
            invoice_number="REPORT-TB-003",
            amount=Decimal("50.00"),
            invoice_date=self.today,
            currency="USD",
            expense_account_code="5100",
        )

        url = reverse(
            "accounting-trial-balance",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(
            url,
            {"as_of_date": self.today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)

        reports = {
            report["currency"]: report
            for report in response.data["currencies"]
        }

        self.assertEqual(set(reports), {"NGN", "USD"})

        # NGN balances.
        ngn = reports["NGN"]

        self.assertTrue(ngn["is_balanced"])

        self.assertEqual(
            ngn["totals"]["debit_balance"],
            "100000.00",
        )

        self.assertEqual(
            ngn["totals"]["credit_balance"],
            "100000.00",
        )

        ngn_accounts = {
            account["code"]: account
            for account in ngn["accounts"]
        }

        # Reversed 5000 activity and its reversal cancel.
        self.assertEqual(
            ngn_accounts["5000"]["debit_balance"],
            "0.00",
        )

        self.assertEqual(
            ngn_accounts["5000"]["credit_balance"],
            "0.00",
        )

        self.assertEqual(
            ngn_accounts["5100"]["debit_balance"],
            "100000.00",
        )

        self.assertEqual(
            ngn_accounts["2000"]["credit_balance"],
            "100000.00",
        )

        # USD balances are independent.
        usd = reports["USD"]

        self.assertTrue(usd["is_balanced"])

        self.assertEqual(
            usd["totals"]["debit_balance"],
            "50.00",
        )

        self.assertEqual(
            usd["totals"]["credit_balance"],
            "50.00",
        )

    def test_foreign_organization_account_ledger_is_not_accessible(self):
        foreign_organization = Organization.objects.create(
            name="Foreign Reporting Company",
            slug="foreign-reporting-company",
        )

        foreign_account = Account.objects.create(
            organization=foreign_organization,
            code="5000",
            name="Foreign Expense",
            account_type=Account.AccountType.EXPENSE,
        )

        url = reverse(
            "accounting-account-ledger",
            kwargs={
                "organization_id": self.organization.id,
                "account_id": foreign_account.id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_non_member_cannot_view_trial_balance(self):
        self.client.force_authenticate(user=self.outsider)

        url = reverse(
            "accounting-trial-balance",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_invalid_ledger_date_range_is_rejected(self):
        url = reverse(
            "accounting-account-ledger",
            kwargs={
                "organization_id": self.organization.id,
                "account_id": self.accounts["5000"].id,
            },
        )

        response = self.client.get(
            url,
            {
                "start_date": "2026-11-08",
                "end_date": "2026-11-01",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_ledger_without_start_date_does_not_double_count_activity(self):
        self.create_posted_entry(
            invoice_number="REPORT-NO-START-001",
            amount=Decimal("215000.00"),
            invoice_date=self.today - timedelta(days=2),
        )

        url = reverse(
            "accounting-account-ledger",
            kwargs={
                "organization_id": self.organization.id,
                "account_id": self.accounts["5000"].id,
            },
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["opening_balances"][0]["amount"],
            "0.00",
        )

        self.assertEqual(
            response.data["totals_by_currency"][0]["debit"],
            "215000.00",
        )

        self.assertEqual(
            response.data["closing_balances"][0]["amount"],
            "215000.00",
        )

        self.assertEqual(
            response.data["closing_balances"][0]["side"],
            "debit",
        )

class FinancialStatementsAPITests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.operator = User.objects.create_user(
            username="statements_operator",
            password="test-password-123",
        )

        self.admin = User.objects.create_user(
            username="statements_admin",
            password="test-password-123",
        )

        self.viewer = User.objects.create_user(
            username="statements_viewer",
            password="test-password-123",
        )

        self.outsider = User.objects.create_user(
            username="statements_outsider",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Financial Statements Company",
            slug="financial-statements-company",
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

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.viewer,
            role=OrganizationMembership.Role.READ_ONLY,
        )

        self.accounts = initialize_chart_of_accounts(
            organization=self.organization,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.viewer)

        self.today = timezone.localdate()

    def create_posted_expense(
        self,
        *,
        invoice_number,
        amount,
        expense_account_code="5000",
    ):
        invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number=invoice_number,
            invoice_date=self.today,
            currency="NGN",
            subtotal=amount,
            total_amount=amount,
            status=Invoice.Status.APPROVED,
        )

        approval_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=invoice,
            submitted_by=self.operator,
            submission_note="Approved for financial statement test.",
            status=ApprovalRequest.Status.APPROVED,
        )

        decision = ApprovalDecision.objects.create(
            approval_request=approval_request,
            decided_by=self.admin,
            outcome=ApprovalDecision.Outcome.APPROVED,
            comment="Approved.",
        )

        entry, created = create_draft_journal_for_approved_invoice(
            invoice=invoice,
            approval_decision=decision,
            actor=self.admin,
        )

        self.assertTrue(created)

        if expense_account_code != "5000":
            line = entry.lines.get(line_number=1)

            update_draft_journal_line(
                organization_id=self.organization.id,
                journal_entry_id=entry.id,
                journal_line_id=line.id,
                actor=self.operator,
                corrections={
                    "account_id": self.accounts[expense_account_code].id,
                },
                correction_reason="Verified expense classification.",
            )

        return post_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            actor=self.admin,
        )

    def create_revenue_journal(
        self,
        *,
        amount,
        reference,
        currency="NGN",
        entry_date=None,
    ):
        entry = JournalEntry(
            organization=self.organization,
            entry_date=entry_date or self.today,
            currency=currency,
            reference=reference,
            description="Recorded operating revenue.",
            status=JournalEntry.Status.DRAFT,
            created_by=self.admin,
        )

        entry.full_clean()
        entry.save(force_insert=True)

        lines = [
            JournalLine(
                entry=entry,
                line_number=1,
                account=self.accounts["1100"],
                description="Customer receivable",
                debit=amount,
                credit=Decimal("0.00"),
            ),
            JournalLine(
                entry=entry,
                line_number=2,
                account=self.accounts["4000"],
                description="Operating revenue",
                debit=Decimal("0.00"),
                credit=amount,
            ),
        ]

        for line in lines:
            line.full_clean()
            line.save(force_insert=True)

        post_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=entry.id,
            actor=self.admin,
        )

        return entry

    def test_income_statement_calculates_revenue_expenses_and_net_income(
        self,
    ):
        self.create_revenue_journal(
            amount=Decimal("300000.00"),
            reference="STATEMENT-REV-001",
        )

        self.create_posted_expense(
            invoice_number="STATEMENT-EXP-001",
            amount=Decimal("215000.00"),
            expense_account_code="5100",
        )

        url = reverse(
            "accounting-income-statement",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(
            url,
            {
                "start_date": self.today.isoformat(),
                "end_date": self.today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)

        report = response.data["currencies"][0]

        self.assertEqual(report["currency"], "NGN")
        self.assertEqual(report["total_revenue"], "300000.00")
        self.assertEqual(report["total_expenses"], "215000.00")
        self.assertEqual(report["net_income"], "85000.00")

        self.assertEqual(
            report["revenue_accounts"][0]["code"],
            "4000",
        )

        self.assertEqual(
            report["expense_accounts"][0]["code"],
            "5100",
        )

    def test_income_statement_keeps_currencies_separate(self):
        self.create_revenue_journal(
            amount=Decimal("300000.00"),
            reference="STATEMENT-NGN-001",
            currency="NGN",
        )

        self.create_revenue_journal(
            amount=Decimal("500.00"),
            reference="STATEMENT-USD-001",
            currency="USD",
        )

        url = reverse(
            "accounting-income-statement",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(
            url,
            {
                "start_date": self.today.isoformat(),
                "end_date": self.today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)

        reports = {
            item["currency"]: item
            for item in response.data["currencies"]
        }

        self.assertEqual(set(reports), {"NGN", "USD"})

        self.assertEqual(
            reports["NGN"]["net_income"],
            "300000.00",
        )

        self.assertEqual(
            reports["USD"]["net_income"],
            "500.00",
        )

    def test_income_statement_includes_reversal_history(self):
        original = self.create_revenue_journal(
            amount=Decimal("300000.00"),
            reference="STATEMENT-REVERSAL-001",
        )

        reverse_journal_entry(
            organization_id=self.organization.id,
            journal_entry_id=original.id,
            actor=self.admin,
            reversal_reason="Testing income statement reversal history.",
        )

        url = reverse(
            "accounting-income-statement",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(
            url,
            {
                "start_date": self.today.isoformat(),
                "end_date": self.today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)

        report = response.data["currencies"][0]

        self.assertEqual(
            report["total_revenue"],
            "0.00",
        )

        self.assertEqual(
            report["net_income"],
            "0.00",
        )

    def test_balance_sheet_includes_cumulative_unclosed_earnings(self):
        self.create_revenue_journal(
            amount=Decimal("300000.00"),
            reference="BALANCE-SHEET-REV-001",
        )

        self.create_posted_expense(
            invoice_number="BALANCE-SHEET-EXP-001",
            amount=Decimal("215000.00"),
            expense_account_code="5100",
        )

        url = reverse(
            "accounting-balance-sheet",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(
            url,
            {"as_of_date": self.today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)

        report = response.data["currencies"][0]

        self.assertEqual(report["currency"], "NGN")

        self.assertEqual(
            report["assets"]["total"],
            "300000.00",
        )

        self.assertEqual(
            report["liabilities"]["total"],
            "215000.00",
        )

        self.assertEqual(
            report["equity"]["total"],
            "0.00",
        )

        self.assertEqual(
            report["equity"]["cumulative_unclosed_earnings"],
            "85000.00",
        )

        self.assertEqual(
            report["total_liabilities_and_equity"],
            "300000.00",
        )

        self.assertEqual(
            report["balance_difference"],
            "0.00",
        )

        self.assertTrue(report["is_balanced"])

    def test_balance_sheet_keeps_currencies_separate(self):
        self.create_revenue_journal(
            amount=Decimal("300000.00"),
            reference="BALANCE-NGN-001",
            currency="NGN",
        )

        self.create_revenue_journal(
            amount=Decimal("500.00"),
            reference="BALANCE-USD-001",
            currency="USD",
        )

        url = reverse(
            "accounting-balance-sheet",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(
            url,
            {"as_of_date": self.today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)

        reports = {
            item["currency"]: item
            for item in response.data["currencies"]
        }

        self.assertEqual(set(reports), {"NGN", "USD"})

        self.assertEqual(
            reports["NGN"]["assets"]["total"],
            "300000.00",
        )

        self.assertEqual(
            reports["USD"]["assets"]["total"],
            "500.00",
        )

        self.assertTrue(reports["NGN"]["is_balanced"])
        self.assertTrue(reports["USD"]["is_balanced"])

    def test_income_statement_requires_valid_date_range(self):
        url = reverse(
            "accounting-income-statement",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        response = self.client.get(
            url,
            {
                "start_date": self.today.isoformat(),
                "end_date": (
                    self.today - timedelta(days=5)
                ).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_non_member_cannot_view_financial_statements(self):
        self.client.force_authenticate(user=self.outsider)

        urls = [
            reverse(
                "accounting-income-statement",
                kwargs={
                    "organization_id": self.organization.id,
                },
            ),
            reverse(
                "accounting-balance-sheet",
                kwargs={
                    "organization_id": self.organization.id,
                },
            ),
        ]

        for url in urls:
            response = self.client.get(
                url,
                {
                    "start_date": self.today.isoformat(),
                    "end_date": self.today.isoformat(),
                    "as_of_date": self.today.isoformat(),
                },
            )

            self.assertEqual(response.status_code, 404)
