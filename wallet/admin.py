# wallet/admin.py
from django.contrib import admin
from django.db.models import Sum
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
    raw_id_fields = ['user']
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

    def changelist_view(self, request, extra_context=None):
        """جمع کل واریز و برداشت کیف‌پول‌ها -- روی همان فهرست فیلترشده/جستجوشده
        فعلی محاسبه می‌شود، نه لزوماً کل جدول."""
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            qs = response.context_data['cl'].queryset
        except (AttributeError, KeyError):
            return response

        total_deposit = qs.filter(amount__gt=0).aggregate(s=Sum('amount'))['s'] or 0
        total_withdraw = qs.filter(amount__lt=0).aggregate(s=Sum('amount'))['s'] or 0
        response.context_data['total_deposit'] = total_deposit
        response.context_data['total_withdraw'] = abs(total_withdraw)
        response.context_data['net_total'] = total_deposit + total_withdraw
        return response


# ===== تغییر نام کلاس ادمین از WalletAdmin به WalletModelAdmin =====
@admin.register(Wallet)
class WalletModelAdmin(admin.ModelAdmin):  # ← نام را تغییر دادیم
    list_display = ['user', 'balance_display', 'created_at', 'updated_at']
    search_fields = ['user__username', 'user__phone_number']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['user']

    def balance_display(self, obj):
        return f"{obj.balance:,} ریال"
    balance_display.short_description = 'موجودی'