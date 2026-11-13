from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from accounting.models import Account, JournalEntry, JournalLine
from accounting.ap_balances import (
    get_invoice_ap_obligation,
    get_invoice_posted_payment_allocations,
)
from invoices.models import Invoice

ZERO = Decimal("0.00")

# A reversal does not erase the original posted transaction.
# Both entries must remain visible in historical reports.
REPORTABLE_STATUSES = (
    JournalEntry.Status.POSTED,
    JournalEntry.Status.REVERSED,
)


def money(value):
    return f"{value:.2f}"


def balance_details(value):
    """
    Convert a signed debit-minus-credit balance into an
    absolute amount and its balance side.
    """

    if value > ZERO:
        side = "debit"
    elif value < ZERO:
        side = "credit"
    else:
        side = "zero"

    return {
        "amount": money(abs(value)),
        "side": side,
    }


def aggregate_currency_totals(queryset):
    """
    Sum journal-line debits and credits separately by currency.
    """

    rows = (
        queryset
        .values("entry__currency")
        .annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        )
    )

    return {
        row["entry__currency"]: {
            "debit": row["total_debit"] or ZERO,
            "credit": row["total_credit"] or ZERO,
        }
        for row in rows
    }


def build_account_ledger(
    *,
    account,
    start_date=None,
    end_date=None,
    currency=None,
):
    """
    Build an account ledger with opening balances,
    individual transactions and running balances.

    Draft journals are excluded.

    Original reversed journals and their posted reversal
    entries are both included to preserve accounting history.

    Balances are calculated independently for each currency.
    """

    base_queryset = JournalLine.objects.filter(
        account=account,
        entry__organization_id=account.organization_id,
        entry__status__in=REPORTABLE_STATUSES,
    )

    if currency:
        base_queryset = base_queryset.filter(
            entry__currency=currency,
        )

    # Calculate movements before the report period.
    if start_date:
        opening_queryset = base_queryset.filter(
            entry__entry_date__lt=start_date,
        )
    else:
        opening_queryset = base_queryset.none()

    opening_by_currency = aggregate_currency_totals(
        opening_queryset,
    )

    running_balances = {
        code: totals["debit"] - totals["credit"]
        for code, totals in opening_by_currency.items()
    }

    # Retrieve transactions inside the report period.
    activity_queryset = base_queryset

    if start_date:
        activity_queryset = activity_queryset.filter(
            entry__entry_date__gte=start_date,
        )

    if end_date:
        activity_queryset = activity_queryset.filter(
            entry__entry_date__lte=end_date,
        )

    activity_queryset = (
        activity_queryset
        .select_related("entry")
        .order_by(
            "entry__entry_date",
            "entry__created_at",
            "entry_id",
            "line_number",
            "id",
        )
    )

    activity_totals = defaultdict(
        lambda: {
            "debit": ZERO,
            "credit": ZERO,
        }
    )

    transactions = []

    for line in activity_queryset:
        entry = line.entry
        code = entry.currency

        debit = line.debit
        credit = line.credit

        running_balances[code] = (
            running_balances.get(code, ZERO)
            + debit
            - credit
        )

        activity_totals[code]["debit"] += debit
        activity_totals[code]["credit"] += credit

        transactions.append({
            "journal_entry_id": str(entry.id),
            "reference": entry.reference,
            "entry_date": entry.entry_date.isoformat(),
            "journal_status": entry.status,
            "journal_description": entry.description,
            "line_id": str(line.id),
            "line_number": line.line_number,
            "description": line.description,
            "currency": code,
            "debit": money(debit),
            "credit": money(credit),
            "running_balance": balance_details(
                running_balances[code],
            ),
        })

    # Include currencies that only have opening balances.
    currencies = set(opening_by_currency)
    currencies.update(activity_totals)

    if currency:
        currencies.add(currency)

    if not currencies:
        currencies.add(account.organization.default_currency)

    opening_balances = []
    totals_by_currency = []
    closing_balances = []

    for code in sorted(currencies):
        opening = opening_by_currency.get(
            code,
            {"debit": ZERO, "credit": ZERO},
        )

        activity = activity_totals.get(
            code,
            {"debit": ZERO, "credit": ZERO},
        )

        opening_net = opening["debit"] - opening["credit"]
        closing_net = running_balances.get(code, ZERO)

        opening_balances.append({
            "currency": code,
            **balance_details(opening_net),
        })

        totals_by_currency.append({
            "currency": code,
            "debit": money(activity["debit"]),
            "credit": money(activity["credit"]),
        })

        closing_balances.append({
            "currency": code,
            **balance_details(closing_net),
        })

    return {
        "period": {
            "start_date": (
                start_date.isoformat() if start_date else None
            ),
            "end_date": (
                end_date.isoformat() if end_date else None
            ),
        },
        "count": len(transactions),
        "opening_balances": opening_balances,
        "transactions": transactions,
        "totals_by_currency": totals_by_currency,
        "closing_balances": closing_balances,
        "report_basis": (
            "Posted journals and original reversed journals are included. "
            "Draft journals are excluded."
        ),
    }


