from celery import shared_task
from .models import PrimaryOrder, SecondaryOrder, TernaryOrder,bulk_update_status
from .constants import BookingStatus
from django.utils import timezone
from datetime import timedelta

@shared_task
def update_statuses_by_time():
    return {
        "primary_updated":   bulk_update_status(PrimaryOrder.objects.all(),   PrimaryOrder),
        "secondary_updated": bulk_update_status(SecondaryOrder.objects.all(), SecondaryOrder),
        "ternary_updated":   bulk_update_status(TernaryOrder.objects.all(),   TernaryOrder),
    }


@shared_task
def trigger_auto_continue_secondary_orders():
    """
    Runs nightly.  For every active PrimaryOrder whose end_datetime
    falls within the next 24 hours and has auto_continue=True,
    generate the next period's SecondaryOrder in LOBBY.

    Example timeline (MONTHLY package):
        Jan 01 - Mar 31  (original range, auto_continue=True)

        Task runs on Mar 31 evening:
            → creates Apr 01-Apr 30 SecondaryOrder (LOBBY)
            → extends primary.end_datetime to Apr 30

        On Apr 30 evening (still auto_continue=True):
            → creates May 01-May 31 in LOBBY
            …and so on until auto_continue is set to False.
    """
    now  = timezone.now()
    soon = now + timedelta(hours=24)

    # Grab primaries that are about to expire AND want to continue
    expiring_orders = (
        PrimaryOrder.objects
        .filter(
            auto_continue=True,
            end_datetime__gte=now,
            end_datetime__lte=soon,
        )
        .exclude(status=BookingStatus.CANCELLED)
        .select_related("package")
    )

    created_count = 0
    for primary in expiring_orders:
        try:
            new_secondary = primary.generate_next_period_secondary()
            if new_secondary:
                created_count += 1
        except Exception as exc:
            # Log and continue — don't let one failure block others
            print(f"[auto_continue] Failed for PrimaryOrder {primary.pk}: {exc}")

    return f"Auto-continue: {created_count} new SecondaryOrders queued in LOBBY."
