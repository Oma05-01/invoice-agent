from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import Account, JournalEntry, JournalLine
from accounting.serializers import (
    AccountSerializer,
    JournalEntrySerializer,
    JournalLineCorrectionSerializer,
    JournalReversalSerializer,
    AccountLedgerQuerySerializer,
    TrialBalanceQuerySerializer,
    IncomeStatementQuerySerializer,
    BalanceSheetQuerySerializer,
    JournalAdjustmentCreateSerializer,
    JournalEntryDateUpdateSerializer
)
from accounting.services import (
    AccountingConfigurationError,
    AccountingPermissionError,
    AccountingStateError,
    initialize_chart_of_accounts,
    post_journal_entry,
    require_accounting_role,
    reverse_journal_entry,
    update_draft_journal_line,
    create_adjustment_journal,
    update_draft_journal_entry_date
)

from accounting.reporting import (
    build_account_ledger,
    build_trial_balance,
    build_income_statement,
    build_balance_sheet,
)

from django.utils import timezone

from organizations.models import OrganizationMembership


INITIALIZATION_ROLES = (
    OrganizationMembership.Role.OWNER,
    OrganizationMembership.Role.FINANCE_ADMIN,
)


def accounting_error_response(exc):
    if isinstance(exc, AccountingPermissionError):
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(
        exc,
        (
            AccountingStateError,
            AccountingConfigurationError,
            ValidationError,
        ),
    ):
        if isinstance(exc, ValidationError):
            if hasattr(exc, "message_dict"):
                detail = exc.message_dict
            else:
                detail = exc.messages
        else:
            detail = str(exc)

        return Response(
            {"detail": detail},
            status=status.HTTP_400_BAD_REQUEST,
        )

    raise exc


class OrganizationAccountingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_membership(self, request, organization_id):
        membership = (
            OrganizationMembership.objects
            .select_related("organization")
            .filter(
                organization_id=organization_id,
                user=request.user,
                is_active=True,
                organization__is_active=True,
            )
            .first()
        )

        if membership is None:
            raise NotFound(
                "Organization not found or access denied."
            )

        return membership


class AccountingAccountListAPIView(
    OrganizationAccountingAPIView
):
    def get(self, request, organization_id):
        self.get_membership(request, organization_id)

        accounts = Account.objects.filter(
            organization_id=organization_id,
        ).select_related("parent")

        serializer = AccountSerializer(accounts, many=True)

        return Response({
            "count": accounts.count(),
            "accounts": serializer.data,
        })


class AccountingAccountInitializeAPIView(
    OrganizationAccountingAPIView
):
    def post(self, request, organization_id):
        self.get_membership(request, organization_id)

        try:
            with transaction.atomic():
                require_accounting_role(
                    organization_id=organization_id,
                    actor=request.user,
                    allowed_roles=INITIALIZATION_ROLES,
                )

                from organizations.models import Organization

                organization = get_object_or_404(
                    Organization,
                    pk=organization_id,
                    is_active=True,
                )

                accounts = initialize_chart_of_accounts(
                    organization=organization,
                )

            serializer = AccountSerializer(
                list(accounts.values()),
                many=True,
            )

            return Response({
                "detail": "Chart of accounts initialized.",
                "count": len(accounts),
                "accounts": serializer.data,
            })

        except (
            AccountingPermissionError,
            AccountingStateError,
            AccountingConfigurationError,
            ValidationError,
        ) as exc:
            return accounting_error_response(exc)


