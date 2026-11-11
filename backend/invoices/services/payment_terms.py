import re

from dataclasses import dataclass
from datetime import date, timedelta


INVOICE_DATE = "invoice_date"
RECEIPT_DATE = "receipt_date"
MONTH_END = "month_end"
UNKNOWN = "unknown"

DOCUMENT = "document"
CALCULATED = "calculated"


@dataclass(frozen=True)
class NormalizedPaymentTerms:
    days: int | None
    basis: str


@dataclass(frozen=True)
class DueDateResolution:
    due_date: date | None
    source: str


def normalize_payment_terms(
    terms: str | None,
) -> NormalizedPaymentTerms:
    """
    Interpret supported payment-term expressions.

    Preserve unknown or ambiguous terms rather than
    guessing their calculation basis.
    """

    if not isinstance(terms, str) or not terms.strip():
        return NormalizedPaymentTerms(
            days=None,
            basis=UNKNOWN,
        )

    value = re.sub(
        r"\s+",
        " ",
        terms,
    ).strip().casefold()

    # Compound early-payment discount terms require
    # more detailed interpretation.
    if "/" in value:
        return NormalizedPaymentTerms(
            days=None,
            basis=UNKNOWN,
        )

    # Explicit invoice-date basis.
    invoice_date_pattern = re.compile(
        r"^(?:net\s*)?(\d{1,3})\s*"
        r"(?:days?\s*)?(?:from|after)\s+"
        r"(?:the\s+)?invoice\s+date$"
    )

    match = invoice_date_pattern.fullmatch(value)

    if match:
        return NormalizedPaymentTerms(
            days=int(match.group(1)),
            basis=INVOICE_DATE,
        )

    # Explicit receipt-date basis.
    receipt_date_pattern = re.compile(
        r"^(?:net\s*)?(\d{1,3})\s*"
        r"(?:days?\s*)?(?:from|after)\s+"
        r"(?:(?:the\s+)?date\s+of\s+)?"
        r"(?:the\s+)?receipt$"
    )

    match = receipt_date_pattern.fullmatch(value)

    if match:
        return NormalizedPaymentTerms(
            days=int(match.group(1)),
            basis=RECEIPT_DATE,
        )

    # Month-end terms do not establish a precise
    # due date without a more specific payment rule.
    month_end_phrases = {
        "eom",
        "end of month",
        "at month end",
        "at the month end",
        "payment at month end",
        "due at month end",
        "due on month end",
    }

    if value in month_end_phrases:
        return NormalizedPaymentTerms(
            days=None,
            basis=MONTH_END,
        )

    # Generic Net N terms.
    net_pattern = re.compile(
        r"^net\s*(\d{1,3})(?:\s*days?)?$"
    )

    match = net_pattern.fullmatch(value)

    if match:
        return NormalizedPaymentTerms(
            days=int(match.group(1)),
            basis=UNKNOWN,
        )

    # Generic N days terms.
    days_pattern = re.compile(
        r"^(\d{1,3})\s+days?$"
    )

    match = days_pattern.fullmatch(value)

    if match:
        return NormalizedPaymentTerms(
            days=int(match.group(1)),
            basis=UNKNOWN,
        )

    return NormalizedPaymentTerms(
        days=None,
        basis=UNKNOWN,
    )


def resolve_due_date(
    *,
    explicit_due_date: date | None,
    invoice_date: date | None,
    payment_terms: NormalizedPaymentTerms,
) -> DueDateResolution:
    """
    Resolve a due date using explicit source information.

    An explicitly extracted due date always takes priority.
    Calculation is permitted only for a known invoice-date basis.
    """

    if explicit_due_date is not None:
        return DueDateResolution(
            due_date=explicit_due_date,
            source=DOCUMENT,
        )

    if (
        payment_terms.days is not None
        and payment_terms.basis == INVOICE_DATE
        and invoice_date is not None
    ):
        return DueDateResolution(
            due_date=invoice_date + timedelta(
                days=payment_terms.days
            ),
            source=CALCULATED,
        )

    return DueDateResolution(
        due_date=None,
        source="",
    )
