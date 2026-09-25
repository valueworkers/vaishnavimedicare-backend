"""
Django management command: regenerate order_id (Primary/Secondary/Ternary
orders) and backfill patient_id (Patient) codes.

/management/commands/regenerate_order_and_patient_ids.py

Why: after merging duplicate PrimaryOrders, a SecondaryOrder's
primary_order_id may now point at a different primary than the one baked
into its order_id string (e.g. "#6793492000" embeds the OLD primary id).
This recomputes order_id from the CURRENT relations, and separately fills
in any missing Patient.patient_id codes.

Uses queryset.update() rather than instance.save(), so no model signals
fire (avoids the invoice-recalculation crash seen with the ORM merge
command).

Usage:
    python manage.py regenerate_order_and_patient_ids                 # dry run, both
    python manage.py regenerate_order_and_patient_ids --apply          # apply, both
    python manage.py regenerate_order_and_patient_ids --orders-only --apply
    python manage.py regenerate_order_and_patient_ids --patients-only --apply

Adjust the import paths below to match your project.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q


from booking.models import PrimaryOrder, SecondaryOrder, TernaryOrder, Patient


class Command(BaseCommand):
    help = "Regenerate order_id for Primary/Secondary/Ternary orders and backfill Patient.patient_id"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry run.")
        parser.add_argument("--orders-only", action="store_true", help="Only regenerate order_id.")
        parser.add_argument("--patients-only", action="store_true", help="Only backfill patient_id.")

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        do_orders = not options["patients_only"]
        do_patients = not options["orders_only"]

        order_changes = []
        patient_changes = []

        if do_orders:
            # PrimaryOrder: #{id:03}000000
            for po in PrimaryOrder.objects.all().only("id", "order_id"):
                new_order_id = f"#{po.id:03}000000"
                if po.order_id != new_order_id:
                    order_changes.append((PrimaryOrder, po.id, po.order_id, new_order_id))

            # SecondaryOrder: #{primary.id:03}{id:03}000
            for so in SecondaryOrder.objects.all().only("id", "order_id", "primary_order_id"):
                if not so.primary_order_id:
                    continue
                new_order_id = f"#{so.primary_order_id:03}{so.id:03}000"
                if so.order_id != new_order_id:
                    order_changes.append((SecondaryOrder, so.id, so.order_id, new_order_id))

            # TernaryOrder: #{primary.id:03}{secondary.id:03}{id:03}
            for to in TernaryOrder.objects.select_related("secondary_order").only(
                "id", "order_id", "secondary_order_id", "secondary_order__primary_order_id"
            ):
                if not to.secondary_order_id:
                    continue
                secondary = to.secondary_order
                if not secondary.primary_order_id:
                    continue
                new_order_id = f"#{secondary.primary_order_id:03}{secondary.id:03}{to.id:03}"
                if to.order_id != new_order_id:
                    order_changes.append((TernaryOrder, to.id, to.order_id, new_order_id))

        if do_patients:
            missing = Patient.objects.all()
            for p in missing.only("id", "patient_id"):
                new_patient_id = f"{p.pk:05}"
                patient_changes.append((Patient, p.id, p.patient_id, new_patient_id))

        self.stdout.write(f"order_id changes: {len(order_changes)}")
        for model, pk, old, new in order_changes:
            self.stdout.write(f"  [{model.__name__}] id={pk}: {old!r} -> {new!r}")

        self.stdout.write(f"patient_id backfills: {len(patient_changes)}")
        for model, pk, old, new in patient_changes:
            self.stdout.write(f"  [{model.__name__}] id={pk}: {old!r} -> {new!r}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to write changes."))
            return

        with transaction.atomic():
            for model, pk, _old, new in order_changes:
                model.objects.filter(pk=pk).update(order_id=new)
            for model, pk, _old, new in patient_changes:
                model.objects.filter(pk=pk).update(patient_id=new)

        self.stdout.write(
            self.style.SUCCESS(
                f"Applied: {len(order_changes)} order_id update(s), "
                f"{len(patient_changes)} patient_id backfill(s)."
            )
        )