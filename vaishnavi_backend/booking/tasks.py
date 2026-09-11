from celery import shared_task
from .models import PrimaryOrder, SecondaryOrder, TernaryOrder,TotalInvoice,bulk_update_status,sync_patient_active_status
from .constants import BookingStatus
from django.utils import timezone
from datetime import timedelta
import logging
from django.db import transaction


logger = logging.getLogger(__name__)

INVOICE_TRIGGER_STATUSES = [
    BookingStatus.UNFULFILLED,
    BookingStatus.PARTIALLY_FULFILLED,
    BookingStatus.FULFILLED,
]


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_missing_secondary_invoices(self):
    """
    Reconciliation sweep for SecondaryOrders. Needed because bulk_create/
    bulk_update (used by PrimaryOrder.generate_secondary_from_random_dates
    and generate_secondary_full_range_dates) bypass post_save signals.
    """
    qs = (
        SecondaryOrder.objects
        .filter(status__in=INVOICE_TRIGGER_STATUSES, invoices__isnull=True)
        .select_related("primary_order")
    )

    created, failed = 0, 0
    for order in qs.iterator():
        try:
            with transaction.atomic():
                TotalInvoice.create_or_update_for_secondary(order)
            created += 1
        except Exception:
            failed += 1
            logger.exception("Failed generating invoice for SecondaryOrder %s", order.pk)

    return {"created": created, "failed": failed}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_missing_ternary_invoices(self):
    qs = (
        TernaryOrder.objects
        .filter(status__in=INVOICE_TRIGGER_STATUSES, invoices__isnull=True)
        .select_related("secondary_order__primary_order")
    )

    created, failed = 0, 0
    for order in qs.iterator():
        try:
            with transaction.atomic():
                TotalInvoice.create_or_update_for_ternary(order)
            created += 1
        except Exception:
            failed += 1
            logger.exception("Failed generating invoice for TernaryOrder %s", order.pk)

    return {"created": created, "failed": failed}


@shared_task
def reconcile_invoices():
    """Umbrella task — schedule this one via beat."""
    secondary_result = generate_missing_secondary_invoices()
    ternary_result = generate_missing_ternary_invoices()
    logger.info("Invoice reconciliation: secondary=%s ternary=%s", secondary_result, ternary_result)
    return {"secondary": secondary_result, "ternary": ternary_result}

@shared_task
def update_statuses_by_time():
    return {
        "primary_updated":   bulk_update_status(PrimaryOrder.objects.all(),   PrimaryOrder),
        "secondary_updated": bulk_update_status(SecondaryOrder.objects.all(), SecondaryOrder),
        "ternary_updated":   bulk_update_status(TernaryOrder.objects.all(),   TernaryOrder),
        "patient_sync":      sync_patient_active_status()
    }


@shared_task
def trigger_auto_continue_secondary_orders():
    """
    Runs nightly. For every active PrimaryOrder whose end_datetime falls
    within the next 24 hours (or has already passed, if a previous run
    was missed) and has auto_continue=True, generate the next period's
    SecondaryOrder via generate_next_period_secondary().

    Example timeline (MONTHLY package):
        Jan 01 - Mar 31  (original range, auto_continue=True)

        Task runs on Mar 31 evening:
            → extends primary.end_datetime to Apr 30
            → creates Apr 01-Apr 30 SecondaryOrder (LOBBY)

        On Apr 30 evening (still auto_continue=True):
            → creates May 01-May 31 in LOBBY
            …and so on until auto_continue is set to False.
    """
    now = timezone.now()
    soon = now + timedelta(hours=24)

    # No lower bound on end_datetime — a primary whose window already
    # passed (e.g. this task ran late once) must still be picked up here,
    # not permanently skipped.
    expiring_orders = (
        PrimaryOrder.objects
        .filter(auto_continue=True, end_datetime__lte=soon)
        .exclude(status=BookingStatus.CANCELLED)
        .select_related("package")
    )

    created_count, failed_count = 0, 0
    for primary in expiring_orders:
        try:
            with transaction.atomic():
                new_secondary = primary.generate_next_period_secondary()
            if new_secondary:
                created_count += 1
        except Exception:
            failed_count += 1
            logger.exception("[auto_continue] Failed for PrimaryOrder %s", primary.pk)

    logger.info(
        "[auto_continue] created=%d failed=%d checked=%d",
        created_count, failed_count, expiring_orders.count(),
    )
    return {"created": created_count, "failed": failed_count}