def build_trial_balance(
    *,
    organization,
    as_of_date,
    currency=None,
):
    """
    Calculate account balances as of a specified date.

    Balances are calculated independently for each currency.
    All organization accounts are returned, including zero balances.
    """

    queryset = JournalLine.objects.filter(
        entry__organization=organization,
        entry__status__in=REPORTABLE_STATUSES,
        entry__entry_date__lte=as_of_date,
        account__organization=organization,
    )

    if currency:
        queryset = queryset.filter(
            entry__currency=currency,
        )

    aggregated = (
        queryset
        .values(
            "entry__currency",
            "account_id",
        )
        .annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        )
    )

    balances_by_currency = defaultdict(dict)

    for row in aggregated:
        balances_by_currency[
            row["entry__currency"]
        ][row["account_id"]] = {
            "debit": row["total_debit"] or ZERO,
            "credit": row["total_credit"] or ZERO,
        }

    currencies = set(balances_by_currency)

    if currency:
        currencies.add(currency)

    if not currencies:
        currencies.add(organization.default_currency)

    accounts = list(
        Account.objects
        .filter(organization=organization)
        .order_by("code")
    )

    currency_reports = []

    for code in sorted(currencies):
        account_balances = balances_by_currency.get(
            code,
            {},
        )

        account_rows = []

        total_debit_balance = ZERO
        total_credit_balance = ZERO

        for account in accounts:
            amounts = account_balances.get(
                account.id,
                {
                    "debit": ZERO,
                    "credit": ZERO,
                },
            )

            # Trial-balance amounts show the remaining balance
            # on its actual debit or credit side.
            net_balance = (
                amounts["debit"] - amounts["credit"]
            )

            debit_balance = max(net_balance, ZERO)
            credit_balance = max(-net_balance, ZERO)

            total_debit_balance += debit_balance
            total_credit_balance += credit_balance

            account_rows.append({
                "id": str(account.id),
                "code": account.code,
                "name": account.name,
                "account_type": account.account_type,
                "is_active": account.is_active,
                "is_control_account": account.is_control_account,
                "debit_balance": money(debit_balance),
                "credit_balance": money(credit_balance),
            })

        currency_reports.append({
            "currency": code,
            "accounts": account_rows,
            "totals": {
                "debit_balance": money(total_debit_balance),
                "credit_balance": money(total_credit_balance),
            },
            "is_balanced": (
                total_debit_balance == total_credit_balance
            ),
        })

    return {
        "as_of_date": as_of_date.isoformat(),
        "currencies": currency_reports,
        "report_basis": (
            "Posted journals and original reversed journals are included. "
            "Draft journals are excluded. Each currency is reported separately."
        ),
    }

