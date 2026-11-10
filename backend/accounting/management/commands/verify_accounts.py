from django.core.management.base import BaseCommand
from organizations.models import Organization
from accounting.models import Account
from accounting.services import initialize_chart_of_accounts

class Command(BaseCommand):
    help = "Initializes chart of accounts and verifies required codes for Demo Engineering Company."

    def handle(self, *args, **options):
        # 1. Locate the test organization with the correct field: is_active
        try:
            org = Organization.objects.get(
                name="Demo Engineering Company",
                is_active=True,
            )
        except Organization.DoesNotExist:
            self.stderr.write(self.style.ERROR("Organization 'Demo Engineering Company' not found or inactive."))
            return

        self.stdout.write(f"Organization: {org.name}")
        self.stdout.write(f"Organization ID: {org.id}")

        # 2. Safely initialize the starter chart of accounts
        try:
            # If the service requires a keyword argument or no arguments
            try:
                initialize_chart_of_accounts(organization=org)
            except TypeError:
                initialize_chart_of_accounts()
            
            self.stdout.write(self.style.SUCCESS("Successfully executed chart of accounts initialization."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Initialization failed: {e}"))

        # 3. Verify accounts
        self.stdout.write("\nRequired account verification:")
        required_codes = ["2000", "5000", "5100", "5200"]

        for code in required_codes:
            account = Account.objects.filter(
                organization=org,
                code=code,
            ).first()

            if account:
                self.stdout.write(
                    f"{code} | {account.name} | Active: {account.is_active}"
                )
            else:
                self.stdout.write(self.style.WARNING(f"{code} | MISSING"))
