"""Read-only expenditure reporting services."""

import re
from datetime import date, datetime

from django.db.models import (
    Case,
    CharField,
    F,
    Sum,
    Count,
    UUIDField,
    Value,
    When,
)
from django.db.models.functions import Coalesce, NullIf, TruncMonth

from accounting.models import Account, JournalLine
from accounting.reporting import REPORTABLE_STATUSES, ZERO, money


SPEND_DIMENSIONS = ("vendor", "account", "month")
MAX_SPEND_LIMIT = 100


class SpendReportError(ValueError):
    """Raised when expenditure report parameters are invalid."""


def _validate_spend_params(
    *,
    organization,
    dimension,
    start_date,
    end_date,
    limit,
    currency,
):
    if organization is None or getattr(organization, "pk", None) is None:
        raise SpendReportError("A saved organization is required.")

    if dimension not in SPEND_DIMENSIONS:
        choices = ", ".join(SPEND_DIMENSIONS)
        raise SpendReportError(
            f"Invalid spend dimension. Choose one of: {choices}."
        )

    for field_name, value in (
        ("start_date", start_date),
        ("end_date", end_date),
    ):
        if not isinstance(value, date) or isinstance(value, datetime):
            raise SpendReportError(f"{field_name} must be a date.")

    if start_date > end_date:
        raise SpendReportError("start_date cannot be after end_date.")

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise SpendReportError("limit must be an integer.")

    if not 1 <= limit <= MAX_SPEND_LIMIT:
        raise SpendReportError(
            f"limit must be between 1 and {MAX_SPEND_LIMIT}."
        )

    if currency is not None:
        if not isinstance(currency, str):
            raise SpendReportError("currency must be a three-letter code.")

        currency = currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise SpendReportError("currency must be a three-letter code.")

    return currency


def _vendor_grouped_rows(queryset, *, organization_id):
    """Group invoice journals and reversals by a same-organisation vendor."""
    source_vendor_name = Coalesce(
        NullIf(F("entry__source_invoice__vendor__display_name"), Value("")),
        NullIf(F("entry__source_invoice__vendor__legal_name"), Value("")),
        Value("Unattributed", output_field=CharField()),
        output_field=CharField(),
    )
    reversal_vendor_name = Coalesce(
        NullIf(
            F("entry__reversal_of__source_invoice__vendor__display_name"),
            Value(""),
        ),
        NullIf(
            F("entry__reversal_of__source_invoice__vendor__legal_name"),
            Value(""),
        ),
        Value("Unattributed", output_field=CharField()),
        output_field=CharField(),
    )

    adjustment_vendor_name = Coalesce(
        NullIf(
            F(
                "entry__adjustment_record__original_journal"
                "__source_invoice__vendor__display_name"
            ),
            Value(""),
        ),
        NullIf(
            F(
                "entry__adjustment_record__original_journal"
                "__source_invoice__vendor__legal_name"
            ),
            Value(""),
        ),
        Value("Unattributed", output_field=CharField()),
        output_field=CharField(),
    )

    nested_adjustment_vendor_name = Coalesce(
        NullIf(
            F(
                "entry__adjustment_record__original_journal"
                "__adjustment_record__original_journal"
                "__source_invoice__vendor__display_name"
            ),
            Value(""),
        ),
        NullIf(
            F(
                "entry__adjustment_record__original_journal"
                "__adjustment_record__original_journal"
                "__source_invoice__vendor__legal_name"
            ),
            Value(""),
        ),
        Value("Unattributed", output_field=CharField()),
        output_field=CharField(),
    )

    vendor_id = Case(
        When(
            entry__source_invoice__organization_id=organization_id,
            entry__source_invoice__vendor__organization_id=organization_id,
            then=F("entry__source_invoice__vendor_id"),
        ),
        When(
            entry__reversal_of__source_invoice__organization_id=organization_id,
            entry__reversal_of__source_invoice__vendor__organization_id=organization_id,
            then=F("entry__reversal_of__source_invoice__vendor_id"),
        ),
        When(
            entry__adjustment_record__organization_id=organization_id,
            entry__adjustment_record__original_journal__organization_id=organization_id,
            entry__adjustment_record__original_journal__source_invoice__organization_id=organization_id,
            entry__adjustment_record__original_journal__source_invoice__vendor__organization_id=organization_id,
            then=F(
                "entry__adjustment_record__original_journal"
                "__source_invoice__vendor_id"
            ),
        ),
        When(
            entry__adjustment_record__organization_id=organization_id,
            entry__adjustment_record__original_journal__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__original_journal__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__original_journal__source_invoice__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__original_journal__source_invoice__vendor__organization_id=organization_id,
            then=F(
                "entry__adjustment_record__original_journal"
                "__adjustment_record__original_journal"
                "__source_invoice__vendor_id"
            ),
        ),
        default=Value(None, output_field=UUIDField()),
        output_field=UUIDField(),
    )
    vendor_name = Case(
        When(
            entry__source_invoice__organization_id=organization_id,
            entry__source_invoice__vendor__organization_id=organization_id,
            then=source_vendor_name,
        ),
        When(
            entry__reversal_of__source_invoice__organization_id=organization_id,
            entry__reversal_of__source_invoice__vendor__organization_id=organization_id,
            then=reversal_vendor_name,
        ),
        When(
            entry__adjustment_record__organization_id=organization_id,
            entry__adjustment_record__original_journal__organization_id=organization_id,
            entry__adjustment_record__original_journal__source_invoice__organization_id=organization_id,
            entry__adjustment_record__original_journal__source_invoice__vendor__organization_id=organization_id,
            then=adjustment_vendor_name,
        ),
        When(
            entry__adjustment_record__organization_id=organization_id,
            entry__adjustment_record__original_journal__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__original_journal__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__original_journal__source_invoice__organization_id=organization_id,
            entry__adjustment_record__original_journal__adjustment_record__original_journal__source_invoice__vendor__organization_id=organization_id,
            then=nested_adjustment_vendor_name,
        ),
        default=Value("Unattributed", output_field=CharField()),
        output_field=CharField(),
    )

    return (
        queryset.annotate(
            report_vendor_id=vendor_id,
            report_vendor_name=vendor_name,
        )
        .values(
            "entry__currency",
            "report_vendor_id",
            "report_vendor_name",
        )
        .annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
            journal_count=Count("entry_id", distinct=True),
            journal_line_count=Count("pk"),
        )
    )


