from decimal import Decimal
from typing import Annotated, Literal
from datetime import date
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


ConfidenceScore = Annotated[
    float,
    Field(ge=0, le=1),
]


class SourceEvidence(BaseModel):
    """
    Identifies where an extracted value came from.
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(ge=1)

    quote: str = Field(
        min_length=1,
        max_length=1000,
    )


class ExtractedTax(BaseModel):
    """
    An individual tax component appearing on an invoice.

    Treatment is important because an additive tax such as VAT
    differs from a deduction such as withholding tax.
    """

    model_config = ConfigDict(extra="forbid")

    name: str

    tax_type: str = Field(
        description="For example VAT, WHT or another levy."
    )

    treatment: Literal[
        "added",
        "deducted",
        "included",
        "withheld",
        "unknown",
    ] = "unknown"

    rate_percent: Decimal | None = None

    amount: Decimal | None = None


class ExtractedLineItem(BaseModel):

    model_config = ConfigDict(extra="forbid")

    description: str

    quantity: Decimal | None = None

    unit_of_measure: str | None = None

    unit_price: Decimal | None = None

    tax_rate_percent: Decimal | None = None

    line_total: Decimal | None = None

    suggested_expense_category: str | None = None


class InvoiceExtractionResult(BaseModel):
    """
    Structured output expected from the invoice AI extractor.

    Missing information remains None. It must never be silently
    converted into zero or an invented value.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    # Supplier information

    supplier_legal_name: str | None = None

    supplier_tin: str | None = None

    supplier_address: str | None = None

    # Invoice identification

    invoice_number: str | None = None

    invoice_date: str | None = None

    due_date: str | None = None

    purchase_order_number: str | None = None

    currency: str | None = Field(
        default=None,
        description="Three-letter ISO currency code, for example NGN or USD.",
    )

    # Financial information

    subtotal: Decimal | None = None

    taxes: list[ExtractedTax] | None = None

    other_charges: Decimal | None = None

    total_amount: Decimal | None = None

    amount_due: Decimal | None = None

    # Additional information

    payment_terms: str | None = None

    description: str | None = None

    line_items: list[ExtractedLineItem] | None = None

    # Extraction evidence

    field_confidence: dict[str, ConfidenceScore] = Field(
        default_factory=dict,
    )

    field_evidence: dict[str, list[SourceEvidence]] = Field(
        default_factory=dict,
    )

    extraction_warnings: list[str] = Field(
        default_factory=list,
    )

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value):
        if value is None:
            return None

        value = value.strip().upper()

        if len(value) != 3 or not value.isalpha():
            raise ValueError(
                "Currency must be a three-letter code."
            )

        return value

    @field_validator("invoice_date", "due_date")
    @classmethod
    def validate_date_format(cls, value):
        if value is None:
            return None

        from datetime import date

        try:
            return date.fromisoformat(value).isoformat()

        except ValueError as exc:
            raise ValueError(
                "Date must use ISO format YYYY-MM-DD."
            ) from exc