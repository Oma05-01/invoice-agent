from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from invoices.schemas import InvoiceExtractionResult


Severity = Literal["info", "warning", "error"]

CENT = Decimal("0.01")


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    severity: Severity
    field_name: str
    message: str
    details: dict = field(default_factory=dict)


def money(value: Decimal) -> Decimal:
    """Apply conventional two-decimal currency rounding."""

    return value.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


def add_finding(
    findings: list[ValidationFinding],
    *,
    code: str,
    severity: Severity,
    field_name: str,
    message: str,
    details: dict | None = None,
):
    findings.append(
        ValidationFinding(
            code=code,
            severity=severity,
            field_name=field_name,
            message=message,
            details=details or {},
        )
    )


def validate_invoice_extraction(
    extraction: InvoiceExtractionResult,
) -> list[ValidationFinding]:
    """
    Apply deterministic validation rules to extracted invoice data.

    This function never changes the supplied extraction.
    """

    findings: list[ValidationFinding] = []

    # -------------------------------------------------
    # 1. Required information checks
    # -------------------------------------------------

    required_fields = {
        "supplier_legal_name": extraction.supplier_legal_name,
        "invoice_number": extraction.invoice_number,
        "invoice_date": extraction.invoice_date,
        "currency": extraction.currency,
        "subtotal": extraction.subtotal,
        "total_amount": extraction.total_amount,
    }

    for field_name, value in required_fields.items():

        if value is None or value == "":
            add_finding(
                findings,
                code="MISSING_REQUIRED_FIELD",
                severity="warning",
                field_name=field_name,
                message=f"Required invoice information is missing: {field_name}.",
            )

    # -------------------------------------------------
    # 2. Date consistency
    # -------------------------------------------------

    if extraction.invoice_date and extraction.due_date:

        from datetime import date

        invoice_date = date.fromisoformat(
            extraction.invoice_date
        )

        due_date = date.fromisoformat(
            extraction.due_date
        )

        if due_date < invoice_date:
            add_finding(
                findings,
                code="DUE_DATE_BEFORE_INVOICE_DATE",
                severity="warning",
                field_name="due_date",
                message="The due date is earlier than the invoice date.",
                details={
                    "invoice_date": extraction.invoice_date,
                    "due_date": extraction.due_date,
                },
            )

    # -------------------------------------------------
    # 3. Individual line-item arithmetic
    # -------------------------------------------------


    for position, item in enumerate(
        extraction.line_items or [],
        start=1,
    ):

        if (
            item.quantity is None
            or item.unit_price is None
            or item.line_total is None
        ):
            continue

        # Avoid assuming whether line-level tax is included
        # in the extracted line total.
        if (
            item.tax_rate_percent is not None
            and item.tax_rate_percent != Decimal("0")
        ):
            continue

        expected_line_total = money(
            item.quantity * item.unit_price
        )

        actual_line_total = money(item.line_total)

        if expected_line_total != actual_line_total:
            add_finding(
                findings,
                code="LINE_TOTAL_MISMATCH",
                severity="error",
                field_name=f"line_items.{position}.line_total",
                message=(
                    f"Line item {position} does not reconcile "
                    "with quantity multiplied by unit price."
                ),
                details={
                    "position": position,
                    "expected": str(expected_line_total),
                    "extracted": str(actual_line_total),
                },
            )
    # -------------------------------------------------
    # 4. Subtotal consistency
    # -------------------------------------------------

    if (
            extraction.line_items
            and extraction.subtotal is not None
        ):

            all_line_totals_available = all(
                item.line_total is not None
                for item in extraction.line_items
            )

            line_tax_is_unambiguous = all(
                item.tax_rate_percent in (None, Decimal("0"))
                for item in extraction.line_items
            )

            if (
                all_line_totals_available
                and line_tax_is_unambiguous
            ):

                expected_subtotal = money(
                    sum(
                        (
                            item.line_total
                            for item in extraction.line_items
                        ),
                        Decimal("0"),
                    )
                )

                actual_subtotal = money(extraction.subtotal)

                if expected_subtotal != actual_subtotal:
                    add_finding(
                        findings,
                        code="SUBTOTAL_MISMATCH",
                        severity="error",
                        field_name="subtotal",
                        message=(
                            "Invoice subtotal does not match "
                            "the sum of extracted line items."
                        ),
                        details={
                            "expected": str(expected_subtotal),
                            "extracted": str(actual_subtotal),
                        },
                    )
    # -------------------------------------------------
    # 5. Gross invoice total
    # -------------------------------------------------

    if (
        extraction.subtotal is not None
        and extraction.total_amount is not None
        and extraction.other_charges is not None
    ):

        tax_information_complete = (
            extraction.taxes is not None
            and all(
                tax.amount is not None
                and tax.treatment not in ("unknown", "included")
                for tax in extraction.taxes
            )
        )

        if tax_information_complete:

            added_taxes = sum(
                (
                    tax.amount
                    for tax in (extraction.taxes or [])
                    if tax.treatment == "added"
                ),
                Decimal("0"),
            )

            expected_total = money(
                extraction.subtotal
                + extraction.other_charges
                + added_taxes
            )

            actual_total = money(
                extraction.total_amount
            )

            if expected_total != actual_total:
                add_finding(
                    findings,
                    code="TOTAL_MISMATCH",
                    severity="error",
                    field_name="total_amount",
                    message=(
                        "Invoice total does not reconcile "
                        "with subtotal, additional charges "
                        "and additive taxes."
                    ),
                    details={
                        "expected": str(expected_total),
                        "extracted": str(actual_total),
                    },
                )

    # -------------------------------------------------
    # 6. Net amount due after deductions
    # -------------------------------------------------

    if (
        extraction.total_amount is not None
        and extraction.amount_due is not None
    ):

        withholding_information_complete = (
            extraction.taxes is not None
            and all(
                tax.amount is not None
                and tax.treatment not in ("unknown", "included")
                for tax in extraction.taxes
            )
        )

        if withholding_information_complete:

            deductions = sum(
                (
                    tax.amount
                    for tax in (extraction.taxes or [])
                    if tax.treatment in ("deducted", "withheld")
                ),
                Decimal("0"),
            )

            expected_amount_due = money(
                extraction.total_amount - deductions
            )

            actual_amount_due = money(
                extraction.amount_due
            )

            if expected_amount_due != actual_amount_due:
                add_finding(
                    findings,
                    code="AMOUNT_DUE_MISMATCH",
                    severity="error",
                    field_name="amount_due",
                    message=(
                        "Amount due does not reconcile with "
                        "invoice total and extracted deductions."
                    ),
                    details={
                        "expected": str(expected_amount_due),
                        "extracted": str(actual_amount_due),
                    },
                )

    return findings