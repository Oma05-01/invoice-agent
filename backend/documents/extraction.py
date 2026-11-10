
from dataclasses import dataclass, field

import pymupdf


class DocumentExtractionError(Exception):
    """Base exception for document extraction failures."""


class OCRRequiredError(DocumentExtractionError):
    """Raised when document content requires OCR."""


@dataclass(frozen=True)
class PDFExtractionResult:
    text: str
    page_count: int
    pages_with_text: tuple[int, ...]
    pages_requiring_ocr: tuple[int, ...]
    page_texts: dict[int, str]

    # Preserve word positions for layout-aware extraction.
    page_words: dict[int, tuple[tuple, ...]] = field(
        default_factory=dict
    )

    # Preserve page dimensions for relative layout calculations.
    page_sizes: dict[int, tuple[float, float]] = field(
        default_factory=dict
    )


def extract_pdf_text(content: bytes) -> PDFExtractionResult:
    if not content:
        raise DocumentExtractionError(
            "The document is empty."
        )

    try:
        pdf = pymupdf.open(
            stream=content,
            filetype="pdf",
        )

    except Exception as exc:
        raise DocumentExtractionError(
            "The PDF could not be opened."
        ) from exc

    try:
        if pdf.is_encrypted:
            raise DocumentExtractionError(
                "Encrypted PDFs are not supported."
            )

        if pdf.page_count == 0:
            raise DocumentExtractionError(
                "The PDF contains no pages."
            )

        extracted_pages = []
        pages_with_text = []
        pages_requiring_ocr = []

        page_texts = {}
        page_words = {}
        page_sizes = {}

        for page_number, page in enumerate(pdf, start=1):

            page_text = page.get_text(
                "text",
                sort=True,
            ).strip()

            # Preserve the page dimensions.
            page_sizes[page_number] = (
                page.rect.width,
                page.rect.height,
            )

            # Keep the original text extraction unchanged.
            page_texts[page_number] = page_text

            # Preserve individual words and their coordinates.
            page_words[page_number] = tuple(
                page.get_text(
                    "words",
                    sort=True,
                )
            )

            if page_text:
                pages_with_text.append(page_number)

                extracted_pages.append(
                    f"[PAGE {page_number}]\n{page_text}"
                )

            else:
                pages_requiring_ocr.append(page_number)

        if not extracted_pages:
            raise OCRRequiredError(
                "No searchable text found. OCR is required."
            )

        return PDFExtractionResult(
            text="\n\n".join(extracted_pages),
            page_count=pdf.page_count,
            pages_with_text=tuple(pages_with_text),
            pages_requiring_ocr=tuple(pages_requiring_ocr),
            page_texts=page_texts,
            page_words=page_words,
            page_sizes=page_sizes,
        )

    finally:
        pdf.close()