def build_income_statement(
    *,
    organization,
    start_date,
    end_date,
    currency=None,
):
    """
    Build an income statement for a selected period.

    Revenue is calculated as credits minus debits.
    Expenses are calculated as debits minus credits.

    Posted journals and original reversed journals are included.
    Draft journals are excluded.
    """

    queryset = JournalLine.objects.filter(
        entry__organization=organization,
        entry__status__in=REPORTABLE_STATUSES,
        entry__entry_date__gte=start_date,
        entry__entry_date__lte=end_date,
        account__organization=organization,
        account__account_type__in=(
            Account.AccountType.INCOME,
            Account.AccountType.EXPENSE,
        ),
    )

    if currency:
        queryset = queryset.filter(
            entry__currency=currency,
        )

    rows = (
        queryset
        .values(
            "entry__currency",
            "account_id",
            "account__code",
            "account__name",
            "account__account_type",
        )
        .annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        )
        .order_by(
            "entry__currency",
            "account__code",
        )
    )

    reports = defaultdict(
        lambda: {
            "revenue_accounts": [],
            "expense_accounts": [],
            "total_revenue": ZERO,
            "total_expenses": ZERO,
        }
    )

    for row in rows:
        code = row["entry__currency"]
        account_type = row["account__account_type"]

        debit = row["total_debit"] or ZERO
        credit = row["total_credit"] or ZERO

        if account_type == Account.AccountType.INCOME:
            amount = credit - debit

            reports[code]["revenue_accounts"].append({
                "account_id": str(row["account_id"]),
                "code": row["account__code"],
                "name": row["account__name"],
                "amount": money(amount),
            })

            reports[code]["total_revenue"] += amount

        else:
            amount = debit - credit

            reports[code]["expense_accounts"].append({
                "account_id": str(row["account_id"]),
                "code": row["account__code"],
                "name": row["account__name"],
                "amount": money(amount),
            })

            reports[code]["total_expenses"] += amount

    currencies = set(reports)

    if currency:
        currencies.add(currency)

    if not currencies:
        currencies.add(organization.default_currency)

    currency_reports = []

    for code in sorted(currencies):
        report = reports[code]

        revenue = report["total_revenue"]
        expenses = report["total_expenses"]
        net_income = revenue - expenses

        currency_reports.append({
            "currency": code,
            "revenue_accounts": report["revenue_accounts"],
            "expense_accounts": report["expense_accounts"],
            "total_revenue": money(revenue),
            "total_expenses": money(expenses),
            "net_income": money(net_income),
        })

    return {
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "currencies": currency_reports,
        "report_basis": (
            "Posted journals and original reversed journals are included. "
            "Draft journals are excluded. "
            "Revenue and expenses are reported separately by currency."
        ),
    }


def build_balance_sheet(
    *,
    organization,
    as_of_date,
    currency=None,
):
    """
    Build a balance sheet as of a selected date.

    Assets use debit-normal balances.
    Liabilities and equity use credit-normal balances.

    Income and expense account activity is reported separately
    as cumulative unclosed earnings because FIN-01 does not
    yet implement year-end closing entries.
    """

    queryset = JournalLine.objects.filter(
        entry__organization=organization,
        entry__status__in=REPORTABLE_STATUSES,
        entry__entry_date__lte=as_of_date,
        account__organization=organization,
    )

    if currency:
        queryset = queryset.filter(
            entry__currency=currency,
        )

    rows = (
        queryset
        .values(
            "entry__currency",
            "account_id",
            "account__account_type",
        )
        .annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
        )
    )

    balances_by_currency = defaultdict(dict)

    for row in rows:
        code = row["entry__currency"]

        balances_by_currency[code][row["account_id"]] = {
            "debit": row["total_debit"] or ZERO,
            "credit": row["total_credit"] or ZERO,
        }

    currencies = set(balances_by_currency)

    if currency:
        currencies.add(currency)

    if not currencies:
        currencies.add(organization.default_currency)

    accounts = list(
        Account.objects
        .filter(organization=organization)
        .order_by("code")
    )

    currency_reports = []

    for code in sorted(currencies):
        balances = balances_by_currency.get(code, {})

        assets = []
        liabilities = []
        equity = []

        asset_total = ZERO
        liability_total = ZERO
        equity_total = ZERO

        revenue_total = ZERO
        expense_total = ZERO

        for account in accounts:
            amounts = balances.get(
                account.id,
                {
                    "debit": ZERO,
                    "credit": ZERO,
                },
            )

            debit = amounts["debit"]
            credit = amounts["credit"]

            if account.account_type == Account.AccountType.ASSET:
                balance = debit - credit

                asset_total += balance

                assets.append({
                    "id": str(account.id),
                    "code": account.code,
                    "name": account.name,
                    "account_type": account.account_type,
                    "is_active": account.is_active,
                    "balance": money(balance),
                })

            elif account.account_type == Account.AccountType.LIABILITY:
                balance = credit - debit

                liability_total += balance

                liabilities.append({
                    "id": str(account.id),
                    "code": account.code,
                    "name": account.name,
                    "account_type": account.account_type,
                    "is_active": account.is_active,
                    "balance": money(balance),
                })

            elif account.account_type == Account.AccountType.EQUITY:
                balance = credit - debit

                equity_total += balance

                equity.append({
                    "id": str(account.id),
                    "code": account.code,
                    "name": account.name,
                    "account_type": account.account_type,
                    "is_active": account.is_active,
                    "balance": money(balance),
                })

            elif account.account_type == Account.AccountType.INCOME:
                revenue_total += credit - debit

            elif account.account_type == Account.AccountType.EXPENSE:
                expense_total += debit - credit

        cumulative_unclosed_earnings = (
            revenue_total - expense_total
        )

        total_liabilities_and_equity = (
            liability_total
            + equity_total
            + cumulative_unclosed_earnings
        )

        balance_difference = (
            asset_total - total_liabilities_and_equity
        )

        currency_reports.append({
            "currency": code,

            "assets": {
                "accounts": assets,
                "total": money(asset_total),
            },

            "liabilities": {
                "accounts": liabilities,
                "total": money(liability_total),
            },

            "equity": {
                "accounts": equity,
                "total": money(equity_total),
                "cumulative_unclosed_earnings": money(
                    cumulative_unclosed_earnings
                ),
                "total_including_unclosed_earnings": money(
                    equity_total + cumulative_unclosed_earnings
                ),
            },

            "total_liabilities_and_equity": money(
                total_liabilities_and_equity
            ),

            "balance_difference": money(balance_difference),

            "is_balanced": balance_difference == ZERO,
        })

    return {
        "as_of_date": as_of_date.isoformat(),
        "currencies": currency_reports,
        "report_basis": (
            "Posted journals and original reversed journals are included. "
            "Draft journals are excluded. "
            "Cumulative unclosed earnings are included in equity "
            "because year-end closing entries are not yet implemented."
        ),
    }

