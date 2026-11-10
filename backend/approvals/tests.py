
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from accounting.models import JournalEntry, JournalLine
from rest_framework.test import APIClient
from decimal import Decimal
from approvals.models import ApprovalRequest, ApprovalDecision
from auditlog.models import InvoiceAuditEvent
from invoices.models import Invoice
from organizations.models import Organization, OrganizationMembership


class ApprovalWorkflowAPITests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.submitter = User.objects.create_user(
            username="invoice_submitter",
            password="test-password-123",
        )

        self.approver = User.objects.create_user(
            username="invoice_approver",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Approval Test Company",
            slug="approval-test-company",
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.submitter,
            role=OrganizationMembership.Role.FINANCE_OPERATOR,
        )

        self.approver_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.approver,
            role=OrganizationMembership.Role.FINANCE_REVIEWER,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="APPROVAL-001",
            currency="NGN",
            total_amount="250000.00",
            status=Invoice.Status.PENDING_APPROVAL,
        )

        self.approval_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            submitted_by=self.submitter,
            submission_note="Invoice review completed.",
            status=ApprovalRequest.Status.PENDING,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.approver)

        self.queue_url = reverse(
            "approval-queue",
            kwargs={
                "organization_id": self.organization.id,
            },
        )

        self.detail_url = reverse(
            "approval-detail",
            kwargs={
                "organization_id": self.organization.id,
                "approval_request_id": self.approval_request.id,
            },
        )

        self.approve_url = reverse(
            "approval-approve",
            kwargs={
                "organization_id": self.organization.id,
                "approval_request_id": self.approval_request.id,
            },
        )

        self.reject_url = reverse(
            "approval-reject",
            kwargs={
                "organization_id": self.organization.id,
                "approval_request_id": self.approval_request.id,
            },
        )

    def test_authorized_approver_can_view_queue(self):
        response = self.client.get(self.queue_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.approval_request.id),
        )

    def test_authorized_approver_can_view_request_details(self):
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.data["approval_request"]["id"],
            str(self.approval_request.id),
        )

        self.assertEqual(
            response.data["invoice"]["status"],
            Invoice.Status.PENDING_APPROVAL,
        )

        self.assertIsNone(response.data["decision"])

    def test_finance_operator_can_view_rejected_request_details(self):
        self.approval_request.status = ApprovalRequest.Status.REJECTED
        self.approval_request.save(update_fields=["status"])

        self.invoice.status = Invoice.Status.REJECTED
        self.invoice.save(update_fields=["status"])

        self.client.force_authenticate(user=self.submitter)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["approval_request"]["status"],
            ApprovalRequest.Status.REJECTED,
        )
        self.assertEqual(
            response.data["invoice"]["status"],
            Invoice.Status.REJECTED,
        )

    def test_finance_operator_cannot_view_pending_request_details(self):
        self.client.force_authenticate(user=self.submitter)

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 403)

    def test_finance_reviewer_can_approve_invoice(self):
        response = self.client.post(
            self.approve_url,
            {"comment": "Financial information verified."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()
        self.approval_request.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.APPROVED,
        )

        self.assertEqual(
            self.approval_request.status,
            ApprovalRequest.Status.APPROVED,
        )

        decision = ApprovalDecision.objects.get(
            approval_request=self.approval_request,
        )

        self.assertEqual(
            decision.decided_by,
            self.approver,
        )

        self.assertEqual(
            decision.outcome,
            ApprovalDecision.Outcome.APPROVED,
        )

        journal = JournalEntry.objects.get(
            source_invoice=self.invoice,
        )

        self.assertEqual(
            journal.status,
            JournalEntry.Status.DRAFT,
        )

        self.assertEqual(
            journal.approval_decision,
            decision,
        )

        self.assertEqual(
            journal.created_by,
            self.approver,
        )

        self.assertEqual(
            journal.lines.count(),
            2,
        )

        self.assertEqual(
            journal.lines.get(line_number=1).debit,
            Decimal("250000.00"),
        )

        self.assertEqual(
            journal.lines.get(line_number=2).credit,
            Decimal("250000.00"),
        )

    def test_approval_creates_audit_event(self):
        response = self.client.post(
            self.approve_url,
            {"comment": "Approved after verification."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        event = InvoiceAuditEvent.objects.get(
            invoice=self.invoice,
            action=InvoiceAuditEvent.Action.APPROVAL_GRANTED,
        )

        self.assertEqual(event.actor, self.approver)

        self.assertEqual(
            event.metadata["approval_request_id"],
            str(self.approval_request.id),
        )

    def test_submitter_cannot_approve_own_request(self):
        self.approval_request.submitted_by = self.approver
        self.approval_request.save(
            update_fields=["submitted_by", "updated_at"]
        )

        response = self.client.post(
            self.approve_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.PENDING_APPROVAL,
        )

        self.assertFalse(
            ApprovalDecision.objects.filter(
                approval_request=self.approval_request,
            ).exists()
        )

    def test_finance_operator_cannot_approve(self):
        self.client.force_authenticate(user=self.submitter)

        response = self.client.post(
            self.approve_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_finance_reviewer_can_reject_with_comment(self):
        response = self.client.post(
            self.reject_url,
            {"comment": "Supplier information could not be verified."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()
        self.approval_request.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.REJECTED,
        )

        self.assertEqual(
            self.approval_request.status,
            ApprovalRequest.Status.REJECTED,
        )

        decision = ApprovalDecision.objects.get(
            approval_request=self.approval_request,
        )

        self.assertEqual(
            decision.outcome,
            ApprovalDecision.Outcome.REJECTED,
        )

        self.assertTrue(decision.comment)

    def test_rejection_requires_comment(self):
        response = self.client.post(
            self.reject_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        self.invoice.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.PENDING_APPROVAL,
        )

        self.assertFalse(
            ApprovalDecision.objects.filter(
                approval_request=self.approval_request,
            ).exists()
        )

    def test_approval_request_can_only_receive_one_decision(self):
        first_response = self.client.post(
            self.approve_url,
            {"comment": "Approved."},
            format="json",
        )

        self.assertEqual(first_response.status_code, 200)

        second_response = self.client.post(
            self.reject_url,
            {"comment": "Attempted second decision."},
            format="json",
        )

        self.assertEqual(second_response.status_code, 409)

        self.assertEqual(
            ApprovalDecision.objects.filter(
                approval_request=self.approval_request,
            ).count(),
            1,
        )

    def test_foreign_organization_request_is_not_accessible(self):
        another_organization = Organization.objects.create(
            name="Another Approval Company",
            slug="another-approval-company",
        )

        another_invoice = Invoice.objects.create(
            organization=another_organization,
            invoice_number="FOREIGN-001",
            status=Invoice.Status.PENDING_APPROVAL,
        )

        another_request = ApprovalRequest.objects.create(
            organization=another_organization,
            invoice=another_invoice,
            submitted_by=self.submitter,
        )

        foreign_url = reverse(
            "approval-detail",
            kwargs={
                "organization_id": self.organization.id,
                "approval_request_id": another_request.id,
            },
        )

        response = self.client.get(foreign_url)

        self.assertEqual(response.status_code, 404)

    def test_inactive_membership_cannot_access_approval_queue(self):
        self.approver_membership.is_active = False
        self.approver_membership.save(
            update_fields=["is_active", "updated_at"]
        )

        response = self.client.get(self.queue_url)

        self.assertEqual(response.status_code, 404)

    def test_approval_decision_cannot_be_modified_or_deleted(self):
        response = self.client.post(
            self.approve_url,
            {"comment": "Approved."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        decision = ApprovalDecision.objects.get(
            approval_request=self.approval_request,
        )

        decision.comment = "Modified decision."

        with self.assertRaises(ValidationError):
            decision.save()

        with self.assertRaises(ValidationError):
            decision.delete()

class ReturnRejectedInvoiceAPITests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.submitter = User.objects.create_user(
            username="return_submitter",
            password="test-password-123",
        )

        self.approver = User.objects.create_user(
            username="return_approver",
            password="test-password-123",
        )

        self.operator = User.objects.create_user(
            username="return_operator",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Return Review Company",
            slug="return-review-company",
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.submitter,
            role=OrganizationMembership.Role.FINANCE_OPERATOR,
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.approver,
            role=OrganizationMembership.Role.FINANCE_REVIEWER,
        )

        self.operator_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.operator,
            role=OrganizationMembership.Role.FINANCE_OPERATOR,
        )

        self.invoice = Invoice.objects.create(
            organization=self.organization,
            invoice_number="RETURN-001",
            status=Invoice.Status.REJECTED,
        )

        self.approval_request = ApprovalRequest.objects.create(
            organization=self.organization,
            invoice=self.invoice,
            submitted_by=self.submitter,
            status=ApprovalRequest.Status.REJECTED,
        )

        self.decision = ApprovalDecision.objects.create(
            approval_request=self.approval_request,
            decided_by=self.approver,
            outcome=ApprovalDecision.Outcome.REJECTED,
            comment="Supplier details need correction.",
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.operator)

        self.return_url = reverse(
            "approval-return-to-review",
            kwargs={
                "organization_id": self.organization.id,
                "approval_request_id": self.approval_request.id,
            },
        )

    def return_invoice(self, reason="Correct supplier information."):
        return self.client.post(
            self.return_url,
            {"return_reason": reason},
            format="json",
        )

    def test_finance_operator_can_return_rejected_invoice(self):
        response = self.return_invoice()

        self.assertEqual(response.status_code, 200)

        self.invoice.refresh_from_db()
        self.approval_request.refresh_from_db()
        self.decision.refresh_from_db()

        self.assertEqual(
            self.invoice.status,
            Invoice.Status.NEEDS_REVIEW,
        )

        # Previous request and decision remain unchanged.
        self.assertEqual(
            self.approval_request.status,
            ApprovalRequest.Status.REJECTED,
        )

        self.assertEqual(
            self.decision.outcome,
            ApprovalDecision.Outcome.REJECTED,
        )

        self.assertEqual(
            self.decision.comment,
            "Supplier details need correction.",
        )

    def test_return_operation_creates_audit_event(self):
        response = self.return_invoice(
            "Correct the supplier invoice number."
        )

        self.assertEqual(response.status_code, 200)

        event = InvoiceAuditEvent.objects.get(
            invoice=self.invoice,
            action=InvoiceAuditEvent.Action.REOPENED_FOR_REVIEW,
        )

        self.assertEqual(event.actor, self.operator)

        self.assertEqual(
            event.changes["invoice_status"]["before"],
            Invoice.Status.REJECTED,
        )

        self.assertEqual(
            event.changes["invoice_status"]["after"],
            Invoice.Status.NEEDS_REVIEW,
        )

        self.assertEqual(
            event.metadata["return_reason"],
            "Correct the supplier invoice number.",
        )

        self.assertEqual(
            event.metadata["rejection_comment"],
            self.decision.comment,
        )

    def test_owner_can_return_rejected_invoice(self):
        owner = get_user_model().objects.create_user(
            username="return_owner",
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=owner,
            role=OrganizationMembership.Role.OWNER,
        )

        self.client.force_authenticate(user=owner)

        response = self.return_invoice()

        self.assertEqual(response.status_code, 200)

    def test_finance_admin_can_return_rejected_invoice(self):
        self.operator_membership.role = (
            OrganizationMembership.Role.FINANCE_ADMIN
        )
        self.operator_membership.save()

        response = self.return_invoice()

        self.assertEqual(response.status_code, 200)

    def test_finance_reviewer_cannot_return_invoice(self):
        self.client.force_authenticate(user=self.approver)

        response = self.return_invoice()

        self.assertEqual(response.status_code, 403)

    def test_read_only_member_cannot_return_invoice(self):
        self.operator_membership.role = (
            OrganizationMembership.Role.READ_ONLY
        )
        self.operator_membership.save()

        response = self.return_invoice()

        self.assertEqual(response.status_code, 403)

    def test_return_reason_is_required(self):
        response = self.client.post(
            self.return_url,
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_pending_approval_request_cannot_be_returned(self):
        self.approval_request.status = ApprovalRequest.Status.PENDING
        self.approval_request.save(
            update_fields=["status", "updated_at"]
        )

        self.invoice.status = Invoice.Status.PENDING_APPROVAL
        self.invoice.save(
            update_fields=["status", "updated_at"]
        )

        response = self.return_invoice()

        self.assertEqual(response.status_code, 409)

    def test_foreign_organization_request_is_not_accessible(self):
        another_organization = Organization.objects.create(
            name="Another Return Company",
            slug="another-return-company",
        )

        another_invoice = Invoice.objects.create(
            organization=another_organization,
            invoice_number="FOREIGN-RETURN-001",
            status=Invoice.Status.REJECTED,
        )

        another_request = ApprovalRequest.objects.create(
            organization=another_organization,
            invoice=another_invoice,
            submitted_by=self.submitter,
            status=ApprovalRequest.Status.REJECTED,
        )

        ApprovalDecision.objects.create(
            approval_request=another_request,
            decided_by=self.approver,
            outcome=ApprovalDecision.Outcome.REJECTED,
            comment="Requires correction.",
        )

        foreign_url = reverse(
            "approval-return-to-review",
            kwargs={
                "organization_id": self.organization.id,
                "approval_request_id": another_request.id,
            },
        )

        response = self.client.post(
            foreign_url,
            {"return_reason": "Testing organization isolation."},
            format="json",
        )

        self.assertEqual(response.status_code, 404)