from django.db import models, transaction as db_transaction
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
import uuid
from accounts.models import CustomUser



class Wallet(models.Model):
    """
    Central wallet for users (patients/customers).
    Tracks balance and last updated timestamp for race condition handling.
    """
    
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='wallet'
    )
    
    balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00')
    )
    
    last_updated = models.DateTimeField(
        auto_now=True,
        help_text="Updated whenever balance changes"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user']),
        ]
    
    def __str__(self):
        return f"Wallet({self.user.username}) - Balance: {self.balance}"
    
    def get_balance(self):
        """Get current wallet balance"""
        return self.balance
    
    def can_debit(self, amount):
        """Check if wallet has sufficient balance"""
        return self.balance >= amount
    
    @db_transaction.atomic
    def debit(self, amount, source_type, reference_id=None, description=None):
        """
        Debit from wallet.
        
        Args:
            amount: Decimal amount to debit
            source_type: Type of debit (ORDER, REFUND, ADJUSTMENT, etc.)
            reference_id: ID of related object (order_id, invoice_id, etc.)
            description: Additional details
        
        Returns:
            WalletTransaction object
        
        Raises:
            ValidationError: If insufficient balance
        """
        if amount <= 0:
            raise ValidationError("Debit amount must be positive")
        
        if not self.can_debit(amount):
            raise ValidationError(
                f"Insufficient balance. Available: {self.balance}, Required: {amount}"
            )
        
        # Refresh from DB to avoid race conditions
        wallet = Wallet.objects.select_for_update().get(pk=self.pk)
        
        if not wallet.can_debit(amount):
            raise ValidationError(
                f"Insufficient balance. Available: {wallet.balance}, Required: {amount}"
            )
        
        wallet.balance -= amount
        wallet.save(update_fields=['balance', 'last_updated'])
        
        transaction_obj = WalletTransaction.objects.create(
            user=self.user,
            wallet=wallet,
            amount=amount,
            transaction_type=WalletTransaction.TransactionType.DEBIT,
            source_type=source_type,
            reference_id=reference_id,
            description=description
        )
        
        # Update self reference
        self.balance = wallet.balance
        self.last_updated = wallet.last_updated
        
        return transaction_obj
    
    @db_transaction.atomic
    def credit(self, amount, source_type, reference_id=None, description=None):
        """
        Credit to wallet.
        
        Args:
            amount: Decimal amount to credit
            source_type: Type of credit (REFUND, EXCESS_PAYMENT, INCENTIVE, etc.)
            reference_id: ID of related object
            description: Additional details
        
        Returns:
            WalletTransaction object
        """
        if amount <= 0:
            raise ValidationError("Credit amount must be positive")
        
        # Refresh from DB
        wallet = Wallet.objects.select_for_update().get(pk=self.pk)
        
        wallet.balance += amount
        wallet.save(update_fields=['balance', 'last_updated'])
        
        transaction_obj = WalletTransaction.objects.create(
            user=self.user,
            wallet=wallet,
            amount=amount,
            transaction_type=WalletTransaction.TransactionType.CREDIT,
            source_type=source_type,
            reference_id=reference_id,
            description=description
        )
        
        # Update self reference
        self.balance = wallet.balance
        self.last_updated = wallet.last_updated
        
        return transaction_obj
    
    @db_transaction.atomic
    def transfer_to(self, target_user, amount, description=None):
        """
        Transfer balance to another user's wallet.
        Updates both wallets in atomic transaction.
        """
        if amount <= 0:
            raise ValidationError("Transfer amount must be positive")
        
        if self.user == target_user:
            raise ValidationError("Cannot transfer to same user")
        
        if not self.can_debit(amount):
            raise ValidationError(f"Insufficient balance: {self.balance}")
        
        # Get or create target wallet
        target_wallet, _ = Wallet.objects.get_or_create(user=target_user)
        
        # Debit from source
        self.debit(
            amount,
            source_type='TRANSFER',
            reference_id=None,
            description=f"Transfer to {target_user.username}"
        )
        
        # Credit to target
        target_wallet.credit(
            amount,
            source_type='TRANSFER',
            reference_id=None,
            description=f"Transfer from {self.user.username}"
        )
        
        return {
            'from_wallet': self,
            'to_wallet': target_wallet,
            'amount': amount
        }
    
    def get_transaction_history(self, limit=50):
        """Get recent transaction history"""
        return self.transactions.all().order_by('-created_at')[:limit]
    
    def get_transaction_summary(self, start_date=None, end_date=None):
        """
        Get summary stats for a date range.
        """
        queryset = self.transactions.all()
        
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        stats = queryset.aggregate(
            total_credits=Coalesce(
                Sum('amount', filter=Q(transaction_type='CREDIT')),
                Decimal('0.00')
            ),
            total_debits=Coalesce(
                Sum('amount', filter=Q(transaction_type='DEBIT')),
                Decimal('0.00')
            ),
            transaction_count=models.Count('id')
        )
        
        return {
            'total_credits': stats['total_credits'],
            'total_debits': stats['total_debits'],
            'net': stats['total_credits'] - stats['total_debits'],
            'transaction_count': stats['transaction_count'],
            'current_balance': self.balance
        }


class WalletTransaction(models.Model):
    """
    Immutable transaction record for every wallet operation.
    Provides complete audit trail.
    """
    
    class TransactionType(models.TextChoices):
        CREDIT = "CREDIT", "Credit"
        DEBIT = "DEBIT", "Debit"
    
    class SourceType(models.TextChoices):
        # Customer/Patient sources
        ORDER_PAYMENT = "ORDER_PAYMENT", "Order Payment (Auto Pay)"
        EXCESS_PAYMENT = "EXCESS_PAYMENT", "Excess Payment (Overpaid)"
        REFUND = "REFUND", "Refund"
        CANCELLATION = "CANCELLATION", "Booking Cancellation"
        ADJUSTMENT = "ADJUSTMENT", "Manual Adjustment"
        TRANSFER = "TRANSFER", "Transfer Between Users"
        
        # Future: Staff sources (commented for later)
        # ADVANCE = "ADVANCE", "Advance Payment"
        # INCENTIVE = "INCENTIVE", "Incentive/Commission"
        # SALARY = "SALARY", "Salary Settlement"
    
    transaction_id = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        db_index=True,
    )
    
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='wallet_transactions'
    )
    
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionType.choices
    )
    
    source_type = models.CharField(
        max_length=30,
        choices=SourceType.choices
    )
    
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        db_index=True,
        help_text="ID of related object: order_id, invoice_id, payment_id, etc."
    )
    
    description = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['wallet', '-created_at']),
            models.Index(fields=['source_type', '-created_at']),
            models.Index(fields=['reference_id']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = f"TXN-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_id} | {self.transaction_type} {self.amount} | {self.source_type}"

    @property
    def sign(self):
        """Return +1 for credit, -1 for debit"""
        return Decimal('1') if self.transaction_type == 'CREDIT' else Decimal('-1')

