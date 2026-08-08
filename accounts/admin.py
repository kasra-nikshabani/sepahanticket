# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = [
        'phone_number',
        'get_full_name',
        'username',
        'user_type',
        'is_phone_verified',
        'is_active',
        'is_staff',
        'wallet_balance_display',
        'tickets_count',
        'date_joined',
    ]
    list_filter = ['user_type', 'is_phone_verified', 'is_active', 'is_staff']
    search_fields = ['phone_number', 'username', 'first_name', 'last_name', 'email']
    ordering = ['-date_joined']
    readonly_fields = ['last_login', 'date_joined', 'wallet_balance_display', 'tickets_count']

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('اطلاعات شخصی', {'fields': ('first_name', 'last_name', 'email', 'phone_number')}),
        ('نوع و وضعیت کاربر', {'fields': ('user_type', 'is_phone_verified', 'is_active', 'is_staff', 'is_superuser')}),
        ('خلاصه‌ی فعالیت', {'fields': ('wallet_balance_display', 'tickets_count')}),
        ('دسترسی‌ها', {'fields': ('groups', 'user_permissions')}),
        ('تاریخ‌ها', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'phone_number', 'first_name', 'last_name', 'user_type', 'password1', 'password2'),
        }),
    )

    def wallet_balance_display(self, obj):
        wallet = getattr(obj, 'wallet', None)
        if wallet is None:
            return '—'
        return f"{wallet.balance:,} ریال"
    wallet_balance_display.short_description = 'موجودی کیف پول'

    def tickets_count(self, obj):
        if not obj.pk:
            return '—'
        return obj.ticket_set.count()
    tickets_count.short_description = 'تعداد بلیط'
