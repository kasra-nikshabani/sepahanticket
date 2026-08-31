# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.shortcuts import redirect
from django.urls import reverse
from .models import User, SiteVisit, SiteSettings


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = [
        'phone_number',
        'get_full_name',
        'username',
        'gender',
        'user_type',
        'is_phone_verified',
        'is_active',
        'is_staff',
        'wallet_balance_display',
        'tickets_count',
        'date_joined',
    ]
    list_filter = ['user_type', 'gender', 'is_phone_verified', 'is_active', 'is_staff']
    search_fields = ['phone_number', 'username', 'first_name', 'last_name', 'email', 'national_code']
    ordering = ['-date_joined']
    readonly_fields = ['last_login', 'date_joined', 'wallet_balance_display', 'tickets_count']

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('اطلاعات شخصی', {'fields': ('first_name', 'last_name', 'email', 'phone_number', 'national_code', 'gender')}),
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


@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    """لاگ خام بازدیدها -- فقط برای مرور، از پنل قابل افزودن/ویرایش نیست."""
    list_display = ('visitor_display', 'ip_address', 'visited_at')
    list_filter = ('visited_at',)
    search_fields = (
        'visitor_id', 'ip_address',
        'user__username', 'user__phone_number', 'user__first_name', 'user__last_name',
    )
    date_hierarchy = 'visited_at'
    ordering = ('-visited_at',)
    list_per_page = 50
    list_select_related = ('user',)

    def visitor_display(self, obj):
        if obj.user_id:
            return obj.user.get_full_name() or obj.visitor_id
        return obj.visitor_id
    visitor_display.short_description = 'بازدیدکننده'
    visitor_display.admin_order_field = 'user__first_name'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """
    تنظیمات سراسری سایت (فعلاً فقط سوییچ مسدودسازی آی‌پی‌های خارج از ایران).
    فقط یک ردیف (singleton) وجود داره؛ کلیک روی این آیتم توی سایدبار
    مستقیم می‌بره به همون یک فرم ویرایش، بدون نیاز به رفتن توی یه لیست.
    """
    fields = ('block_foreign_ips', 'bypass_civil_registry_inquiry', 'wallet_enabled', 'updated_at')
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.get_solo()
        return redirect(reverse('admin:accounts_sitesettings_change', args=[obj.pk]))
