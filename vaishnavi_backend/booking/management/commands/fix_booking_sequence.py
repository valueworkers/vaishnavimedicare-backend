"""
Django management command: fix_booking_sequence

booking/management/commands/fix_booking_sequence.py

ONE command that does both jobs, in this order, inside a single transaction:

  STEP 1  Resolve conflicting PrimaryOrders
          Two active orders for the same patient / service / package / venue /
          booking_type (booking_entity ignored) whose periods overlap. The OLDER
          order (created_at) is kept. In the newer order, secondaries that overlap a
          kept secondary are removed after their invoices (and payments) are moved to
          the kept secondary; unpaid duplicate invoices are then deleted (paid ones
          never; unpaid ones that have payments never; if all unpaid, oldest is kept).
          Non-clashing secondaries are moved under the kept order and the emptied
          newer order is deleted.

  STEP 2  One secondary order per month (every patient, or --patient)
          Inside each primary order, secondaries whose start falls in the same calendar
          month are duplicates. The one that carries a paid invoice/payment is kept,
          otherwise the oldest. The others are removed after their invoices are moved to
          the kept one; unpaid duplicate invoices are then deleted (same rules as step 1).
          If TWO secondaries of a month both have paid invoices/payments, nothing is
          deleted for that month - it is reported for manual review.

  STEP 3  (opt-in: --split-monthly) Split multi-month secondaries into monthly entries
          A secondary that spans N months (e.g. 27 Jun -> 25 Aug = 2 months) becomes N
          secondaries of one month each: month k starts at start + k months and ends the
          day before the next month starts; the last one keeps the original end. The
          subtotal is NOT divided: every month keeps the original subtotal. The original row
          becomes the first month; the others are clones (is_registration_fee=False).
          Existing invoices/payments are NOT split - they stay on the first month and
          a warning is printed.

  STEP 4  Sync the booking sequence dates (every patient, or --patient)
          - reports gaps / overlaps between consecutive secondaries of an order
          - --close-gaps [start|end]  closes gaps without shifting other periods
          - --fix-overlaps            pushes an overlapping secondary forward
          - always sets PrimaryOrder.start/end = earliest secondary start / latest end
          Invoice period dates follow their secondary unless --no-invoice-sync.

Usage:
    python manage.py fix_booking_sequence                               # dry run (rolled back)
    python manage.py fix_booking_sequence --patient 22                  # dry run, one patient
    python manage.py fix_booking_sequence --close-gaps --apply          # write changes
    python manage.py fix_booking_sequence --keep 63 --remove 1666 --apply
    python manage.py fix_booking_sequence --skip-resolve --close-gaps   # skip step 1
    python manage.py fix_booking_sequence --skip-monthly ...            # skip step 2
    python manage.py fix_booking_sequence --split-monthly --close-gaps  # dry run incl. splitting
"""
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from booking.models import PrimaryOrder, SecondaryOrder, TotalInvoice

# ---- ADJUST TO YOUR MODELS --------------------------------------------------
INVOICE_SECONDARY_FK = "secondary_order"   # FK on TotalInvoice -> SecondaryOrder (SINV = secondary invoice)
PAID_STATUSES = ["PAID"]
EXCLUDED_STATUSES = ["CANCELLED"]          # primary orders ignored
# -----------------------------------------------------------------------------


def overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def has_payments(invoice):
    mgr = getattr(invoice, "payment_set", None) or getattr(invoice, "payments", None)
    return mgr.exists() if mgr is not None else False


