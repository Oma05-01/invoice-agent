import pymupdf

from django.test import SimpleTestCase

from documents.extraction import (
    extract_pdf_text,
    DocumentExtractionError,
    OCRRequiredError,
)


class PDFTextExtractionTests(SimpleTestCase):

    @staticmethod
    def generate_pdf(include_text=True):
        pdf = pymupdf.open()

        page = pdf.new_page()

        if include_text:
            page.insert_text(
                (72, 72),
                "Invoice Number: DEMO-001\n"
                "Supplier: ABC Engineering Ltd\n"
                "Total: 107500.00",
            )

        content = pdf.tobytes()

        pdf.close()

        return content

    def test_extracts_searchable_pdf_text(self):

        result = extract_pdf_text(
            self.generate_pdf()
        )

        self.assertIn(
            "DEMO-001",
            result.text,
        )

        self.assertEqual(
            result.page_count,
            1,
        )

        self.assertEqual(
            result.pages_with_text,
            (1,),
        )

        self.assertEqual(
            result.pages_requiring_ocr,
            (),
        )

    def test_identifies_pages_requiring_ocr(self):

        pdf = pymupdf.open()

        first_page = pdf.new_page()

        first_page.insert_text(
            (72, 72),
            "Invoice Number: DEMO-001",
        )

        pdf.new_page()

        content = pdf.tobytes()

        pdf.close()

        result = extract_pdf_text(content)

        self.assertEqual(
            result.pages_with_text,
            (1,),
        )

        self.assertEqual(
            result.pages_requiring_ocr,
            (2,),
        )

    def test_scanned_only_pdf_requires_ocr(self):

        with self.assertRaises(OCRRequiredError):
            extract_pdf_text(
                self.generate_pdf(include_text=False)
            )

    def test_invalid_pdf_is_rejected(self):

        with self.assertRaises(DocumentExtractionError):
            extract_pdf_text(
                b"This is not a PDF"
            )

    def test_empty_pdf_is_rejected(self):

        with self.assertRaises(DocumentExtractionError):
            extract_pdf_text(b"")