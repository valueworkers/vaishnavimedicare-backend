from django.db.models.signals import post_save,post_delete
from django.dispatch import receiver
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from .models import PrimaryOrder, SecondaryOrder,TernaryOrder, TotalInvoice, BookingStatus, Payment

  
@receiver([post_save, post_delete], sender=SecondaryOrder)
def refresh_primary_from_secondary(sender, instance, **kwargs):
    if kwargs.get("update_fields") == frozenset({"order_id"}):
        return
    primary_id = instance.primary_order_id
    if not primary_id:
        return
 
    def _run():
        primary = PrimaryOrder.objects.filter(pk=primary_id).first()  # may be cascade-deleted
        if primary:
            primary.refresh_from_secondaries()  # totals + status; dates left alone
 
    transaction.on_commit(_run)

@receiver(post_save, sender=Payment)
def update_invoice_on_payment_save(sender, instance, **kwargs):
    """Recalculate invoice when payment is created or updated"""
    
    def _recalculate():    
        try:
            invoice = instance.invoice
        except ObjectDoesNotExist:
            invoice = None

        if invoice is None:
            return  # or create it, if every booking should have an invoice
        invoice.recalculate_payments()

    transaction.on_commit(_recalculate)


@receiver(post_delete, sender=Payment)
def update_invoice_on_payment_delete(sender, instance, **kwargs):
    """
    Recalculate invoice totals when a payment is deleted.
    """
    def _recalculate():    
        try:
            invoice = instance.invoice
        except ObjectDoesNotExist:
            invoice = None

        if invoice is None:
            return  # or create it, if every booking should have an invoice
        invoice.recalculate()

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