class Command(BaseCommand):
    help = "Resolve conflicting primary orders, keep one secondary per month, then re-sync start/end dates of every patient's booking sequence."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run, rolled back).")
        parser.add_argument("--patient", type=int, help="Only this patient id.")
        parser.add_argument("--keep", type=int, help="PrimaryOrder id to keep (use with --remove).")
        parser.add_argument("--remove", type=int, help="PrimaryOrder id to remove (use with --keep).")
        parser.add_argument("--skip-resolve", action="store_true", help="Skip step 1 (conflicting orders).")
        parser.add_argument("--skip-monthly", action="store_true", help="Skip step 2 (one secondary per month).")
        parser.add_argument("--split-monthly", action="store_true",
                            help="Step 3: split secondaries spanning several months into one entry per month.")
        parser.add_argument("--skip-sync", action="store_true", help="Skip step 4 (date sync).")
        parser.add_argument("--close-gaps", nargs="?", const="start", choices=["start", "end"],
                            help="'start' (default) pulls the NEXT secondary's start back to previous end + gap-days; "
                                 "'end' extends the PREVIOUS secondary's end forward.")
        parser.add_argument("--fix-overlaps", action="store_true", help="Push overlapping secondaries forward.")
        parser.add_argument("--gap-days", type=int, default=1, help="Days between one period's end and the next start (default 1).")
        parser.add_argument("--no-invoice-sync", action="store_true", help="Do not move invoice period dates.")

    def log(self, msg):
        self.stdout.write(msg)

    # ============================================================== STEP 1
    def dedupe_invoices(self, secondary_id):
        invoices = list(TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: secondary_id}).order_by("id"))
        if len(invoices) < 2:
            return 0
        paid = [i for i in invoices if i.status in PAID_STATUSES]
        unpaid = [i for i in invoices if i.status not in PAID_STATUSES]
        deletable = [i for i in unpaid if not has_payments(i)]
        if not paid and len(deletable) == len(invoices):
            deletable = deletable[1:]                  # all unpaid -> keep the oldest
        if deletable:
            self.log(f"      delete unpaid duplicate invoice(s) {[i.invoice_number for i in deletable]}")
            TotalInvoice.objects.filter(pk__in=[i.pk for i in deletable]).delete()
        return len(deletable)

    def resolve_pair(self, keeper, victim):
        deleted_invoices = 0
        keeper_secs = list(SecondaryOrder.objects.filter(primary_order_id=keeper.pk))
        victim_secs = list(SecondaryOrder.objects.filter(primary_order_id=victim.pk))
        conflicts = 0
        self.log(f"    kept order {keeper.pk}: {len(keeper_secs)} secondaries | "
                 f"order {victim.pk}: {len(victim_secs)} secondaries")

        for sv in victim_secs:
            match = next((sk for sk in keeper_secs
                          if overlaps(sv.start_datetime, sv.end_datetime, sk.start_datetime, sk.end_datetime)), None)
            if match is None:
                SecondaryOrder.objects.filter(pk=sv.pk).update(primary_order_id=keeper.pk)
                self.log(f"    secondary {sv.pk} has no clash -> moved to order {keeper.pk}")
                continue

            ternary = getattr(sv, "ternary_orders", None)
            if ternary is not None and ternary.exists():
                raise CommandError(f"Secondary {sv.pk} (order {victim.pk}) has ternary orders - resolve those manually first.")

            conflicts += 1
            self.log(f"    secondary {sv.pk} ({sv.start_datetime:%d %b %Y}->{sv.end_datetime:%d %b %Y}) "
                     f"conflicts with kept secondary {match.pk}")

            moved = TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: sv.pk})
            for inv in moved:
                self.log(f"      move invoice {inv.invoice_number} [{inv.status}] total={inv.total_amount} -> secondary {match.pk}")
                if inv.status in PAID_STATUSES and inv.total_amount != match.subtotal:
                    self.log(self.style.WARNING(
                        f"      !! paid invoice total {inv.total_amount} != kept secondary subtotal "
                        f"{match.subtotal} - review amount manually"))
            moved.update(**{INVOICE_SECONDARY_FK: match.pk})
            deleted_invoices += self.dedupe_invoices(match.pk)
            sv.delete()

        vid, vorder = victim.pk, victim.order_id            # victim.pk becomes None after delete()
        remaining = SecondaryOrder.objects.filter(primary_order_id=vid).count()
        if remaining == 0:
            self.log(f"    delete conflicting order {vid} ({vorder})"
                     f"{'' if conflicts else ' (no clashing secondaries; all moved to kept order)'}")
            victim.delete()
            if PrimaryOrder.objects.filter(pk=vid).exists():
                self.log(self.style.ERROR(
                    f"    !! order {vid} still exists after delete() - PrimaryOrder.delete()/signals may soft-delete or block it"))
        else:
            self.log(self.style.ERROR(f"    !! order {vid} still has {remaining} secondary order(s), not deleted"))
        return deleted_invoices

    def find_pairs(self, o):
        if o["keep"] or o["remove"]:
            if not (o["keep"] and o["remove"]):
                raise CommandError("--keep and --remove must be given together.")
            return [(PrimaryOrder.objects.get(pk=o["keep"]), PrimaryOrder.objects.get(pk=o["remove"]))]
        qs = PrimaryOrder.objects.exclude(status__in=EXCLUDED_STATUSES).order_by("created_at", "id")
        if o["patient"]:
            qs = qs.filter(patient_id=o["patient"])
        groups, pairs = {}, []
        for po in qs:
            groups.setdefault((po.patient_id, po.service_id, po.package_id, po.venue_id, po.booking_type), []).append(po)
        for orders in groups.values():
            keeper = orders[0]                                # oldest wins
            for victim in orders[1:]:
                if overlaps(keeper.start_datetime, keeper.end_datetime, victim.start_datetime, victim.end_datetime):
                    pairs.append((keeper, victim))
        return pairs

    # ============================================================== STEP 2
    def _is_paid_secondary(self, secondary_id):
        for inv in TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: secondary_id}):
            if inv.status in PAID_STATUSES or has_payments(inv):
                return True
        return False

    def one_per_month(self, o, stats):
        qs = PrimaryOrder.objects.exclude(status__in=EXCLUDED_STATUSES).order_by("patient_id", "id")
        if o["patient"]:
            qs = qs.filter(patient_id=o["patient"])

        for po in qs:
            secs = list(SecondaryOrder.objects.filter(primary_order_id=po.pk).order_by("start_datetime", "id"))
            months = {}
            for s in secs:
                d = timezone.localtime(s.start_datetime)
                months.setdefault((d.year, d.month), []).append(s)

            for (year, month), group in months.items():
                if len(group) < 2:
                    continue
                ids = [s.pk for s in group]
                paid = [s for s in group if self._is_paid_secondary(s.pk)]
                if len(paid) > 1:
                    self.log(self.style.ERROR(
                        f"patient {po.patient_id} order {po.pk} {year}-{month:02d}: secondaries {ids} - more than one "
                        f"has a paid invoice/payment, NOT touched, review manually"))
                    stats["monthly_manual"] += 1
                    continue
                winner = paid[0] if paid else min(group, key=lambda x: (x.created_at, x.pk))
                self.log(f"patient {po.patient_id} order {po.pk} {year}-{month:02d}: {len(group)} secondaries {ids} "
                         f"-> keep {winner.pk}"
                         f"{' (has paid invoice)' if paid else ' (oldest)'}")

                for loser in group:
                    if loser.pk == winner.pk:
                        continue
                    ternary = getattr(loser, "ternary_orders", None)
                    if ternary is not None and ternary.exists():
                        self.log(self.style.ERROR(f"    secondary {loser.pk} has ternary orders, skipped - review manually"))
                        stats["monthly_manual"] += 1
                        continue

                    moved = TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: loser.pk})
                    for inv in moved:
                        self.log(f"    move invoice {inv.invoice_number} [{inv.status}] total={inv.total_amount} "
                                 f"from secondary {loser.pk} -> {winner.pk}")
                        if inv.status in PAID_STATUSES and inv.total_amount != winner.subtotal:
                            self.log(self.style.WARNING(
                                f"    !! paid invoice total {inv.total_amount} != kept secondary subtotal "
                                f"{winner.subtotal} - review amount manually"))
                    moved.update(**{INVOICE_SECONDARY_FK: winner.pk})
                    stats["invoices_deleted"] += self.dedupe_invoices(winner.pk)
                    if not o["no_invoice_sync"]:
                        TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: winner.pk}).exclude(
                            status__in=PAID_STATUSES).update(
                            period_start=winner.start_datetime, period_end=winner.end_datetime)
                    self.log(f"    delete duplicate secondary {loser.pk} ({loser.order_id}) "
                             f"{loser.start_datetime:%d %b %Y}->{loser.end_datetime:%d %b %Y}")
                    loser.delete()
                    stats["monthly_removed"] += 1

    # ============================================================== STEP 3
    def clone_secondary(self, src, **changes):
        new = SecondaryOrder.objects.get(pk=src.pk)
        new.pk = None
        new.id = None
        new._state.adding = True
        try:                                   # let the model/signals generate a fresh order_id
            new.order_id = None if SecondaryOrder._meta.get_field("order_id").null else ""
        except Exception:
            pass
        for k, v in changes.items():
            setattr(new, k, v)
        new.is_registration_fee = False
        new.save()
        return new

    def split_monthly(self, o, stats):
        qs = PrimaryOrder.objects.exclude(status__in=EXCLUDED_STATUSES).order_by("patient_id", "id")
        if o["patient"]:
            qs = qs.filter(patient_id=o["patient"])

        for po in qs:
            for s in list(SecondaryOrder.objects.filter(primary_order_id=po.pk).order_by("start_datetime", "id")):
                n = max(1, round((s.end_datetime - s.start_datetime).days / 30.44))
                if n < 2:
                    continue
                ternary = getattr(s, "ternary_orders", None)
                if ternary is not None and ternary.exists():
                    self.log(self.style.ERROR(f"secondary {s.pk} spans {n} months but has ternary orders - skipped, review manually"))
                    stats["monthly_manual"] += 1
                    continue

                orig_start, orig_end, orig_sub = s.start_datetime, s.end_datetime, s.subtotal
                pieces = []
                for k in range(n):
                    p_start = orig_start + relativedelta(months=k)
                    p_end = (orig_start + relativedelta(months=k + 1)) - timedelta(days=1) if k < n - 1 else orig_end
                    pieces.append((p_start, p_end))
                amounts = [orig_sub] * n                      # subtotal is NOT split: same amount every month

                self.log(f"patient {po.patient_id} order {po.pk}: secondary {s.pk} "
                         f"{orig_start:%d %b %Y}->{orig_end:%d %b %Y} spans {n} months, subtotal {orig_sub} kept on every month -> split:")
                for (a, b), amt in zip(pieces, amounts):
                    self.log(f"      {a:%d %b %Y} -> {b:%d %b %Y}  subtotal {amt}")
                for inv in TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: s.pk}):
                    self.log(self.style.WARNING(
                        f"      !! invoice {inv.invoice_number} [{inv.status}] total={inv.total_amount} stays on the FIRST month "
                        f"and is NOT split - review invoices/payments manually"))

                s.end_datetime, s.updated_at = pieces[0][1], timezone.now()
                s.save(update_fields=["end_datetime", "updated_at"])
                for (a, b), amt in list(zip(pieces, amounts))[1:]:
                    self.clone_secondary(s, start_datetime=a, end_datetime=b, subtotal=amt)
                    stats["split_created"] += 1

    # ============================================================== STEP 4
    def sync_dates(self, o, stats):
        gap = timedelta(days=o["gap_days"])
        qs = PrimaryOrder.objects.exclude(status__in=EXCLUDED_STATUSES).order_by("patient_id", "id")
        if o["patient"]:
            qs = qs.filter(patient_id=o["patient"])

        for po in qs:
            secs = list(SecondaryOrder.objects.filter(primary_order_id=po.pk).order_by("start_datetime", "id"))
            if not secs:
                continue
            stats["orders"] += 1
            prev = None
            for s in secs:
                if prev is not None:
                    if s.start_datetime < prev.end_datetime:
                        stats["overlaps"] += 1
                        self.log(self.style.WARNING(
                            f"patient {po.patient_id} order {po.pk}: secondary {s.pk} "
                            f"({s.start_datetime:%d %b %Y}) overlaps {prev.pk} (ends {prev.end_datetime:%d %b %Y})"))
                        if o["fix_overlaps"]:
                            length = s.end_datetime - s.start_datetime
                            s.start_datetime = prev.end_datetime + gap
                            s.end_datetime = s.start_datetime + length
                            s.updated_at = timezone.now()
                            s.save(update_fields=["start_datetime", "end_datetime", "updated_at"])
                            stats["moved"] += 1
                            self.log(f"    -> moved to {s.start_datetime:%d %b %Y} - {s.end_datetime:%d %b %Y}")
                            if not o["no_invoice_sync"]:
                                TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: s.pk}).update(
                                    period_start=s.start_datetime, period_end=s.end_datetime)
                    elif s.start_datetime - prev.end_datetime > timedelta(days=1):
                        stats["gaps"] += 1
                        days = (s.start_datetime - prev.end_datetime).days
                        if not o["close_gaps"]:
                            self.log(f"patient {po.patient_id} order {po.pk}: gap of {days} day(s) "
                                     f"before secondary {s.pk} (left as is; use --close-gaps)")
                        elif o["close_gaps"] == "start":
                            s.start_datetime = prev.end_datetime + gap
                            s.updated_at = timezone.now()
                            s.save(update_fields=["start_datetime", "updated_at"])
                            stats["moved"] += 1
                            self.log(f"patient {po.patient_id} order {po.pk}: closed {days}-day gap, "
                                     f"secondary {s.pk} now starts {s.start_datetime:%d %b %Y}")
                            if not o["no_invoice_sync"]:
                                TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: s.pk}).update(period_start=s.start_datetime)
                        else:  # "end"
                            prev.end_datetime = s.start_datetime - gap
                            prev.updated_at = timezone.now()
                            prev.save(update_fields=["end_datetime", "updated_at"])
                            stats["moved"] += 1
                            self.log(f"patient {po.patient_id} order {po.pk}: closed {days}-day gap, "
                                     f"secondary {prev.pk} now ends {prev.end_datetime:%d %b %Y}")
                            if not o["no_invoice_sync"]:
                                TotalInvoice.objects.filter(**{INVOICE_SECONDARY_FK: prev.pk}).update(period_end=prev.end_datetime)
                prev = s

            new_start = min(s.start_datetime for s in secs)
            new_end = max(s.end_datetime for s in secs)
            if po.start_datetime != new_start or po.end_datetime != new_end:
                self.log(f"patient {po.patient_id} order {po.pk}: primary "
                         f"{po.start_datetime:%d %b %Y} - {po.end_datetime:%d %b %Y} -> "
                         f"{new_start:%d %b %Y} - {new_end:%d %b %Y}")
                PrimaryOrder.objects.filter(pk=po.pk).update(
                    start_datetime=new_start, end_datetime=new_end, updated_at=timezone.now())
                stats["primary_updated"] += 1

    # ============================================================== main
    def handle(self, *args, **o):
        stats = {"orders": 0, "primary_updated": 0, "overlaps": 0, "gaps": 0, "moved": 0,
                 "monthly_removed": 0, "monthly_manual": 0, "invoices_deleted": 0, "split_created": 0}
        pairs, victim_ids, deleted_invoices = [], [], 0

        with transaction.atomic():
            if not o["skip_resolve"]:
                self.log("=== STEP 1: resolve conflicting orders ===")
                pairs = self.find_pairs(o)
                victim_ids = [v.pk for _, v in pairs]
                if not pairs:
                    self.log("No conflicting orders found.")
                for keeper, victim in pairs:
                    self.log(f"Conflict: keep {keeper.pk} ({keeper.booking_entity}) / remove {victim.pk} "
                             f"({victim.booking_entity}) patient={keeper.patient_id}")
                    deleted_invoices += self.resolve_pair(keeper, victim)

            if not o["skip_monthly"]:
                self.log("=== STEP 2: one secondary order per month ===")
                self.one_per_month(o, stats)

            if o["split_monthly"]:
                self.log("=== STEP 3: split multi-month secondaries into monthly entries ===")
                self.split_monthly(o, stats)

            if not o["skip_sync"]:
                self.log("=== STEP 4: sync booking sequence dates ===")
                self.sync_dates(o, stats)

            if not o["apply"]:
                transaction.set_rollback(True)             # dry run executes the real code, then rolls back

        if o["apply"] and victim_ids:
            left = list(PrimaryOrder.objects.filter(pk__in=victim_ids).values_list("pk", flat=True))
            if left:
                self.log(self.style.ERROR(f"!! after commit these conflicting orders STILL exist: {left}"))
            else:
                self.log("verified: all conflicting orders are gone from the database")

        mode = "APPLIED" if o["apply"] else "DRY RUN (rolled back)"
        self.log(self.style.SUCCESS(
            f"[{mode}] {len(pairs)} conflicting pair(s), {stats['monthly_removed']} duplicate monthly secondary(ies) removed "
            f"({stats['monthly_manual']} need manual review), {stats['split_created']} monthly secondary(ies) created by splitting, {deleted_invoices + stats['invoices_deleted']} unpaid duplicate invoice(s) deleted | "
            f"{stats['orders']} order(s) checked, {stats['primary_updated']} primary date(s) updated, "
            f"{stats['overlaps']} overlap(s), {stats['moved']} moved, {stats['gaps']} gap(s)."))

