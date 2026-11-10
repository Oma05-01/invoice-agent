from auditlog.models import InvoiceAuditEvent

invoice_id = "0cb01936-8acc-4a13-858a-8c31f47d6d69"

events = (
    InvoiceAuditEvent.objects
    .filter(invoice_id=invoice_id)
    .select_related("actor")
    .order_by("created_at")
)

print(f"\nClearWave invoice audit events: {events.count()}")

for event in events:
    print("\n" + "-" * 65)
    print("Timestamp:", event.created_at)
    print("Action:", event.action)
    print(
        "Actor:",
        event.actor.username if event.actor else "Unknown",
    )
    print("Changes:", event.changes)
    print("Metadata:", event.metadata)
