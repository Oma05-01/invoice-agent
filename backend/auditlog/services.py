from auditlog.models import (
    InvoiceAuditEvent,
    JournalAuditEvent,
)


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


def record_journal_event(
    *,
    entry,
    actor=None,
    operation,
    changes=None,
    metadata=None,
):
    """
    Record an immutable accounting event for a journal entry.

    This supports both invoice-generated and standalone journals.
    """

    if entry.pk is None:
        raise ValueError(
            "Cannot audit a journal that has not been saved."
        )

    if actor is not None and not getattr(
        actor,
        "is_authenticated",
        False,
    ):
        actor = None

    event = JournalAuditEvent(
        organization_id=entry.organization_id,
        journal_entry=entry,
        actor=actor,
        operation=operation,
        changes=changes if changes is not None else {},
        metadata=metadata if metadata is not None else {},
    )

    event.full_clean()
    event.save(force_insert=True)

    return event

