import logging

from celery import shared_task

from invoices.models import Invoice
from invoices.services.processing import process_invoice


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="invoices.process_invoice",
    ignore_result=True,
)
def process_invoice_task(
    self,
    invoice_id: str,
    expected_task_id: str,
):
    """
    Execute invoice processing in the Celery worker.
    """

    invoice = Invoice.objects.filter(
        pk=invoice_id,
    ).first()

    if invoice is None:
        logger.warning(
            "Unknown invoice ID: %s",
            invoice_id,
        )
        return

    if (
        invoice.status != Invoice.Status.QUEUED
        or str(invoice.processing_task_id) != expected_task_id
    ):
        logger.warning(
            "Ignoring stale invoice task: %s",
            invoice_id,
        )
        return

    logger.info(
        "Starting invoice processing: %s",
        invoice_id,
    )

    process_invoice(invoice_id)

    logger.info(
        "Invoice processing completed: %s",
        invoice_id,
    )