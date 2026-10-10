"""Rebuild secondary orders from their primary orders' date ranges.

Usage:
    python manage.py fix_booking_sequence                 # dry run (rolled back)
    python manage.py fix_booking_sequence --patient 22     # one patient, dry run
    python manage.py fix_booking_sequence --patient 22 --apply
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from booking.models import PrimaryOrder


class Command(BaseCommand):
    help = "Update or create secondary orders from each primary order's date range."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Commit changes (default: dry run).")
        parser.add_argument("--patient", type=int, help="Only rebuild this patient's secondary orders.")

    def handle(self, *args, **options):
        orders = PrimaryOrder.objects.select_related("package").order_by("patient_id", "id")
        if options["patient"] is not None:
            orders = orders.filter(patient_id=options["patient"])

        checked = 0
        with transaction.atomic():
            for order in orders:
                before = order.secondary_orders.count()
                if order.raw_dates:
                    order.generate_secondary_from_random_dates(order.raw_dates,prune=True)
                else:
                    order.generate_secondary_full_range_dates(prune=True)
                after = order.secondary_orders.count()
                checked += 1
                self.stdout.write(
                    f"patient:{order.patient_id} primary id:{order.pk}\t "
                    f"{before} -> {after}"
                )
                
            if not options["apply"]:
                transaction.set_rollback(True)

        mode = "APPLIED" if options["apply"] else "DRY RUN (rolled back)"
        self.stdout.write(self.style.SUCCESS(f"[{mode}] {checked} primary order(s) checked."))