AP_AGEING_BUCKET_LABELS = {
    "current": "Current / Not Yet Due",
    "1_30_days": "1–30 Days Overdue",
    "31_60_days": "31–60 Days Overdue",
    "61_90_days": "61–90 Days Overdue",
    "over_90_days": "Over 90 Days Overdue",
    "missing_due_date": "Missing Due Date",
}


def _get_ap_ageing_bucket(*, due_date, as_of_date):
    """
    Classify an outstanding invoice balance by its due date.

    A due date equal to the reporting date is current.
    Missing due dates are never inferred from payment terms.
    """

    if due_date is None:
        return "missing_due_date", None

    days_overdue = (as_of_date - due_date).days

    if days_overdue <= 0:
        return "current", 0

    if days_overdue <= 30:
        return "1_30_days", days_overdue

    if days_overdue <= 60:
        return "31_60_days", days_overdue

    if days_overdue <= 90:
        return "61_90_days", days_overdue

    return "over_90_days", days_overdue


def _empty_ap_ageing_totals():
    return {
        bucket: ZERO
        for bucket in AP_AGEING_BUCKET_LABELS
    }


def _serialize_ap_ageing_totals(totals):
    return {
        bucket: money(totals[bucket])
        for bucket in AP_AGEING_BUCKET_LABELS
    }


