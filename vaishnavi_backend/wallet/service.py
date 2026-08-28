"""
Wallet Service Layer for Order & Booking Payments

This service handles:
- Auto-pay from wallet for orders
- Excess payment handling (overpayment)
- Partial payment with wallet combo
- Refunds and cancellations
- Invoice payment processing
"""

from django.db import transaction as db_transaction
from django.db import models
from django.core.exceptions import ValidationError
from decimal import Decimal
from typing import Dict, Tuple, Optional
from datetime import datetime


class WalletPaymentService:
    """
    Service to handle all wallet-related payment operations for orders/bookings.
    Encapsulates business logic for payment processing.
    """
    
    @staticmethod
    def process_order_auto_pay(order, invoice) -> Dict:
        """
        Process automatic payment from customer's wallet for an order.
        
        Called when:
        - Customer has auto_pay enabled
        - Order is ready for payment
        
        Args:
            order: PrimaryOrder or SecondaryOrder object
            invoice: TotalInvoice object
        
        Returns:
            {
                'success': bool,
                'payment_id': str (if created),
                'wallet_debit_amount': Decimal,
                'remaining_due': Decimal,
                'status': str (PAID, PARTIALLY_PAID, or FAILED),
                'message': str
            }
        
        Raises:
            ValidationError: If order/invoice invalid
        """
        if not hasattr(order, 'auto_continue') or not order.auto_continue:
            raise ValidationError("Auto-pay not enabled for this order")
        
        if invoice.status == 'PAID':
            return {
                'success': False,
                'message': 'Invoice already paid',
                'status': 'PAID'
            }
        
        patient = invoice.patient
        user = invoice.user
        
        # Get or create wallet
        from .models import Wallet
        wallet, _ = Wallet.objects.get_or_create(user=user)
        
        remaining_due = invoice.remaining_amount
        
        with db_transaction.atomic():
            # Check if wallet has enough balance
            if wallet.can_debit(remaining_due):
                # Debit full amount from wallet
                wallet_txn = wallet.debit(
                    amount=remaining_due,
                    source_type='ORDER_PAYMENT',
                    reference_id=str(invoice.id),
                    description=f"Auto-pay for invoice {invoice.invoice_number}"
                )
                
                from booking.models import Payment
                payment = Payment.objects.create(
                    invoice=invoice,
                    patient=patient,
                    amount=remaining_due,
                    method='WALLET',
                    reference=wallet_txn.transaction_id,
                    is_verified=True
                )
                
                invoice.recalculate_payments()
                
                return {
                    'success': True,
                    'payment_id': payment.id,
                    'wallet_debit_amount': remaining_due,
                    'remaining_due': Decimal('0.00'),
                    'status': invoice.status,
                    'message': f'Auto-pay successful: {remaining_due} debited from wallet'
                }
            else:
                # Partial auto-pay with available wallet balance
                available = wallet.balance
                
                if available > 0:
                    wallet_txn = wallet.debit(
                        amount=available,
                        source_type='ORDER_PAYMENT',
                        reference_id=str(invoice.id),
                        description=f"Partial wallet payment for invoice {invoice.invoice_number}"
                    )
                    
                    from booking.models import Payment
                    payment = Payment.objects.create(
                        invoice=invoice,
                        patient=patient,
                        amount=available,
                        method='WALLET',
                        reference=wallet_txn.transaction_id,
                        is_verified=True
                    )
                    
                    invoice.recalculate_payments()
                    
                    return {
                        'success': True,
                        'payment_id': payment.id,
                        'wallet_debit_amount': available,
                        'remaining_due': remaining_due - available,
                        'status': invoice.status,
                        'message': f'Partial wallet payment: {available} debited. Remaining: {remaining_due - available}'
                    }
                else:
                    return {
                        'success': False,
                        'wallet_debit_amount': Decimal('0.00'),
                        'remaining_due': remaining_due,
                        'status': 'FAILED',
                        'message': f'Insufficient wallet balance. Required: {remaining_due}, Available: {available}'
                    }
    
    @staticmethod
    def handle_excess_payment(payment_obj, invoice) -> Dict:
        """
        Handle customer overpayment - credit excess to wallet.
        
        Called when:
        - Cash payment > invoice amount
        - Customer pays more than due
        
        Args:
            payment_obj: Payment object with amount paid
            invoice: TotalInvoice object
        
        Returns:
            {
                'excess_amount': Decimal,
                'credited_to_wallet': bool,
                'wallet_balance': Decimal,
                'message': str
            }
        """
        excess = payment_obj.amount - invoice.total_amount
        
        if excess <= 0:
            return {
                'excess_amount': Decimal('0.00'),
                'credited_to_wallet': False,
                'message': 'No excess payment'
            }
        
        user = invoice.user
        from .models import Wallet
        wallet, _ = Wallet.objects.get_or_create(user=user)
        
        with db_transaction.atomic():
            wallet.credit(
                amount=excess,
                source_type='EXCESS_PAYMENT',
                reference_id=str(payment_obj.id),
                description=f"Excess payment from invoice {invoice.invoice_number}"
            )
            
            return {
                'excess_amount': excess,
                'credited_to_wallet': True,
                'wallet_balance': wallet.balance,
                'message': f'Excess {excess} credited to wallet'
            }
    
    @staticmethod
    def apply_wallet_and_cash(invoice, cash_paid: Decimal) -> Dict:
        """
        Apply combination of cash and wallet to an invoice.
        
        Flow:
        1. Apply cash_paid first
        2. If remaining due > 0, use wallet balance
        3. Return payment split
        
        Args:
            invoice: TotalInvoice object
            cash_paid: Amount paid in cash
        
        Returns:
            {
                'cash_applied': Decimal,
                'wallet_applied': Decimal,
                'total_applied': Decimal,
                'remaining_due': Decimal,
                'status': str (PAID, PARTIALLY_PAID),
                'payment_ids': [int],
                'message': str
            }
        """
        user = invoice.user
        total_due = invoice.total_amount
        
        from .models import Wallet
        from booking.models import Payment
        wallet, _ = Wallet.objects.get_or_create(user=user)

        with db_transaction.atomic():
            payment_ids = []

            # Step 1: Apply cash payment
            if cash_paid > 0:
                cash_payment = Payment.objects.create(
                    invoice=invoice,
                    patient=invoice.patient,
                    amount=cash_paid,
                    method='CASH',
                    is_verified=True
                )
                payment_ids.append(cash_payment.id)
            
            # Step 2: Calculate remaining after cash
            remaining = total_due - cash_paid
            wallet_applied = Decimal('0.00')
            
            if remaining > 0 and wallet.balance > 0:
                # Use as much wallet balance as possible
                usable = min(wallet.balance, remaining)
                
                wallet_txn = wallet.debit(
                    amount=usable,
                    source_type='ORDER_PAYMENT',
                    reference_id=str(invoice.id),
                    description=f"Wallet payment for invoice {invoice.invoice_number}"
                )
                
                wallet_payment = Payment.objects.create(
                    invoice=invoice,
                    patient=invoice.patient,
                    amount=usable,
                    method='WALLET',
                    reference=wallet_txn.transaction_id,
                    is_verified=True
                )
                payment_ids.append(wallet_payment.id)
                wallet_applied = usable
                remaining -= usable
            
            # Recalculate invoice
            invoice.recalculate_payments()
            
            return {
                'cash_applied': cash_paid,
                'wallet_applied': wallet_applied,
                'total_applied': cash_paid + wallet_applied,
                'remaining_due': max(remaining, Decimal('0.00')),
                'status': invoice.status,
                'payment_ids': payment_ids,
                'message': f'Payment applied: Cash={cash_paid}, Wallet={wallet_applied}'
            }
    
    @staticmethod
    def refund_to_wallet(invoice, refund_amount: Decimal, reason: str = "") -> Dict:
        """
        Refund amount to customer's wallet (e.g., cancellation, adjustment).
        
        Args:
            invoice: TotalInvoice object to refund
            refund_amount: Amount to refund
            reason: Reason for refund
        
        Returns:
            {
                'success': bool,
                'refund_amount': Decimal,
                'new_wallet_balance': Decimal,
                'transaction_id': str,
                'message': str
            }
        """
        if refund_amount <= 0:
            raise ValidationError("Refund amount must be positive")
        
        if refund_amount > invoice.paid_amount:
            raise ValidationError(
                f"Refund amount ({refund_amount}) cannot exceed paid amount ({invoice.paid_amount})"
            )
        
        user = invoice.user
        from .models import Wallet
        wallet, _ = Wallet.objects.get_or_create(user=user)
        
        with db_transaction.atomic():
            txn = wallet.credit(
                amount=refund_amount,
                source_type='REFUND',
                reference_id=str(invoice.id),
                description=f"Refund for invoice {invoice.invoice_number}. Reason: {reason}"
            )
            
            from booking.models import Payment
            refund_payment = Payment.objects.create(
                invoice=invoice,
                patient=invoice.patient,
                amount=-refund_amount,  # Negative to indicate reversal
                method='WALLET_REFUND',
                reference=txn.transaction_id,
                is_verified=True
            )
            
            invoice.recalculate_payments()
            
            return {
                'success': True,
                'refund_amount': refund_amount,
                'new_wallet_balance': wallet.balance,
                'transaction_id': txn.transaction_id,
                'message': f'Refund of {refund_amount} credited to wallet'
            }
    
    @staticmethod
    def handle_booking_cancellation(order, cancellation_fee: Decimal = None) -> Dict:
        """
        Handle cancellation and refund for a booking.
        
        Args:
            order: PrimaryOrder/SecondaryOrder/TernaryOrder
            cancellation_fee: Optional fee to deduct from refund
        
        Returns:
            {
                'original_amount': Decimal,
                'cancellation_fee': Decimal,
                'refund_amount': Decimal,
                'wallet_balance_after': Decimal,
                'message': str
            }
        """
        # Get invoice(s) linked to order
        if hasattr(order, 'invoices'):
            invoices = list(order.invoices.all())
        else:
            raise ValidationError("Cannot determine invoices for this order")
        
        if not invoices:
            return {
                'original_amount': Decimal('0.00'),
                'cancellation_fee': Decimal('0.00'),
                'refund_amount': Decimal('0.00'),
                'message': 'No invoices found for cancellation'
            }
        
        total_paid = sum(inv.paid_amount for inv in invoices)
        fee = cancellation_fee or Decimal('0.00')
        refund_amount = total_paid - fee
        
        if refund_amount <= 0:
            return {
                'original_amount': total_paid,
                'cancellation_fee': fee,
                'refund_amount': Decimal('0.00'),
                'message': 'No refund due after cancellation fee'
            }
        
        user = invoices[0].user
        from .models import Wallet
        wallet, _ = Wallet.objects.get_or_create(user=user)
        
        with db_transaction.atomic():
            wallet.credit(
                amount=refund_amount,
                source_type='CANCELLATION',
                reference_id=str(order.id),
                description=f"Cancellation refund. Fee: {fee}"
            )
            
            for invoice in invoices:
                WalletPaymentService.refund_to_wallet(
                    invoice,
                    invoice.paid_amount - (fee / len(invoices)),
                    reason=f"Booking cancellation"
                )
            
            return {
                'original_amount': total_paid,
                'cancellation_fee': fee,
                'refund_amount': refund_amount,
                'wallet_balance_after': wallet.balance,
                'message': f'Refund of {refund_amount} (after {fee} fee) credited'
            }
    
    @staticmethod
    def get_payment_summary(user) -> Dict:
        """
        Get payment summary for a user.
        
        Returns:
            {
                'wallet_balance': Decimal,
                'total_paid_orders': int,
                'total_paid_amount': Decimal,
                'outstanding_invoices': int,
                'outstanding_amount': Decimal,
                'last_payment_date': datetime
            }
        """
        from .models import Wallet
        from booking.models import Payment, TotalInvoice

        wallet, _ = Wallet.objects.get_or_create(user=user)

        payments = Payment.objects.filter(invoice__user=user)
        invoices = TotalInvoice.objects.filter(user=user)
        
        total_paid = payments.aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0.00')
        
        outstanding = invoices.filter(
            status__in=['UNPAID', 'PARTIALLY_PAID']
        ).aggregate(
            total=models.Sum('remaining_amount')
        )['total'] or Decimal('0.00')
        
        last_payment = payments.order_by('-paid_date').first()
        
        return {
            'wallet_balance': wallet.balance,
            'total_paid_orders': payments.count(),
            'total_paid_amount': total_paid,
            'outstanding_invoices': invoices.filter(
                status__in=['UNPAID', 'PARTIALLY_PAID']
            ).count(),
            'outstanding_amount': outstanding,
            'last_payment_date': last_payment.paid_date if last_payment else None
        }