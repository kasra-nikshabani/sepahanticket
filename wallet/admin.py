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
        'is_wallet',
        'description',
        'created_at',
        'reference_id',
    ]
    list_filter = [
        'transaction_type',
        'is_wallet',
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
        """نمایش مبلغ به ریال با جداکننده"""
        return f"{obj.amount:,} ریال"
    amount_display.short_description = 'مبلغ'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


# ===== تغییر نام کلاس ادمین از WalletAdmin به WalletModelAdmin =====
@admin.register(Wallet)
class WalletModelAdmin(admin.ModelAdmin):  # ← نام را تغییر دادیم
    list_display = ['user', 'balance_display', 'created_at', 'updated_at']
    search_fields = ['user__username', 'user__phone_number']
    readonly_fields = ['created_at', 'updated_at']

    def balance_display(self, obj):
        return f"{obj.balance:,} ریال"
    balance_display.short_description = 'موجودی'