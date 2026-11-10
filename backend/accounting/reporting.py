from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from accounting.models import Account, JournalEntry, JournalLine


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