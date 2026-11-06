import hashlib

import pymupdf

from PIL import Image, UnidentifiedImageError
from django.conf import settings


class UploadValidationError(Exception):
    """Raised when an uploaded document is invalid."""


SUPPORTED_TYPES = {
    ".pdf": {
        "content_type": "application/pdf",
        "extension": ".pdf",
    },
    ".png": {
        "content_type": "image/png",
        "extension": ".png",
    },
    ".jpg": {
        "content_type": "image/jpeg",
        "extension": ".jpg",
    },
    ".jpeg": {
        "content_type": "image/jpeg",
        "extension": ".jpeg",
    },
}


def validate_invoice_file(uploaded_file):
    """
    Validate file size, extension and actual file content.

    Returns:
        tuple[str, str]: sanitized filename and detected MIME type.
    """

    if uploaded_file.size <= 0:
        raise UploadValidationError("The uploaded file is empty.")

    max_size = settings.MAX_INVOICE_UPLOAD_SIZE

    if uploaded_file.size > max_size:
        raise UploadValidationError(
            "File exceeds the maximum allowed size of 10 MB."
        )

    original_name = (
        uploaded_file.name.replace("\\", "/").split("/")[-1]
    )

    extension = original_name.rsplit(".", 1)[-1].lower()

    if "." not in original_name:
        raise UploadValidationError(
            "The file must have a supported extension."
        )

    extension = f".{extension}"

    if extension not in SUPPORTED_TYPES:
        raise UploadValidationError(
            "Only PDF, PNG and JPEG files are supported."
        )

    uploaded_file.seek(0)
    header = uploaded_file.read(16)
    uploaded_file.seek(0)

    if header.startswith(b"%PDF-"):
        detected_extension = ".pdf"

        try:
            raw_content = uploaded_file.read()
            uploaded_file.seek(0)

            pdf = pymupdf.open(
                stream=raw_content,
                filetype="pdf",
            )

            try:
                if pdf.is_encrypted:
                    raise UploadValidationError(
                        "Password-protected PDFs are not supported."
                    )

                if pdf.page_count < 1:
                    raise UploadValidationError(
                        "The PDF contains no pages."
                    )

                max_pages = getattr(
                    settings,
                    "MAX_INVOICE_PDF_PAGES",
                    100,
                )

                if pdf.page_count > max_pages:
                    raise UploadValidationError(
                        f"PDF exceeds the maximum of {max_pages} pages."
                    )

            finally:
                pdf.close()

        except UploadValidationError:
            raise

        except Exception as exc:
            raise UploadValidationError(
                "The PDF could not be opened or validated."
            ) from exc

    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_extension = ".png"

    elif header.startswith(b"\xff\xd8\xff"):
        detected_extension = ".jpg"

    else:
        raise UploadValidationError(
            "The file content does not match a supported document type."
        )

    if (
        detected_extension == ".jpg"
        and extension not in {".jpg", ".jpeg"}
    ) or (
        detected_extension != ".jpg"
        and detected_extension != extension
    ):
        raise UploadValidationError(
            "The file extension does not match its actual content."
        )

    if detected_extension in {".jpg", ".png"}:
        try:
            with Image.open(uploaded_file) as image:
                image.verify()

        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
        ) as exc:
            raise UploadValidationError(
                "The image could not be decoded or validated."
            ) from exc

        finally:
            uploaded_file.seek(0)

    return (
        original_name[:255],
        SUPPORTED_TYPES[detected_extension]["content_type"],
    )


def calculate_sha256(uploaded_file):
    """Calculate the SHA-256 hash of an uploaded file."""

    digest = hashlib.sha256()

    uploaded_file.seek(0)

    for chunk in uploaded_file.chunks():
        digest.update(chunk)

    uploaded_file.seek(0)

    return digest.hexdigest()