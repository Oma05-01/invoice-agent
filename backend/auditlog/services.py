
from auditlog.models import InvoiceAuditEvent


def record_invoice_event(
    *,
    invoice,
    action,
    actor=None,
    changes=None,
    metadata=None,
):
    """
    Record an immutable business event associated with an invoice.

    Call this inside the same database transaction as the
    business operation being recorded.
    """

    if invoice.pk is None:
        raise ValueError(
            "Cannot audit an invoice that has not been saved."
        )

    if actor is not None and not getattr(
        actor,
        "is_authenticated",
        False,
    ):
        actor = None

    event = InvoiceAuditEvent(
        organization_id=invoice.organization_id,
        invoice=invoice,
        actor=actor,
        action=action,
        changes=changes if changes is not None else {},
        metadata=metadata if metadata is not None else {},
    )

    event.full_clean()
    event.save(force_insert=True)

    return event
