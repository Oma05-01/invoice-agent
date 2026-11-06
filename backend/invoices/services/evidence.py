import re
import unicodedata

from dataclasses import dataclass, field
from typing import Literal

from invoices.schemas import InvoiceExtractionResult


@dataclass(frozen=True)
class EvidenceFinding:

    code: str

    severity: Literal["warning", "error"]

    field_name: str

    message: str

    details: dict = field(default_factory=dict)


def normalize_text(value: str) -> str:
    """
    Normalize text for reliable quotation matching.

    Handles differences in whitespace, Unicode representation
    and letter casing.
    """

    normalized = unicodedata.normalize("NFKC", value)

    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    )

    return normalized.strip().casefold()


def verify_extraction_evidence(
    extraction: InvoiceExtractionResult,
    page_texts: dict[int, str],
) -> list[EvidenceFinding]:
    """
    Verify that the evidence quotations supplied by the AI
    exist on their referenced PDF pages.

    This verifies quotation provenance, not semantic correctness
    of the extracted field.
    """

    findings = []

    for field_name, references in (
        extraction.field_evidence or {}
    ).items():

        for reference in references:

            page_number = reference.page
            quote = reference.quote

            # ---------------------------------------------
            # 1. Check referenced page exists
            # ---------------------------------------------

            if page_number not in page_texts:

                findings.append(
                    EvidenceFinding(
                        code="EVIDENCE_PAGE_NOT_FOUND",
                        severity="warning",
                        field_name=field_name,
                        message=(
                            "The referenced page does not exist "
                            "in the extracted document."
                        ),
                        details={
                            "page": page_number,
                        },
                    )
                )

                continue

            page_text = page_texts[page_number]

            # ---------------------------------------------
            # 2. Check page contains searchable text
            # ---------------------------------------------

            if not page_text.strip():

                findings.append(
                    EvidenceFinding(
                        code="EVIDENCE_PAGE_REQUIRES_OCR",
                        severity="warning",
                        field_name=field_name,
                        message=(
                            "The referenced page has no searchable "
                            "text and requires OCR."
                        ),
                        details={
                            "page": page_number,
                        },
                    )
                )

                continue

            # ---------------------------------------------
            # 3. Verify quotation exists on page
            # ---------------------------------------------

            normalized_quote = normalize_text(quote)

            normalized_page = normalize_text(page_text)

            if normalized_quote not in normalized_page:

                findings.append(
                    EvidenceFinding(
                        code="EVIDENCE_QUOTE_NOT_FOUND",
                        severity="warning",
                        field_name=field_name,
                        message=(
                            "The supplied quotation could not "
                            "be found on its referenced page."
                        ),
                        details={
                            "page": page_number,
                            "quote": quote,
                        },
                    )
                )

    return findings