# generate_invoice.py

from django.core.management.base import BaseCommand
from django.db import transaction
from booking.models import SecondaryOrder, TotalInvoice

def handle_secondary_order_update(instance):
    def _update():
        # Update Primary total
        if instance.primary_order_id:
            instance.primary_order.recalculate_total()

        # Invoice generation
        if instance.status =='FULFILLED':
            TotalInvoice.create_or_update_for_secondary(instance)

    transaction.on_commit(_update)


class Command(BaseCommand):
    help = "Trigger update logic for SecondaryOrders"

    def handle(self, *args, **kwargs):
        orders = SecondaryOrder.objects.filter(
            status='FULFILLED',
            # invoices__isnull=True
        )
        total_invoices = TotalInvoice.objects.all()
        before_count = total_invoices.count()
        
        self.stdout.write(self.style.SUCCESS(f"Total Number of Secondary order : {orders.count()}"))
        self.stdout.write(self.style.SUCCESS(f"Total Number of  Invoices {total_invoices.count()}"))
        
        for i, order in enumerate(orders):
            pass
            # handle_secondary_order_update(order)
            # self.stdout.write(self.style.SUCCESS(f"{i}) {order.order_id} {order.invoices.first().invoice_number if order.invoices.first() else 'N/A'} is generated "))
        self.stdout.write(self.style.SUCCESS(f"Total Number of Invoices generated : {total_invoices.count()-before_count}"))

