import time

from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from invoices.services.outbox import (
    dispatch_pending_events,
)


class Command(BaseCommand):

    help = "Dispatch pending invoice outbox events."

    def add_arguments(self, parser):

        parser.add_argument(
            "--loop",
            action="store_true",
            help="Continuously poll for pending events.",
        )

        parser.add_argument(
            "--interval",
            type=int,
            default=2,
            help="Polling interval in seconds.",
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=20,
            help="Maximum events processed per iteration.",
        )

    def handle(self, *args, **options):

        interval = options["interval"]
        batch_size = options["batch_size"]
        continuous = options["loop"]

        if interval < 1 or batch_size < 1:
            raise CommandError(
                "Interval and batch size must be positive."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Invoice outbox dispatcher started."
            )
        )

        try:

            while True:

                result = dispatch_pending_events(
                    batch_size=batch_size,
                )

                if result["claimed"]:

                    self.stdout.write(
                        "Outbox: "
                        f"claimed={result['claimed']} "
                        f"published={result['published']} "
                        f"retry_scheduled={result['retry_scheduled']} "
                        f"failed={result['failed']}"
                    )

                if not continuous:
                    break

                time.sleep(interval)

        except KeyboardInterrupt:

            self.stdout.write(
                self.style.WARNING(
                    "Outbox dispatcher stopped."
                )
            )