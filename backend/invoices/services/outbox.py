import logging

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from invoices.models import OutboxEvent


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 8

BASE_RETRY_SECONDS = 5

MAX_RETRY_SECONDS = 300

STALE_LOCK_SECONDS = 300


def claim_pending_events(batch_size=20):
    """
    Atomically claim pending events for publication.

    Stale dispatching events are returned to pending status
    so that interrupted dispatchers do not permanently
    strand outbox records.
    """

    now = timezone.now()

    stale_cutoff = now - timedelta(
        seconds=STALE_LOCK_SECONDS
    )

    with transaction.atomic():

        # Recover stale claims from a previously interrupted
        # dispatcher.

        stale_events = OutboxEvent.objects.filter(
            status=OutboxEvent.Status.DISPATCHING,
            locked_at__lt=stale_cutoff,
        )

        stale_events.filter(
            attempts__gte=MAX_ATTEMPTS,
        ).update(
            status=OutboxEvent.Status.FAILED,
            locked_at=None,
            last_error=(
                "Dispatcher lease expired after final attempt."
            ),
        )

        stale_events.filter(
            attempts__lt=MAX_ATTEMPTS,
        ).update(
            status=OutboxEvent.Status.PENDING,
            locked_at=None,
            available_at=now,
        )

        OutboxEvent.objects.filter(
            status=OutboxEvent.Status.DISPATCHING,
            locked_at__lt=stale_cutoff,
        ).update(
            status=OutboxEvent.Status.PENDING,
            locked_at=None,
            available_at=now,
        )

        # Lock only records that are not already claimed
        # by another dispatcher.

        events = list(
            OutboxEvent.objects
            .select_for_update(skip_locked=True)
            .filter(
                status=OutboxEvent.Status.PENDING,
                available_at__lte=now,
                attempts__lt=MAX_ATTEMPTS,
            )
            .order_by("created_at")[:batch_size]
        )

        for event in events:

            event.status = OutboxEvent.Status.DISPATCHING

            event.locked_at = now

            event.attempts += 1

            event.save(
                update_fields=[
                    "status",
                    "locked_at",
                    "attempts",
                    "updated_at",
                ]
            )

    return events


def publish_event(event):
    """
    Publish a claimed outbox event to the invoice processing queue.

    The event remains DISPATCHING until the broker accepts the message
    and mark_event_published() successfully updates its state.
    """

    from invoices.tasks import process_invoice_task

    payload = event.payload or {}

    invoice_id = payload.get("invoice_id")
    task_id = payload.get("task_id")

    if not invoice_id or not task_id:
        raise ValueError(
            "Outbox event is missing invoice_id or task_id."
        )

    process_invoice_task.apply_async(
        args=(invoice_id, task_id),
        task_id=task_id,
        queue="invoice_processing",
    )


def mark_event_published(event_id):
    """
    Record successful broker publication.

    Returns the number of updated rows so the dispatcher can
    verify that the event was successfully transitioned.
    """

    return OutboxEvent.objects.filter(
        id=event_id,
        status=OutboxEvent.Status.DISPATCHING,
    ).update(
        status=OutboxEvent.Status.PUBLISHED,
        published_at=timezone.now(),
        locked_at=None,
        last_error="",
    )

def mark_event_failed(event, exc):
    """
    Schedule a bounded retry or mark the event permanently failed.
    """

    now = timezone.now()

    if event.attempts >= MAX_ATTEMPTS:

        new_status = OutboxEvent.Status.FAILED
        available_at = now

    else:

        retry_seconds = min(
            BASE_RETRY_SECONDS * (2 ** (event.attempts - 1)),
            MAX_RETRY_SECONDS,
        )

        new_status = OutboxEvent.Status.PENDING

        available_at = now + timedelta(
            seconds=retry_seconds
        )

    error_message = (
        f"{type(exc).__name__}: {str(exc)[:500]}"
    )

    return OutboxEvent.objects.filter(
        id=event.id,
        status=OutboxEvent.Status.DISPATCHING,
    ).update(
        status=new_status,
        available_at=available_at,
        locked_at=None,
        last_error=error_message,
    )


def dispatch_pending_events(batch_size=20):
    """
    Publish a batch of pending outbox events.

    Broker publication happens outside the database transaction.
    """

    events = claim_pending_events(batch_size)

    results = {
        "claimed": len(events),
        "published": 0,
        "retry_scheduled": 0,
        "failed": 0,
    }

    for event in events:

        try:

            publish_event(event)

            updated = mark_event_published(event.id)

            if updated:
                results["published"] += 1
            else:
                logger.warning(
                    "Outbox event %s was published to the broker, "
                    "but its database status was not updated.",
                    event.id,
                )

        except Exception as exc:

            logger.exception(
                "Outbox event publication failed: %s",
                event.id,
            )

            updated = mark_event_failed(event, exc)

            if updated:
                if event.attempts >= MAX_ATTEMPTS:
                    results["failed"] += 1
                else:
                    results["retry_scheduled"] += 1

    return results