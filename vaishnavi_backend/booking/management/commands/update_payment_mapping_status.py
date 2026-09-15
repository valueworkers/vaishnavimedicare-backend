# booking/management/commands/update_payment_mapping_status.py

from django.core.management.base import BaseCommand
from django.db.models import Q

from booking.models import Payment
from booking.constants import PaymentMappingStatus


class Command(BaseCommand):
    help = "Update payment mapping status based on invoice and patient mapping"

    def add_arguments(self, parser):
        parser.add_argument(
            "--update",
            action="store_true",
            help="Actually update the payment mapping statuses",
        )

    def handle(self, *args, **options):
        should_update = options["update"]

        # Both invoice and patient found
        manual = Payment.objects.filter(
            invoice__isnull=False,
            patient__isnull=False,
        )

        # Only one of invoice or patient found
        review = Payment.objects.filter(
            Q(invoice__isnull=False, patient__isnull=True)
            | Q(invoice__isnull=True, patient__isnull=False)
        )

        # Neither invoice nor patient found
        unmapped = Payment.objects.filter(
            invoice__isnull=True,
            patient__isnull=True,
        )

        # Show what will be affected
        self.stdout.write(
            self.style.NOTICE(
                f"\nPayment mapping status summary:\n"
                f"MANUAL   : {manual.count()}\n"
                f"REVIEW   : {review.count()}\n"
                f"UNMAPPED : {unmapped.count()}\n"
            )
        )

        # Do not update unless --update is passed
        if not should_update:
            self.stdout.write(
                self.style.WARNING(
                    "\nDry run only. No records were updated.\n"
                    "Run with --update to apply these changes."
                )
            )
            return

        # Update MANUAL
        updated_manual = manual.exclude(
            mapping_status=PaymentMappingStatus.MANUAL
        ).update(
            mapping_status=PaymentMappingStatus.MANUAL
        )

        # Update REVIEW
        updated_review = review.exclude(
            mapping_status=PaymentMappingStatus.REVIEW
        ).update(
            mapping_status=PaymentMappingStatus.REVIEW
        )

        # Update UNMAPPED
        updated_unmapped = unmapped.exclude(
            mapping_status=PaymentMappingStatus.UNMAPPED
        ).update(
            mapping_status=PaymentMappingStatus.UNMAPPED
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPayment mapping status updated successfully:\n"
                f"MANUAL   : {updated_manual}\n"
                f"REVIEW   : {updated_review}\n"
                f"UNMAPPED : {updated_unmapped}\n"
            )
        )