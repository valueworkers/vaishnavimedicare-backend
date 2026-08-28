# management/commands/sync_order_statuses.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from dateutil.relativedelta import relativedelta
from datetime import timedelta
from decimal import Decimal

from booking.models import PrimaryOrder, SecondaryOrder, TotalInvoice
from booking.constants import BookingStatus


class Command(BaseCommand):
    help = """
    Syncs order statuses based on current time. Also auto-extends fulfilled orders with auto_continue=True.
    
    # Sync all active orders
    python manage.py sync_order_statuses
    # Dry run — preview only
    python manage.py sync_order_statuses --dry-run
    # Target a single order
    python manage.py sync_order_statuses --order-id ORD-0001
    # Both
    python manage.py sync_order_statuses --order-id ORD-0001 --dry-run
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to DB.",
        )
        parser.add_argument(
            "--order-id",
            type=str,
            help="Run for a single PrimaryOrder by order_id.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        order_id = options.get("order_id")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be saved.\n"))

        qs = PrimaryOrder.objects.filter(
            status__in=[
                BookingStatus.YET_TO_START,
                BookingStatus.IN_PROGRESS,
                BookingStatus.FULFILLED,
            ]
        ).prefetch_related("secondary_orders")

        if order_id:
            qs = qs.filter(order_id=order_id)
            if not qs.exists():
                self.stdout.write(self.style.ERROR(f"No active PrimaryOrder found with order_id={order_id}"))
                return

        total = qs.count()
        self.stdout.write(f"Processing {total} order(s)...\n")

        synced = 0
        extended = 0
        errors = 0

        for primary in qs:
            try:
                was_extended = self._sync(primary, dry_run)
                synced += 1
                if was_extended:
                    extended += 1
            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(f"  [ERROR] {primary.order_id}: {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. synced={synced}, auto-extended={extended}, errors={errors}"
            )
        )

    # ── Core sync ──────────────────────────────────────────────────────────────

    def _sync(self, primary: PrimaryOrder, dry_run: bool) -> bool:
        """Returns True if order was auto-extended."""
        now = timezone.now()

        # Step 1: Compute new statuses for unlocked secondaries
        secondaries = list(primary.secondary_orders.filter(status_locked=False))
        updates = []

        for sec in secondaries:
            new_status = self._compute_status(sec.start_datetime, sec.end_datetime, now)
            if sec.status != new_status:
                self.stdout.write(
                    f"  [SECONDARY] {sec.order_id}: {sec.status} → {new_status}"
                )
                sec.status = new_status
                updates.append(sec)

        fulfilled_orders = []

        if updates and not dry_run:
            SecondaryOrder.objects.bulk_update(updates, ["status"])

            # Generate invoices only for orders that are now fulfilled
            for sec in updates:
                if sec.status == BookingStatus.FULFILLED:
                    fulfilled_orders.append(sec)

        # Step 2: Derive primary status
        all_statuses = {s.status for s in secondaries}
        derived = self._derive_primary_status(all_statuses)

        if not primary.status_locked and primary.status != derived:
            self.stdout.write(
                f"  [PRIMARY]   {primary.order_id}: {primary.status} → {derived}"
            )
            if not dry_run:
                PrimaryOrder.objects.filter(pk=primary.pk).update(status=derived)
            primary.status = derived
            
            # Generate invoices
            if not dry_run:
                for sec in fulfilled_orders:
                    self._generate_invoice(sec)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [INVOICE]   {sec.order_id}"
                        )
                    )

        # Step 3: Auto-continue if fulfilled
        if (
            primary.auto_continue
            and not primary.status_locked
            and primary.status == BookingStatus.FULFILLED
        ):
            return self._extend(primary, dry_run)

        return False

    # ── Status helpers ─────────────────────────────────────────────────────────

    def _compute_status(self, start, end, now):
        if now < start:
            return BookingStatus.YET_TO_START
        elif start <= now <= end:
            return BookingStatus.IN_PROGRESS
        elif now > end:
            return BookingStatus.FULFILLED
        return BookingStatus.LOBBY

    def _derive_primary_status(self, statuses: set) -> str:
        if not statuses:
            return BookingStatus.LOBBY
        if statuses == {BookingStatus.FULFILLED}:
            return BookingStatus.FULFILLED
        if BookingStatus.IN_PROGRESS in statuses:
            return BookingStatus.IN_PROGRESS
        if statuses == {BookingStatus.YET_TO_START}:
            return BookingStatus.YET_TO_START
        if BookingStatus.FULFILLED in statuses and BookingStatus.YET_TO_START in statuses:
            return BookingStatus.IN_PROGRESS  # straddling
        return BookingStatus.LOBBY

    # ── Auto-extend ────────────────────────────────────────────────────────────

    def _extend(self, primary: PrimaryOrder, dry_run: bool) -> bool:
        # Idempotency guard
        already_extended = primary.secondary_orders.filter(
            start_datetime__gte=primary.end_datetime
        ).exists()

        if already_extended:
            self.stdout.write(
                f"  [SKIP]      {primary.order_id}: already extended beyond {primary.end_datetime}"
            )
            return False

        new_start = primary.end_datetime + timedelta(seconds=1)
        new_end = primary.end_datetime + relativedelta(months=1)

        self.stdout.write(
            self.style.SUCCESS(
                f"  [EXTEND]    {primary.order_id}: {primary.end_datetime} → {new_end}"
            )
        )

        if dry_run:
            return True

        with transaction.atomic():
            PrimaryOrder.objects.filter(pk=primary.pk).update(end_datetime=new_end)
            primary.end_datetime = new_end

            # Temporarily shift start so generation only covers the new window
            original_start = primary.start_datetime
            primary.start_datetime = new_start

            primary.generate_secondary_full_range_dates(
                upcoming_only=False,
                secondary_status=BookingStatus.YET_TO_START,
            )

            primary.start_datetime = original_start  # restore (not persisted)

        return True
    
    # ── Generate-Invoice ────────────────────────────────────────────────────────────

    def _generate_invoice(self, secondary):
        def _update():
            # Update primary total
            if secondary.primary_order_id:
                secondary.primary_order.recalculate_total()

            # Generate invoice only if it doesn't exist
            if (
                secondary.status == BookingStatus.FULFILLED
                and not secondary.invoices.exists()
            ):
                TotalInvoice.create_or_update_for_secondary(secondary)

        transaction.on_commit(_update)