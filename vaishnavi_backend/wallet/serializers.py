
from .models import Wallet, WalletTransaction
from rest_framework import serializers

class WalletTransactionSerializer(serializers.ModelSerializer):
    """Serializer for wallet transaction history"""
    
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    
    class Meta:
        model = WalletTransaction
        fields = [
            'id',
            'transaction_id',
            'user_name',
            'amount',
            'transaction_type',
            'source_type',
            'reference_id',
            'description',
            'created_at'
        ]
        read_only_fields = fields

class WalletSerializer(serializers.ModelSerializer):
    """Serializer for wallet details"""
    
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    transactions = WalletTransactionSerializer(
        many=True,
        read_only=True,
        required=False
    )
    
    class Meta:
        model = Wallet
        fields = [
            'id',
            'user_name',
            'user_email',
            'balance',
            'last_updated',
            'created_at',
            'transactions'
        ]
        read_only_fields = [
            'id',
            'balance',
            'last_updated',
            'created_at',
            'transactions'
        ]

class WalletDebitSerializer(serializers.Serializer):
    """Serializer for wallet debit operations"""
    
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference_id = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    
    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

class WalletCreditSerializer(serializers.Serializer):
    """Serializer for wallet credit operations"""
    
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference_id = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)
    
    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

class AutoPaySerializer(serializers.Serializer):
    """Serializer for processing auto-pay"""
    
    invoice_id = serializers.IntegerField()
    
class ExcessPaymentSerializer(serializers.Serializer):
    """Serializer for handling excess payments"""
    
    payment_id = serializers.IntegerField()

class WalletCashComboSerializer(serializers.Serializer):
    """Serializer for applying wallet + cash combo payment"""
    
    invoice_id = serializers.IntegerField()
    cash_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    
    def validate_cash_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("Cash amount cannot be negative")
        return value

class RefundSerializer(serializers.Serializer):
    """Serializer for refund operations"""
    
    invoice_id = serializers.IntegerField()
    refund_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
    
    def validate_refund_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Refund amount must be positive")
        return value

class PaymentSummarySerializer(serializers.Serializer):
    """Serializer for payment summary"""
    
    wallet_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_paid_orders = serializers.IntegerField()
    total_paid_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    outstanding_invoices = serializers.IntegerField()
    outstanding_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    last_payment_date = serializers.DateTimeField(allow_null=True)

