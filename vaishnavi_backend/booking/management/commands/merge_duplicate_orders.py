"""
Django management command: merge duplicate PrimaryOrder rows.

/management/commands/merge_duplicate_orders.py
(create the management/ and management/commands/ dirs, each with an
empty __init__.py, if they don't already exist)

Usage:
    python manage.py merge_duplicate_orders          # dry run, prints what it would do
    python manage.py merge_duplicate_orders --apply  # actually performs the merge

Adjust the two import lines below to match where your PrimaryOrder /
SecondaryOrder models actually live.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum, Max, Count
from django.utils import timezone
from booking.models import PrimaryOrder, SecondaryOrder


class Command(BaseCommand):
    help = "Merge duplicate PrimaryOrder rows sharing (booking_entity, booking_type, package_id, patient_id, service_id)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write changes. Without this flag, runs as a dry run.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]

        dup_keys = (
            PrimaryOrder.objects.values(
                "booking_entity", "booking_type", "package_id", "patient_id", "service_id"
            )
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
        )

        total_groups = 0
        total_deleted = 0

        for key in dup_keys:
            group_qs = PrimaryOrder.objects.filter(
                booking_entity=key["booking_entity"],
                booking_type=key["booking_type"],
                package_id=key["package_id"],
                patient_id=key["patient_id"],
                service_id=key["service_id"],
            ).order_by("id")

            ids = list(group_qs.values_list("id", flat=True))
            keeper_id, dup_ids = ids[0], ids[1:]

            agg = group_qs.aggregate(
                total_bill_sum=Sum("total_bill"),
                discount_sum=Sum("discount_amount"),
                premium_sum=Sum("premium_amount"),
                latest_end=Max("end_datetime"),
            )

            self.stdout.write(
                f"Group {key}: keeper={keeper_id}, merging {dup_ids} -> "
                f"total_bill={agg['total_bill_sum']}, "
                f"discount_amount={agg['discount_sum']}, "
                f"premium_amount={agg['premium_sum']}, "
                f"end_datetime={agg['latest_end']}"
            )

            total_groups += 1
            total_deleted += len(dup_ids)

            if not apply_changes:
                continue

            with transaction.atomic():
                # STEP 1: repoint secondary orders, merging any that would
                # collide on (primary_order_id, start_datetime, end_datetime)
                for sec in SecondaryOrder.objects.filter(primary_order_id__in=dup_ids):
                    collision = (
                        SecondaryOrder.objects.filter(
                            primary_order_id=keeper_id,
                            start_datetime=sec.start_datetime,
                            end_datetime=sec.end_datetime,
                        )
                        .exclude(pk=sec.pk)
                        .first()
                    )
                    if collision:
                        collision.subtotal = collision.subtotal + sec.subtotal
                        collision.is_registration_fee = (
                            collision.is_registration_fee or sec.is_registration_fee
                        )
                        collision.updated_at = timezone.now()
                        collision.save(
                            update_fields=["subtotal", "is_registration_fee", "updated_at"]
                        )
                        sec.delete()
                    else:
                        sec.primary_order_id = keeper_id
                        sec.updated_at = timezone.now()
                        sec.save(update_fields=["primary_order_id", "updated_at"])

                # STEP 2 + STEP 3: keeper's end_datetime -> latest, totals -> summed
                PrimaryOrder.objects.filter(pk=keeper_id).update(
                    end_datetime=agg["latest_end"],
                    total_bill=agg["total_bill_sum"],
                    discount_amount=agg["discount_sum"],
                    premium_amount=agg["premium_sum"],
                    updated_at=timezone.now(),
                )

                # STEP 4: delete the remaining duplicate primary orders
                PrimaryOrder.objects.filter(pk__in=dup_ids).delete()

        mode = "APPLIED" if apply_changes else "DRY RUN"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] {total_groups} duplicate group(s) found, {total_deleted} row(s) would be removed."
            )
        )