def _account_grouped_rows(queryset):
    return (
        queryset.values(
            "entry__currency",
            "account_id",
            "account__code",
            "account__name",
        )
        .annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
            journal_count=Count("entry_id", distinct=True),
            journal_line_count=Count("pk"),
        )
    )


def _month_grouped_rows(queryset):
    return (
        queryset.annotate(report_month=TruncMonth("entry__entry_date"))
        .values("entry__currency", "report_month")
        .annotate(
            total_debit=Sum("debit"),
            total_credit=Sum("credit"),
            journal_count=Count("entry_id", distinct=True),
            journal_line_count=Count("pk"),
        )
    )


def _serialize_group(row, *, dimension):
    debit = row["total_debit"] or ZERO
    credit = row["total_credit"] or ZERO
    amount = debit - credit

    activity = {
        "amount": money(amount),
        "gross_debits": money(debit),
        "gross_credits": money(credit),
        "journal_count": row["journal_count"],
        "journal_line_count": row["journal_line_count"],
    }

    if dimension == "vendor":
        vendor_id = row["report_vendor_id"]
        return {
            "vendor_id": str(vendor_id) if vendor_id else None,
            "vendor_name": row["report_vendor_name"] or "Unattributed",
            **activity,
        }, amount

    if dimension == "account":
        return {
            "account_id": str(row["account_id"]),
            "account_code": row["account__code"],
            "account_name": row["account__name"],
            **activity,
        }, amount

    month = row["report_month"]
    if isinstance(month, datetime):
        month = month.date()

    return {
        "month": month.isoformat(),
        **activity,
    }, amount


