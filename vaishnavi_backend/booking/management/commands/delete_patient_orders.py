"""
Place at: booking/management/commands/delete_patient_orders.py
(make sure management/__init__.py and management/commands/__init__.py exist)

Usage:
    python manage.py delete_patient_orders --patient-ids 12 45 78 --booking-type IN_HOUSE --dry-run
    python manage.py delete_patient_orders --patient-ids 12 45 78 --booking-type CLIENT_SIDE
    python manage.py delete_patient_orders --patient-ids 12 45 78 --booking-type IN_HOUSE --yes
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from booking.models import PrimaryOrder, SecondaryOrder, TotalInvoice, Payment


class Command(BaseCommand):
    help = (
        "Delete primary orders (with their secondary orders and invoices) for "
        "the given patient IDs and a single booking type. Payments are kept "
        "but unlinked from the deleted invoices."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--patient-ids",
            nargs="+",
            type=int,
            required=True,
            help="One or more patient IDs, e.g. 12 45 78",
        )
        parser.add_argument(
            "--booking-type",
            required=True,
            choices=["IN_HOUSE", "CLIENT_SIDE"],
            help="Booking type applied to all the patient IDs.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be affected without changing anything.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip the confirmation prompt.",
        )

    def handle(self, *args, **options):
        patient_ids = list(dict.fromkeys(options["patient_ids"]))  # de-dupe
        booking_type = options["booking_type"]

        primary_ids = list(
            PrimaryOrder.objects.filter(
                patient_id__in=patient_ids, booking_type=booking_type
            ).values_list("id", flat=True)
        )
        if not primary_ids:
            self.stdout.write(self.style.WARNING("No matching primary orders found."))
            return

        secondary_ids = list(
            SecondaryOrder.objects.filter(primary_order_id__in=primary_ids)
            .values_list("id", flat=True)
        )
        invoice_ids = list(
            TotalInvoice.objects.filter(secondary_order_id__in=secondary_ids)
            .values_list("id", flat=True)
        )
        payment_count = Payment.objects.filter(invoice_id__in=invoice_ids).count()

        self.stdout.write(f"Patients      : {patient_ids}")
        self.stdout.write(f"Booking type  : {booking_type}")
        self.stdout.write(f"  Primary orders   : {primary_ids}")
        self.stdout.write(f"  Secondary orders : {secondary_ids}")
        self.stdout.write(f"  Invoices         : {invoice_ids}")
        self.stdout.write(f"  Payments to unlink (invoice -> NULL): {payment_count}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run only. Nothing changed."))
            return

        if not options["yes"]:
            answer = input("Proceed with deletion? Type 'yes' to confirm: ")
            if answer.strip().lower() != "yes":
                self.stdout.write("Aborted.")
                return

        with transaction.atomic():
            # 1. Detach payments from invoices (payments are kept)
            unlinked = Payment.objects.filter(invoice_id__in=invoice_ids).update(
                invoice=None
            )
            # 2. Delete invoices -> secondary orders -> primary orders
            TotalInvoice.objects.filter(id__in=invoice_ids).delete()
            SecondaryOrder.objects.filter(id__in=secondary_ids).delete()
            PrimaryOrder.objects.filter(id__in=primary_ids).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Deleted {len(primary_ids)} primary, "
                f"{len(secondary_ids)} secondary, {len(invoice_ids)} invoices; "
                f"unlinked {unlinked} payments."
            )
        )