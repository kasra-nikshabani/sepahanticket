# wallet/admin.py
from django.contrib import admin
from .models import Wallet, Transaction

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'user',
        'amount_display',
        'transaction_type',
        'is_wallet',          # ← ستون جدید
        'description',
        'created_at',
        'reference_id',
    ]
    list_filter = [
        'transaction_type',
        'is_wallet',          # ← فیلتر بر اساس کیف پول
        'created_at',
    ]
    search_fields = [
        'user__username',
        'user__phone_number',
        'description',
        'reference_id',
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'balance_after']
    list_per_page = 25

    fieldsets = (
        ('اطلاعات تراکنش', {
            'fields': (
                'user',
                'amount',
                'transaction_type',
                'description',
                'is_wallet',
                'reference_id',
                'balance_after',
            )
        }),
        ('زمان', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    def amount_display(self, obj):
        """نمایش مبلغ به تومان با جداکننده"""
        return f"{obj.amount:,} تومان"
    amount_display.short_description = 'مبلغ'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['user', 'balance_display', 'created_at', 'updated_at']
    search_fields = ['user__username', 'user__phone_number']
    readonly_fields = ['created_at', 'updated_at']

    def balance_display(self, obj):
        return f"{obj.balance:,} تومان"
    balance_display.short_description = 'موجودی'