def spend_by(
    organization,
    *,
    dimension,
    start_date,
    end_date,
    limit=20,
    currency=None,
):
    """Build posted expenditure grouped by vendor, account, or month.

    Amounts use the expense-account normal balance (debits minus credits).
    Posted journals and original journals marked reversed are included. A
    reversal journal is included on its own entry date, so it offsets the
    original expenditure in the period in which the reversal was recorded.
    Amounts are kept separate by currency and are never converted.

    ``limit`` is applied independently to each currency. Vendor and account
    groups are ranked by amount, highest first. Month groups return the most
    recent months in chronological order. Currency totals are calculated
    before the per-currency row limit is applied.
    """
    currency = _validate_spend_params(
        organization=organization,
        dimension=dimension,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        currency=currency,
    )

    queryset = JournalLine.objects.filter(
        entry__organization_id=organization.pk,
        entry__status__in=REPORTABLE_STATUSES,
        entry__entry_date__gte=start_date,
        entry__entry_date__lte=end_date,
        account__organization_id=organization.pk,
        account__account_type=Account.AccountType.EXPENSE,
    )

    if currency:
        queryset = queryset.filter(entry__currency=currency)

    currency_totals = (
        queryset.values("entry__currency")
        .annotate(
            gross_debits=Sum("debit"),
            gross_credits=Sum("credit"),
            journal_count=Count("entry_id", distinct=True),
            journal_line_count=Count("pk"),
        )
    )

    currency_metrics = {
        row["entry__currency"] or "UNKNOWN": row
        for row in currency_totals
    }

    if dimension == "vendor":
        grouped_rows = _vendor_grouped_rows(
            queryset, organization_id=organization.pk
        )
    elif dimension == "account":
        grouped_rows = _account_grouped_rows(queryset)
    else:
        grouped_rows = _month_grouped_rows(queryset)

    grouped_by_currency = {}
    for row in grouped_rows:
        currency_code = row["entry__currency"] or "UNKNOWN"
        serialized, amount = _serialize_group(row, dimension=dimension)
        bucket = grouped_by_currency.setdefault(
            currency_code,
            {"rows": []},
        )
        bucket["rows"].append((serialized, amount))

    # Preserve the organisation's reporting currency for an empty unfiltered
    # Preserve the organisation's reporting currency for an empty report.
    if not grouped_by_currency:
        empty_currency = currency or organization.default_currency
        if empty_currency:
            grouped_by_currency[empty_currency] = {
                "rows": [],
            }

    currency_reports = []

    for currency_code in sorted(grouped_by_currency):
        bucket = grouped_by_currency[currency_code]
        all_rows = bucket["rows"]

        if dimension == "month":
            all_rows.sort(key=lambda item: item[0]["month"])
            selected_rows = all_rows[-limit:]
        else:
            all_rows.sort(
                key=lambda item: (
                    -item[1],
                    item[0].get("vendor_name", "")
                    or item[0].get("account_code", ""),
                    item[0].get("vendor_id", "") or "",
                )
            )
            selected_rows = all_rows[:limit]

        metrics = currency_metrics.get(currency_code, {})

        gross_debits = metrics.get("gross_debits") or ZERO
        gross_credits = metrics.get("gross_credits") or ZERO

        total_expenditure = gross_debits - gross_credits

        displayed_rows_expenditure = sum(
            (amount for _row, amount in selected_rows),
            ZERO,
        )

        currency_reports.append({
            "currency": currency_code,
            "rows": [row for row, _amount in selected_rows],
            "total_expenditure": money(total_expenditure),
            "gross_debits": money(gross_debits),
            "gross_credits": money(gross_credits),
            "journal_count": metrics.get("journal_count", 0),
            "journal_line_count": metrics.get(
                "journal_line_count", 0
            ),
            "displayed_rows_expenditure": money(
                displayed_rows_expenditure
            ),
            "group_count": len(all_rows),
            "returned_group_count": len(selected_rows),
            "is_truncated": len(all_rows) > len(selected_rows),
        })

    return {
        "dimension": dimension,
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "limit_per_currency": limit,
        "currencies": currency_reports,
        "report_basis": (
            "Expenditure is calculated from expense-account journal "
            "lines using debits minus credits. Gross debits and gross "
            "credits show the underlying expense activity before netting. "
            "Journal count is the number of distinct journals containing "
            "expense lines; journal-line count is the number of included "
            "expense-account lines. "
            "Posted journals and original journals marked reversed are "
            "included. A reversal journal is included on its own entry "
            "date, so both the original and reversal remain visible in "
            "historical reporting. Draft journals are excluded. "
            "Reversal journals are attributed to the original invoice "
            "vendor when one exists. "
            "Linked adjustment journals are attributed through their "
            "original-journal chain to the source invoice vendor when one "
            "exists and belongs to the same organisation. "
            "Other non-invoice expenditure is grouped as Unattributed "
            "when reporting by vendor. Amounts are reported separately "
            "by currency without conversion. "
            "Displayed rows expenditure is the sum of the selected "
            "returned groups and may differ from total expenditure "
            "when the report is truncated."
        ),
    }
