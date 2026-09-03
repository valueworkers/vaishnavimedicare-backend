from django.contrib import admin
from django.db.models import Sum

from .models import Wallet, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'balance',
        'total_credited',
        'total_debited',
        'created_at',
    )

    list_filter = (
        'created_at',
    )

    search_fields = (
        'user__username',
        'user__email',
        'user__first_name',
        'user__last_name',
    )

    readonly_fields = (
        'balance',
        'created_at',
    )

    ordering = ('-created_at',)

    def total_credited(self, obj):
        total = (
            obj.transactions.filter(transaction_type='CREDIT')
            .aggregate(total=Sum('amount'))
            .get('total')
        )
        return total or 0

    total_credited.short_description = 'Total Credited'

    def total_debited(self, obj):
        total = (
            obj.transactions.filter(transaction_type='DEBIT')
            .aggregate(total=Sum('amount'))
            .get('total')
        )
        return total or 0

    total_debited.short_description = 'Total Debited'


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id',
        'wallet',
        'transaction_type',
        'source_type',
        'amount',
        'reference_id',
        'created_at',
    )

    list_filter = (
        'transaction_type',
        'source_type',
        'created_at',
    )

    search_fields = (
        'transaction_id',
        'reference_id',
        'wallet__user__username',
        'wallet__user__email',
    )

    readonly_fields = (
        'transaction_id',
        'created_at',
    )

    ordering = ('-created_at',)