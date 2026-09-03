from django.db.models.signals import post_save,post_delete
from django.dispatch import receiver
from django.db import transaction
from .models import SecondaryOrder,TernaryOrder, TotalInvoice, BookingStatus, Payment


@receiver(post_save, sender=Payment)
def update_invoice_on_payment_save(sender, instance, **kwargs):
    """Recalculate invoice when payment is created or updated"""
    
    def _recalculate():
        if instance.invoice:
            instance.invoice.recalculate_payments()

    transaction.on_commit(_recalculate)


@receiver(post_delete, sender=Payment)
def update_invoice_on_payment_delete(sender, instance, **kwargs):
    """
    Recalculate invoice totals when a payment is deleted.
    """
    def _recalculate():
        if instance.invoice:
            instance.invoice.recalculate_payments()

    transaction.on_commit(_recalculate)

INVOICE_TRIGGER_STATUSES = {
    BookingStatus.UNFULFILLED,
    BookingStatus.PARTIALLY_FULFILLED,
    BookingStatus.FULFILLED,
}

@receiver(post_save, sender=SecondaryOrder)
def secondary_saved(sender, instance, created, **kwargs):

    def _update():
        #  Update Primary total
        if instance.primary_order_id:
            instance.primary_order.recalculate_total()

        #  Invoice generation
        if instance.status in INVOICE_TRIGGER_STATUSES:
            TotalInvoice.create_or_update_for_secondary(instance)

    transaction.on_commit(_update)


@receiver(post_save, sender=TernaryOrder)
def ternary_saved(sender, instance, created, **kwargs):

    def _update():
        # Update Secondary subtotal
        if instance.secondary_order_id:
            instance.secondary_order.recalculate_subtotal()

        # Invoice generation
        if instance.status in INVOICE_TRIGGER_STATUSES:
            TotalInvoice.create_or_update_for_ternary(instance)

    transaction.on_commit(_update)

