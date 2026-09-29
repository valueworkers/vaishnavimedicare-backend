"""
Usage:
    python manage.py resolve_conflicting_orders                      # dry run
    python manage.py resolve_conflicting_orders --apply              # write changes
    python manage.py resolve_conflicting_orders --keep 63 --remove 1666 [--apply]
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from booking.models import PrimaryOrder, SecondaryOrder, TotalInvoice

# ---- ADJUST TO YOUR MODELS --------------------------------------------------
INVOICE_SECONDARY_FK = "secondary_order"   # FK on TotalInvoice -> SecondaryOrder (SINV = secondary invoice)
PAID_STATUSES = ["PAID"]
EXCLUDED_STATUSES = ["CANCELLED"]          # primary orders ignored when looking for conflicts
# -----------------------------------------------------------------------------


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def has_payments(invoice):
    mgr = getattr(invoice, "payment_set", None) or getattr(invoice, "payments", None)
    return mgr.exists() if mgr is not None else False


class Command(BaseCommand):
    help = "Remove primary orders that conflict (overlap) with an older order of the same patient/package."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes (default is dry run).")
        parser.add_argument("--keep", type=int, help="PrimaryOrder id to keep (use with --remove).")
        parser.add_argument("--remove", type=int, help="PrimaryOrder id to remove (use with --keep).")

    # ------------------------------------------------------------------ helpers
    def log(self, msg):
        self.stdout.write(msg)

    def dedupe_invoices(self, secondary_id):
        invoices = list(
            TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: secondary_id}).order_by("id")
        )
        if len(invoices) < 2:
            return 0
        paid = [i for i in invoices if i.status in PAID_STATUSES]
        unpaid = [i for i in invoices if i.status not in PAID_STATUSES]
        deletable = [i for i in unpaid if not has_payments(i)]
        if not paid and len(deletable) == len(invoices):
            deletable = deletable[1:]          # all unpaid -> keep the oldest
        if deletable:
            self.log(f"      delete unpaid duplicate invoice(s) {[i.invoice_number for i in deletable]}")
            TotalInvoice.objects.filter(pk__in=[i.pk for i in deletable]).delete()
        return len(deletable)

    def resolve_pair(self, keeper, victim):
        """Merge `victim` into `keeper`. Returns number of invoices deleted."""
        deleted_invoices = 0
        keeper_secs = list(SecondaryOrder.objects.filter(primary_order_id=keeper.pk))
        victim_secs = list(SecondaryOrder.objects.filter(primary_order_id=victim.pk))
        conflicts = 0

        for sv in victim_secs:
            match = next(
                (sk for sk in keeper_secs
                 if overlaps(sv.start_datetime, sv.end_datetime, sk.start_datetime, sk.end_datetime)),
                None,
            )
            if match is None:
                # no clash: just move it under the kept order
                SecondaryOrder.objects.filter(pk=sv.pk).update(primary_order_id=keeper.pk)
                self.log(f"    secondary {sv.pk} has no clash -> moved to order {keeper.pk}")
                continue

            ternary = getattr(sv, "ternary_orders", None)
            if ternary is not None and ternary.exists():
                raise CommandError(
                    f"Secondary {sv.pk} (order {victim.pk}) has ternary orders - resolve those manually first."
                )

            conflicts += 1
            self.log(f"    secondary {sv.pk} ({sv.start_datetime:%d %b %Y}->{sv.end_datetime:%d %b %Y}) "
                     f"conflicts with kept secondary {match.pk}")

            moved = TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: sv.pk})
            for inv in moved:
                self.log(f"      move invoice {inv.invoice_number} [{inv.status}] total={inv.total_amount} "
                         f"-> secondary {match.pk}")
                if inv.status in PAID_STATUSES and inv.total_amount != match.subtotal:
                    self.log(self.style.WARNING(
                        f"      !! paid invoice total {inv.total_amount} != kept secondary subtotal "
                        f"{match.subtotal} - review amount manually"))
            moved.update(**{INVOICE_SECONDARY_FK: match.pk})
            deleted_invoices += self.dedupe_invoices(match.pk)
            sv.delete()

        if conflicts == 0:
            self.log(f"    order {victim.pk}: no overlapping secondaries, nothing to do")
            return deleted_invoices

        if not SecondaryOrder.objects.filter(primary_order_id=victim.pk).exists():
            self.log(f"    delete conflicting order {victim.pk} ({victim.order_id})")
            victim.delete()
        return deleted_invoices

    # ------------------------------------------------------------------ main
    def handle(self, *args, **opts):
        apply_changes = opts["apply"]
        pairs = []

        if opts["keep"] or opts["remove"]:
            if not (opts["keep"] and opts["remove"]):
                raise CommandError("--keep and --remove must be given together.")
            pairs.append((PrimaryOrder.objects.get(pk=opts["keep"]),
                          PrimaryOrder.objects.get(pk=opts["remove"])))
        else:
            seen = {}
            qs = PrimaryOrder.objects.exclude(status__in=EXCLUDED_STATUSES).order_by("created_at", "id")
            for po in qs:
                key = (po.patient_id, po.service_id, po.package_id, po.venue_id, po.booking_type)
                seen.setdefault(key, []).append(po)
            for key, orders in seen.items():
                if len(orders) < 2:
                    continue
                keeper = orders[0]                       # oldest wins
                for victim in orders[1:]:
                    if overlaps(keeper.start_datetime, keeper.end_datetime,
                                victim.start_datetime, victim.end_datetime):
                        pairs.append((keeper, victim))

        total_inv = 0
        with transaction.atomic():
            for keeper, victim in pairs:
                self.log(f"Conflict: keep {keeper.pk} ({keeper.booking_entity}) / "
                         f"remove {victim.pk} ({victim.booking_entity}) patient={keeper.patient_id}")
                total_inv += self.resolve_pair(keeper, victim)
            if not apply_changes:
                transaction.set_rollback(True)          # dry run runs the real code, then rolls back

        mode = "APPLIED" if apply_changes else "DRY RUN (rolled back)"
        self.log(self.style.SUCCESS(
            f"[{mode}] {len(pairs)} conflicting order pair(s), {total_inv} unpaid duplicate invoice(s) deleted."))