from datetime import date
from pprint import pprint

from accounting.models import Account, JournalEntry, JournalAdjustment
from accounting.reporting import build_account_ledger
from auditlog.models import JournalAuditEvent

INVOICE_ID = "0cb01936-8acc-4a13-858a-8c31f47d6d69"

original = JournalEntry.objects.select_related(
    "organization", "source_invoice"
).get(source_invoice_id=INVOICE_ID)

organization_id = original.organization_id

# Discover the original journal, its reversal, and all
# adjustment journals linked directly or indirectly to it.
journal_map = {original.id: original}
adjustment_records = {}
seen_ids = {original.id}
frontier = [original]

reversal = JournalEntry.objects.filter(
    reversal_of_id=original.id
).first()

if reversal:
    journal_map[reversal.id] = reversal
    seen_ids.add(reversal.id)

for _ in range(3):
    if not frontier:
        break

    records = JournalAdjustment.objects.filter(
        original_journal_id__in=[entry.id for entry in frontier],
        organization_id=organization_id,
    ).select_related(
        "original_journal",
        "adjustment_journal",
        "created_by",
    ).order_by("created_at")

    next_frontier = []

    for record in records:
        adjustment_records[record.id] = record

        adjustment = record.adjustment_journal
        journal_map[adjustment.id] = adjustment

        if adjustment.id not in seen_ids:
            seen_ids.add(adjustment.id)
            next_frontier.append(adjustment)

    frontier = next_frontier

print("\n" + "=" * 75)
print("1. CLEARWAVE JOURNAL HISTORY")
print("=" * 75)

journals = sorted(
    journal_map.values(),
    key=lambda entry: (entry.entry_date, entry.created_at),
)

for entry in journals:
    entry.refresh_from_db()

    print(f"\nReference: {entry.reference}")
    print(f"Journal ID: {entry.id}")
    print(f"Date: {entry.entry_date}")
    print(f"Status: {entry.status}")
    print(f"Currency: {entry.currency}")
    print(f"Created: {entry.created_at}")
    print(f"Posted: {getattr(entry, 'posted_at', None)}")

    created_by = getattr(entry, "created_by", None)
    posted_by = getattr(entry, "posted_by", None)

    print(f"Created by: {created_by}")
    print(f"Posted by: {posted_by}")

    for line in entry.lines.select_related("account").order_by("line_number"):
        account = line.account

        print(
            f"  Line {line.line_number}: "
            f"{account.code if account else 'NO ACCOUNT'} - "
            f"{account.name if account else 'Unassigned'} | "
            f"Debit: {line.debit} | Credit: {line.credit}"
        )

print("\n" + "=" * 75)
print("2. ADJUSTMENT RELATIONSHIPS")
print("=" * 75)

for record in adjustment_records.values():
    print(f"\nAdjustment ID: {record.id}")
    print(f"Original: {record.original_journal.reference}")
    print(f"Adjustment: {record.adjustment_journal.reference}")
    print(f"Reason: {record.reason}")
    print(f"Created by: {record.created_by}")
    print(f"Created: {record.created_at}")

print("\n" + "=" * 75)
print("3. JOURNAL AUDIT EVENTS")
print("=" * 75)

events = JournalAuditEvent.objects.filter(
    journal_entry_id__in=list(journal_map.keys()),
    organization_id=organization_id,
).select_related(
    "actor", "journal_entry"
).order_by("created_at")

print(f"\nTotal audit events: {events.count()}")

for event in events:
    print(f"\nTimestamp: {event.created_at}")
    print(f"Journal: {event.journal_entry.reference}")
    print(f"Operation: {event.operation}")
    print(f"Actor: {event.actor}")
    print("Changes:")
    pprint(event.changes, width=110)
    print("Metadata:")
    pprint(event.metadata, width=110)

print("\n" + "=" * 75)
print("4. GENERAL LEDGER TRANSACTIONS")
print("=" * 75)

accounts = Account.objects.filter(
    organization_id=organization_id,
    code__in=["2000", "5000", "5100"],
).order_by("code")

for account in accounts:
    print(f"\n\nACCOUNT {account.code} - {account.name}")
    print("-" * 65)

    ledger = build_account_ledger(
        account=account,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 11, 10),
        currency="NGN",
    )

    pprint(ledger, width=120, sort_dicts=False)

print("\n" + "=" * 75)
print("VERIFICATION QUERY COMPLETE - NO RECORDS MODIFIED")
print("=" * 75)
