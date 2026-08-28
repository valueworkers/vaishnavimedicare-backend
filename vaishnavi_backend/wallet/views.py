
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from .serializers import *
from .service import WalletPaymentService
from booking.models import TotalInvoice,Payment


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for wallet operations.
    
    Endpoints:
    - GET /wallet/wallet/ - List (admin only)
    - GET /wallet/wallet/{id}/ - Retrieve wallet
    - GET /wallet/wallet/my-wallet/ - Get current user's wallet
    - GET /wallet/wallet/{id}/history/ - Transaction history
    - POST /wallet/wallet/{id}/debit/ - Debit from wallet
    - POST /wallet/wallet/{id}/credit/ - Credit to wallet
    - POST /wallet/wallet/{id}/auto-pay/ - Auto-pay for invoice
    - POST /wallet/wallet/{id}/excess-payment/ - Handle excess payment
    - POST /wallet/wallet/{id}/wallet-cash-combo/ - Apply wallet + cash
    - POST /wallet/wallet/{id}/refund/ - Refund to wallet
    - GET /wallet/wallet/{id}/summary/ - Payment summary
    """
    
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Users can only see their own wallet, admins can see all"""
        if self.request.user.is_staff:
            return Wallet.objects.all()
        return Wallet.objects.filter(user=self.request.user)
    
    def get_object(self):
        """Allow access to own wallet via 'my-wallet' or explicit ID"""
        if self.kwargs.get('pk') == 'my-wallet':
            return get_object_or_404(Wallet, user=self.request.user)
        return super().get_object()
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """Get transaction history for wallet"""
        wallet = self.get_object()
        limit = request.query_params.get('limit', 50)
        
        transactions = wallet.get_transaction_history(limit=int(limit))
        serializer = WalletTransactionSerializer(transactions, many=True)
        
        return Response({
            'wallet_id': wallet.id,
            'transaction_count': len(transactions),
            'transactions': serializer.data
        })
    
    @action(detail=True, methods=['post'])
    def debit(self, request, pk=None):
        """Debit from wallet (manual operation)"""
        wallet = self.get_object()
        serializer = WalletDebitSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            txn = wallet.debit(
                amount=serializer.validated_data['amount'],
                source_type='ADJUSTMENT',
                reference_id=serializer.validated_data.get('reference_id'),
                description=serializer.validated_data.get('description')
            )
            
            return Response({
                'success': True,
                'transaction_id': txn.transaction_id,
                'amount': txn.amount,
                'new_balance': wallet.balance,
                'message': 'Debit successful'
            }, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def credit(self, request, pk=None):
        """Credit to wallet (manual operation)"""
        wallet = self.get_object()
        serializer = WalletCreditSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            txn = wallet.credit(
                amount=serializer.validated_data['amount'],
                source_type='ADJUSTMENT',
                reference_id=serializer.validated_data.get('reference_id'),
                description=serializer.validated_data.get('description')
            )
            
            return Response({
                'success': True,
                'transaction_id': txn.transaction_id,
                'amount': txn.amount,
                'new_balance': wallet.balance,
                'message': 'Credit successful'
            }, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def auto_pay(self, request, pk=None):
        """Process auto-pay for an invoice"""
        wallet = self.get_object()
        serializer = AutoPaySerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        invoice_id = serializer.validated_data['invoice_id']
        invoice = get_object_or_404(TotalInvoice, id=invoice_id, user=wallet.user)
        
        # Get order from invoice
        order = invoice.secondary_order or invoice.ternary_order
        
        try:
            result = WalletPaymentService.process_order_auto_pay(order, invoice)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def excess_payment(self, request, pk=None):
        """Handle excess payment"""
        wallet = self.get_object()
        serializer = ExcessPaymentSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        payment_id = serializer.validated_data['payment_id']
        payment = get_object_or_404(Payment, id=payment_id)
        invoice = payment.invoice
        
        try:
            result = WalletPaymentService.handle_excess_payment(payment, invoice)
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def wallet_cash_combo(self, request, pk=None):
        """Apply wallet + cash combo to invoice"""
        wallet = self.get_object()
        serializer = WalletCashComboSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        invoice_id = serializer.validated_data['invoice_id']
        invoice = get_object_or_404(TotalInvoice, id=invoice_id, user=wallet.user)
        
        try:
            result = WalletPaymentService.apply_wallet_and_cash(
                invoice,
                serializer.validated_data['cash_amount']
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        """Refund to wallet"""
        wallet = self.get_object()
        serializer = RefundSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        invoice_id = serializer.validated_data['invoice_id']
        invoice = get_object_or_404(TotalInvoice, id=invoice_id, user=wallet.user)
        
        try:
            result = WalletPaymentService.refund_to_wallet(
                invoice,
                serializer.validated_data['refund_amount'],
                serializer.validated_data.get('reason', '')
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def summary(self, request, pk=None):
        """Get payment summary"""
        wallet = self.get_object()
        
        summary = WalletPaymentService.get_payment_summary(wallet.user)
        serializer = PaymentSummarySerializer(summary)
        
        return Response(serializer.data, status=status.HTTP_200_OK)