def build_ap_ageing_report(
    *,
    organization,
    as_of_date,
    currency=None,
):
    """
    Build an Accounts Payable ageing report.

    Outstanding invoice balances are calculated from:
    - Posted invoice journals.
    - Posted adjustments and their reversals.
    - Posted vendor payment allocations.
    - Payment reversals effective by the reporting date.

    Draft payments do not reduce outstanding AP.

    Balances are grouped by currency and vendor. Invoices without
    an assigned vendor are grouped under Unassigned Vendor.
    """

    invoices = (
        Invoice.objects
        .filter(
            organization=organization,
            journal_entry__isnull=False,
        )
        .select_related(
            "vendor",
            "journal_entry",
        )
        .order_by(
            "journal_entry__currency",
            "vendor__legal_name",
            "invoice_date",
            "invoice_number",
            "id",
        )
    )

    if currency:
        invoices = invoices.filter(
            journal_entry__currency=currency,
        )

    currency_reports = {}

    for invoice in invoices:
        journal = invoice.journal_entry
        invoice_currency = journal.currency

        if not invoice_currency:
            continue

        ap_obligation = get_invoice_ap_obligation(
            invoice=invoice,
            as_of_date=as_of_date,
        )

        if ap_obligation <= ZERO:
            continue

        posted_payments = (
            get_invoice_posted_payment_allocations(
                invoice=invoice,
                as_of_date=as_of_date,
            )
        )

        outstanding = ap_obligation - posted_payments

        # A subsequent adjustment can reduce the obligation below
        # amounts previously paid. Do not report negative AP.
        if outstanding <= ZERO:
            continue

        bucket, days_overdue = _get_ap_ageing_bucket(
            due_date=invoice.due_date,
            as_of_date=as_of_date,
        )

        currency_report = currency_reports.setdefault(
            invoice_currency,
            {
                "currency": invoice_currency,
                "bucket_totals": _empty_ap_ageing_totals(),
                "total_outstanding": ZERO,
                "invoice_count": 0,
                "vendors": {},
            },
        )

        vendor_key = (
            str(invoice.vendor_id)
            if invoice.vendor_id
            else "unassigned"
        )

        if invoice.vendor:
            vendor_name = (
                invoice.vendor.display_name
                or invoice.vendor.legal_name
            )
            vendor_id = str(invoice.vendor_id)
        else:
            vendor_name = "Unassigned Vendor"
            vendor_id = None

        vendor_report = currency_report["vendors"].setdefault(
            vendor_key,
            {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "bucket_totals": _empty_ap_ageing_totals(),
                "total_outstanding": ZERO,
                "invoice_count": 0,
                "invoices": [],
            },
        )

        invoice_report = {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice.invoice_number,
            "invoice_date": (
                invoice.invoice_date.isoformat()
                if invoice.invoice_date
                else None
            ),
            "due_date": (
                invoice.due_date.isoformat()
                if invoice.due_date
                else None
            ),
            "ageing_bucket": bucket,
            "days_overdue": days_overdue,
            "ap_obligation": money(ap_obligation),
            "posted_payments": money(posted_payments),
            "outstanding_amount": money(outstanding),
        }

        currency_report["bucket_totals"][bucket] += outstanding
        currency_report["total_outstanding"] += outstanding
        currency_report["invoice_count"] += 1

        vendor_report["bucket_totals"][bucket] += outstanding
        vendor_report["total_outstanding"] += outstanding
        vendor_report["invoice_count"] += 1
        vendor_report["invoices"].append(invoice_report)

    # Retain an empty report for the requested/default currency
    # when there are no outstanding invoices.
    if not currency_reports:
        empty_currency = currency or organization.default_currency

        currency_reports[empty_currency] = {
            "currency": empty_currency,
            "bucket_totals": _empty_ap_ageing_totals(),
            "total_outstanding": ZERO,
            "invoice_count": 0,
            "vendors": {},
        }

    serialized_currencies = []

    for code in sorted(currency_reports):
        report = currency_reports[code]

        vendors = []

        for vendor in report["vendors"].values():
            vendors.append({
                "vendor_id": vendor["vendor_id"],
                "vendor_name": vendor["vendor_name"],
                "bucket_totals": _serialize_ap_ageing_totals(
                    vendor["bucket_totals"],
                ),
                "total_outstanding": money(
                    vendor["total_outstanding"],
                ),
                "invoice_count": vendor["invoice_count"],
                "invoices": vendor["invoices"],
            })

        vendors.sort(
            key=lambda item: item["vendor_name"].casefold(),
        )

        serialized_currencies.append({
            "currency": code,
            "bucket_totals": _serialize_ap_ageing_totals(
                report["bucket_totals"],
            ),
            "total_outstanding": money(
                report["total_outstanding"],
            ),
            "invoice_count": report["invoice_count"],
            "vendors": vendors,
        })

    return {
        "organization_id": str(organization.id),
        "as_of_date": as_of_date.isoformat(),
        "currency_filter": currency,
        "bucket_labels": AP_AGEING_BUCKET_LABELS,
        "currencies": serialized_currencies,
    }