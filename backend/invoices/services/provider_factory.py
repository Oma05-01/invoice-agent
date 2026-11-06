from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from invoices.providers.groq_provider import (
    GroqInvoiceExtractionProvider,
)

from invoices.services.extraction import InvoiceExtractionService


def build_invoice_extraction_service():
    """
    Construct the configured invoice extraction service.
    """

    if not settings.GROQ_API_KEY:
        raise ImproperlyConfigured(
            "GROQ_API_KEY is not configured."
        )

    provider = GroqInvoiceExtractionProvider(
        api_key=settings.GROQ_API_KEY,
        model=settings.GROQ_MODEL,
        timeout=settings.GROQ_TIMEOUT_SECONDS,
        max_retries=settings.GROQ_MAX_RETRIES,
    )

    return InvoiceExtractionService(
        provider=provider,
    )