class JournalEntryListAPIView(
    OrganizationAccountingAPIView
):
    def get(self, request, organization_id):
        self.get_membership(request, organization_id)

        queryset = (
            JournalEntry.objects
            .filter(organization_id=organization_id)
            .select_related(
                "source_invoice",
                "created_by",
                "posted_by",
            )
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=JournalLine.objects.select_related(
                        "account"
                    ).order_by("line_number"),
                )
            )
        )

        journal_status = request.query_params.get("status")

        if journal_status:
            valid_statuses = JournalEntry.Status.values

            if journal_status not in valid_statuses:
                return Response(
                    {
                        "detail": (
                            "Invalid journal status. "
                            f"Allowed values: {', '.join(valid_statuses)}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            queryset = queryset.filter(status=journal_status)

        serializer = JournalEntrySerializer(
            queryset,
            many=True,
        )

        return Response({
            "count": queryset.count(),
            "journals": serializer.data,
        })


class JournalEntryDetailAPIView(
    OrganizationAccountingAPIView
):
    def get(self, request, organization_id, journal_entry_id):
        self.get_membership(request, organization_id)

        journal = get_object_or_404(
            JournalEntry.objects
            .filter(organization_id=organization_id)
            .select_related(
                "source_invoice",
                "created_by",
                "posted_by",
            )
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=JournalLine.objects.select_related(
                        "account"
                    ).order_by("line_number"),
                )
            ),
            pk=journal_entry_id,
        )

        serializer = JournalEntrySerializer(journal)

        return Response(serializer.data)


class JournalLineCorrectionAPIView(
    OrganizationAccountingAPIView
):
    def patch(
        self,
        request,
        organization_id,
        journal_entry_id,
        journal_line_id,
    ):
        self.get_membership(request, organization_id)

        serializer = JournalLineCorrectionSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        validated_data = dict(serializer.validated_data)
        correction_reason = validated_data.pop(
            "correction_reason"
        )

        try:
            line = update_draft_journal_line(
                organization_id=organization_id,
                journal_entry_id=journal_entry_id,
                journal_line_id=journal_line_id,
                actor=request.user,
                corrections=validated_data,
                correction_reason=correction_reason,
            )

            line = (
                JournalLine.objects
                .select_related("account")
                .get(pk=line.pk)
            )

            from accounting.serializers import JournalLineSerializer

            return Response(
                JournalLineSerializer(line).data
            )

        except JournalEntry.DoesNotExist:
            raise NotFound("Journal entry not found.")

        except JournalLine.DoesNotExist:
            raise NotFound("Journal line not found.")

        except (
            AccountingPermissionError,
            AccountingStateError,
            AccountingConfigurationError,
            ValidationError,
        ) as exc:
            return accounting_error_response(exc)


class JournalEntryPostAPIView(
    OrganizationAccountingAPIView
):
    def post(
        self,
        request,
        organization_id,
        journal_entry_id,
    ):
        self.get_membership(request, organization_id)

        try:
            entry = post_journal_entry(
                organization_id=organization_id,
                journal_entry_id=journal_entry_id,
                actor=request.user,
            )

            return Response(
                JournalEntrySerializer(entry).data
            )

        except JournalEntry.DoesNotExist:
            raise NotFound("Journal entry not found.")

        except (
            AccountingPermissionError,
            AccountingStateError,
            AccountingConfigurationError,
            ValidationError,
        ) as exc:
            return accounting_error_response(exc)


class JournalEntryReverseAPIView(
    OrganizationAccountingAPIView
):
    def post(
        self,
        request,
        organization_id,
        journal_entry_id,
    ):
        self.get_membership(request, organization_id)

        serializer = JournalReversalSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        try:
            reversal = reverse_journal_entry(
                organization_id=organization_id,
                journal_entry_id=journal_entry_id,
                actor=request.user,
                reversal_reason=serializer.validated_data[
                    "reversal_reason"
                ],
            )

            reversal = (
                JournalEntry.objects
                .prefetch_related(
                    Prefetch(
                        "lines",
                        queryset=JournalLine.objects.select_related(
                            "account"
                        ).order_by("line_number"),
                    )
                )
                .get(pk=reversal.pk)
            )

            return Response(
                JournalEntrySerializer(reversal).data,
                status=status.HTTP_201_CREATED,
            )

        except JournalEntry.DoesNotExist:
            raise NotFound("Journal entry not found.")

        except (
            AccountingPermissionError,
            AccountingStateError,
            AccountingConfigurationError,
            ValidationError,
        ) as exc:
            return accounting_error_response(exc)


class JournalAdjustmentCreateAPIView(
    OrganizationAccountingAPIView
):
    def post(
        self,
        request,
        organization_id,
        journal_entry_id,
    ):
        self.get_membership(request, organization_id)

        serializer = JournalAdjustmentCreateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        try:
            entry = create_adjustment_journal(
                organization_id=organization_id,
                original_journal_id=journal_entry_id,
                actor=request.user,
                entry_date=serializer.validated_data["entry_date"],
                reason=serializer.validated_data["reason"],
                description=serializer.validated_data["description"],
                lines=serializer.validated_data["lines"],
            )

            entry = (
                JournalEntry.objects
                .select_related(
                    "created_by",
                    "posted_by",
                )
                .prefetch_related(
                    Prefetch(
                        "lines",
                        queryset=JournalLine.objects.select_related(
                            "account"
                        ).order_by("line_number"),
                    )
                )
                .get(pk=entry.pk)
            )

            adjustment = entry.adjustment_record

            return Response(
                {
                    "journal": JournalEntrySerializer(entry).data,
                    "adjustment": {
                        "id": str(adjustment.id),
                        "original_journal_id": str(
                            adjustment.original_journal_id
                        ),
                        "adjustment_journal_id": str(
                            adjustment.adjustment_journal_id
                        ),
                        "reason": adjustment.reason,
                    },
                    "message": "Adjustment journal draft created successfully.",
                },
                status=status.HTTP_201_CREATED,
            )

        except JournalEntry.DoesNotExist:
            raise NotFound("Original journal not found.")

        except (
            AccountingPermissionError,
            AccountingStateError,
            AccountingConfigurationError,
            ValidationError,
        ) as exc:
            return accounting_error_response(exc)


class AccountLedgerAPIView(OrganizationAccountingAPIView):
    """
    Return the transaction history and running balance
    for one account belonging to the selected organization.
    """

    def get(
        self,
        request,
        organization_id,
        account_id,
    ):
        membership = self.get_membership(
            request,
            organization_id,
        )

        serializer = AccountLedgerQuerySerializer(
            data=request.query_params,
        )
        serializer.is_valid(raise_exception=True)

        account = get_object_or_404(
            Account.objects.select_related("organization").filter(
                organization_id=organization_id,
            ),
            pk=account_id,
        )

        filters = serializer.validated_data

        report = build_account_ledger(
            account=account,
            start_date=filters.get("start_date"),
            end_date=filters.get("end_date"),
            currency=filters.get("currency"),
        )

        return Response({
            "account": AccountSerializer(account).data,
            **report,
        })


class TrialBalanceAPIView(OrganizationAccountingAPIView):
    """
    Return account balances as of a specified date.

    Every currency is reported separately.
    """

    def get(self, request, organization_id):
        membership = self.get_membership(
            request,
            organization_id,
        )

        serializer = TrialBalanceQuerySerializer(
            data=request.query_params,
        )
        serializer.is_valid(raise_exception=True)

        filters = serializer.validated_data

        report = build_trial_balance(
            organization=membership.organization,
            as_of_date=(
                filters.get("as_of_date")
                or timezone.localdate()
            ),
            currency=filters.get("currency"),
        )

        return Response(report)


class IncomeStatementAPIView(OrganizationAccountingAPIView):
    """
    Return revenue, expenses and net income for a date range.
    """

    def get(self, request, organization_id):
        membership = self.get_membership(
            request,
            organization_id,
        )

        serializer = IncomeStatementQuerySerializer(
            data=request.query_params,
        )
        serializer.is_valid(raise_exception=True)

        filters = serializer.validated_data

        report = build_income_statement(
            organization=membership.organization,
            start_date=filters["start_date"],
            end_date=filters["end_date"],
            currency=filters.get("currency"),
        )

        return Response(report)


class BalanceSheetAPIView(OrganizationAccountingAPIView):
    """
    Return assets, liabilities and equity as of a date.
    """

    def get(self, request, organization_id):
        membership = self.get_membership(
            request,
            organization_id,
        )

        serializer = BalanceSheetQuerySerializer(
            data=request.query_params,
        )
        serializer.is_valid(raise_exception=True)

        filters = serializer.validated_data

        report = build_balance_sheet(
            organization=membership.organization,
            as_of_date=(
                filters.get("as_of_date")
                or timezone.localdate()
            ),
            currency=filters.get("currency"),
        )

        return Response(report)

class JournalEntryDateUpdateAPIView(
    OrganizationAccountingAPIView
):
    def patch(
        self,
        request,
        organization_id,
        journal_entry_id,
    ):
        self.get_membership(request, organization_id)

        serializer = JournalEntryDateUpdateSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        try:
            entry = update_draft_journal_entry_date(
                organization_id=organization_id,
                journal_entry_id=journal_entry_id,
                actor=request.user,
                entry_date=serializer.validated_data["entry_date"],
                correction_reason=serializer.validated_data[
                    "correction_reason"
                ],
            )

            return Response(
                JournalEntrySerializer(entry).data
            )

        except JournalEntry.DoesNotExist:
            raise NotFound("Journal entry not found.")

        except (
            AccountingPermissionError,
            AccountingStateError,
            AccountingConfigurationError,
            ValidationError,
        ) as exc:
            return accounting_error_response(exc)

