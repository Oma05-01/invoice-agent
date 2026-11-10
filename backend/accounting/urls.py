from django.urls import path

from accounting.views import (
    AccountingAccountInitializeAPIView,
    AccountingAccountListAPIView,
    JournalEntryDetailAPIView,
    JournalEntryListAPIView,
    JournalEntryPostAPIView,
    JournalEntryReverseAPIView,
    JournalLineCorrectionAPIView,
    AccountLedgerAPIView,
    TrialBalanceAPIView,
    IncomeStatementAPIView,
    BalanceSheetAPIView,
)


urlpatterns = [
    path(
        "organizations/<uuid:organization_id>/accounting/accounts/",
        AccountingAccountListAPIView.as_view(),
        name="accounting-account-list",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/accounts/initialize/",
        AccountingAccountInitializeAPIView.as_view(),
        name="accounting-account-initialize",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/journals/",
        JournalEntryListAPIView.as_view(),
        name="accounting-journal-list",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/journals/<uuid:journal_entry_id>/",
        JournalEntryDetailAPIView.as_view(),
        name="accounting-journal-detail",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/journals/<uuid:journal_entry_id>/lines/<uuid:journal_line_id>/",
        JournalLineCorrectionAPIView.as_view(),
        name="accounting-journal-line-correction",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/journals/<uuid:journal_entry_id>/post/",
        JournalEntryPostAPIView.as_view(),
        name="accounting-journal-post",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/journals/<uuid:journal_entry_id>/reverse/",
        JournalEntryReverseAPIView.as_view(),
        name="accounting-journal-reverse",
    ),
        path(
        "organizations/<uuid:organization_id>/accounting/accounts/<uuid:account_id>/ledger/",
        AccountLedgerAPIView.as_view(),
        name="accounting-account-ledger",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/reports/trial-balance/",
        TrialBalanceAPIView.as_view(),
        name="accounting-trial-balance",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/reports/income-statement/",
        IncomeStatementAPIView.as_view(),
        name="accounting-income-statement",
    ),
    path(
        "organizations/<uuid:organization_id>/accounting/reports/balance-sheet/",
        BalanceSheetAPIView.as_view(),
        name="accounting-balance-sheet",
    ),
]

