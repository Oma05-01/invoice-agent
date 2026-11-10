from django.core.management.base import BaseCommand
from django.db import transaction
from organizations.models import Organization
from vendors.models import Vendor

class Command(BaseCommand):
    help = "Seeds the 11 known fictional vendors for the FIN-01 invoice test pack."

    def handle(self, *args, **options):
        ORGANIZATION_NAME = "Demo Engineering Company"
        VENDORS = [
            {
                "vendor_code": "DEMO-TEST-001",
                "legal_name": "Northstar Office Supplies Ltd",
                "display_name": "Northstar Office Supplies",
                "email": "ap@northstar.example",
            },
            {
                "vendor_code": "DEMO-TEST-002",
                "legal_name": "Meridian Advisory Partners Ltd",
                "display_name": "Meridian Advisory Partners",
                "email": "ap@meridian.example",
            },
            {
                "vendor_code": "DEMO-TEST-003",
                "legal_name": "BrightPath Logistics Services Ltd",
                "display_name": "BrightPath Logistics Services",
                "email": "ap@brightpath.example",
            },
            {
                "vendor_code": "DEMO-TEST-004",
                "legal_name": "Cedarline Technology Services Ltd",
                "display_name": "Cedarline Technology Services",
                "email": "ap@cedarline.example",
            },
            {
                "vendor_code": "DEMO-TEST-005",
                "legal_name": "DeltaPrint Media House Ltd",
                "display_name": "DeltaPrint Media House",
                "email": "ap@deltaprint.example",
            },
            {
                "vendor_code": "DEMO-TEST-006",
                "legal_name": "Greenfield Catering & Events Ltd",
                "display_name": "Greenfield Catering & Events",
                "email": "ap@greenfield.example",
            },
            {
                "vendor_code": "DEMO-TEST-007",
                "legal_name": "BluePeak Facilities Management Ltd",
                "display_name": "BluePeak Facilities Management",
                "email": "ap@bluepeak.example",
            },
            {
                "vendor_code": "DEMO-TEST-008",
                "legal_name": "ClearWave Digital Systems Ltd",
                "display_name": "ClearWave Digital Systems",
                "email": "ap@clearwave.example",
            },
            {
                "vendor_code": "DEMO-TEST-009",
                "legal_name": "Nexus Courier & Logistics Ltd",
                "display_name": "Nexus Courier & Logistics",
                "email": "ap@nexus.example",
            },
            {
                "vendor_code": "DEMO-TEST-010",
                "legal_name": "Riverbend Safety Equipment Ltd",
                "display_name": "Riverbend Safety Equipment",
                "email": "ap@riverbend.example",
            },
            {
                "vendor_code": "DEMO-TEST-011",
                "legal_name": "Lumen Creative Works Ltd",
                "display_name": "Lumen Creative Works",
                "email": "ap@lumen.example",
            },
        ]

        try:
            with transaction.atomic():
                # FIXED: active=True -> is_active=True
                matching_organizations = Organization.objects.filter(
                    name=ORGANIZATION_NAME,
                    is_active=True,
                )
                organization_count = matching_organizations.count()

                if organization_count != 1:
                    self.stderr.write(self.style.ERROR(
                        f"Expected exactly one active organization named {ORGANIZATION_NAME!r}; "
                        f"found {organization_count}. No vendors were created."
                    ))
                    return

                organization = matching_organizations.get()
                self.stdout.write(f"Tenant: {organization.name} ({organization.id})")

                created_count = 0
                reused_count = 0
                updated_count = 0

                for vendor_data in VENDORS:
                    vendor_code = vendor_data["vendor_code"]
                    legal_name = vendor_data["legal_name"]

                    vendor = Vendor.objects.filter(
                        organization=organization,
                        vendor_code=vendor_code,
                    ).first()

                    if vendor is not None:
                        if vendor.legal_name != legal_name:
                            self.stderr.write(self.style.ERROR(
                                f"Vendor code collision for {vendor_code}: existing name is "
                                f"{vendor.legal_name!r}, expected {legal_name!r}. Rolled back."
                            ))
                            raise transaction.TransactionManagementError()
                        if not vendor.is_active:
                            self.stderr.write(self.style.ERROR(
                                f"{legal_name} exists but is inactive. Rolled back."
                            ))
                            raise transaction.TransactionManagementError()
                        reused_count += 1
                        self.stdout.write(f"REUSED  {vendor_code}  {legal_name}")
                        continue

                    same_name = Vendor.objects.filter(
                        organization=organization,
                        legal_name=legal_name,
                    )
                    same_name_count = same_name.count()

                    if same_name_count > 1:
                        self.stderr.write(self.style.ERROR(
                            f"Multiple vendors named {legal_name!r} exist. Rolled back."
                        ))
                        raise transaction.TransactionManagementError()

                    if same_name_count == 1:
                        vendor = same_name.get()
                        if vendor.vendor_code and vendor.vendor_code != vendor_code:
                            self.stderr.write(self.style.ERROR(
                                f"{legal_name} exists with different code {vendor.vendor_code!r}. Rolled back."
                            ))
                            raise transaction.TransactionManagementError()
                        if not vendor.is_active:
                            self.stderr.write(self.style.ERROR(
                                f"{legal_name} is inactive. Rolled back."
                            ))
                            raise transaction.TransactionManagementError()

                        changed_fields = []
                        if not vendor.vendor_code:
                            vendor.vendor_code = vendor_code
                            changed_fields.append("vendor_code")
                        if not vendor.display_name:
                            vendor.display_name = vendor_data["display_name"]
                            changed_fields.append("display_name")
                        if not vendor.email:
                            vendor.email = vendor_data["email"]
                            changed_fields.append("email")

                        if changed_fields:
                            vendor.save(update_fields=changed_fields + ["updated_at"])
                            updated_count += 1
                            self.stdout.write(f"UPDATED {vendor_code}  {legal_name}")
                        else:
                            reused_count += 1
                            self.stdout.write(f"REUSED  {vendor_code}  {legal_name}")
                        continue

                    Vendor.objects.create(
                        organization=organization,
                        **vendor_data,
                        is_active=True,
                    )
                    created_count += 1
                    self.stdout.write(f"CREATED {vendor_code}  {legal_name}")

                expected_codes = [item["vendor_code"] for item in VENDORS]
                verified_count = Vendor.objects.filter(
                    organization=organization,
                    vendor_code__in=expected_codes,
                    is_active=True,
                ).count()

                if verified_count != len(VENDORS):
                    self.stderr.write(self.style.ERROR("Verification failed. Rolled back."))
                    raise transaction.TransactionManagementError()

                self.stdout.write(self.style.SUCCESS("\nSeed summary"))
                self.stdout.write(f"Created: {created_count} | Updated: {updated_count} | Reused: {reused_count}")
                self.stdout.write(self.style.SUCCESS(f"Verified active test vendors: {verified_count}/{len(VENDORS)}"))

        except transaction.TransactionManagementError:
            return

