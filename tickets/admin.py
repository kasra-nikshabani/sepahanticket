# tickets/admin.py
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib import messages
from .models import Ticket, DiscountCode, VIPQuota, Transaction, Order


# ============================================================
#  اکشن‌های سفارشی
# ============================================================

@admin.action(description='تخصیص به کاربر ویژه')
def assign_to_vip(modeladmin, request, queryset):
    count = 0
    for ticket in queryset:
        if ticket.user.user_type == 'vip':
            ticket.is_admin_assigned = True
            ticket.status = 'admin_assigned'
            ticket.save()
            count += 1
        else:
            messages.warning(request, f'کاربر {ticket.user.username} ویژه نیست.')
    messages.success(request, f'{count} بلیط به کاربران ویژه تخصیص داده شد.')


# ============================================================
#  ثبت مدل‌ها در ادمین
# ============================================================

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_number', 'match', 'user', 'full_name', 'price_display',
        'status', 'is_admin_assigned', 'is_used', 'purchase_date',
    )
    list_filter = ('match', 'status', 'is_admin_assigned', 'is_used')
    search_fields = ('ticket_number', 'user__username', 'user__phone_number', 'full_name', 'national_code')
    actions = [assign_to_vip]
    # بدون این، فیلدهای user/seat/match توی صفحه‌ی جزئیات بلیط به‌صورت
    # <select> ساده رندر می‌شدند -- یعنی همه‌ی ردیف‌های اون جدول (الان
    # ۹۰۰۰+ کاربر و ۵۹۰۰۰+ صندلی) باید توی HTML لود می‌شد و صفحه عملاً هنگ
    # می‌کرد. raw_id_fields به‌جاش یه ورودی متنی + جستجوی پاپ‌آپ می‌ده.
    raw_id_fields = ('user', 'match', 'seat')
    readonly_fields = ('ticket_number', 'qr_code', 'pdf_file_display', 'used_at', 'purchase_date')
    fieldsets = (
        ('اطلاعات اصلی', {
            'fields': ('user', 'match', 'seat', 'full_name', 'national_code', 'price')
        }),
        ('وضعیت', {
            'fields': ('status', 'is_admin_assigned', 'is_used', 'used_at', 'purchase_date')
        }),
        ('فایل‌ها', {
            'fields': ('qr_code', 'pdf_file_display', 'ticket_number')
        }),
    )
    list_per_page = 30
    list_select_related = ('match', 'user')
    ordering = ('match', '-purchase_date')
    date_hierarchy = 'purchase_date'

    def price_display(self, obj):
        return f"{obj.price:,} ریال"
    price_display.short_description = 'قیمت'

    def pdf_file_display(self, obj):
        """
        فایل PDF بلیط دیگر از طریق /media/ مستقیم در دسترس نیست (چون شامل
        نام و کد ملی خریدار است)؛ اینجا لینکش را از طریق ویوی احراز
        هویت‌شده نشون می‌دیم تا برای ادمین هم قابل دانلود بمونه.
        """
        if not obj.pk or not obj.pdf_file:
            return '—'
        url = reverse('tickets:download_ticket_pdf', args=[obj.pk])
        return format_html('<a href="{}" target="_blank">دانلود PDF</a>', url)

    pdf_file_display.short_description = 'فایل PDF'


@admin.register(VIPQuota)
class VIPQuotaAdmin(admin.ModelAdmin):
    list_display = ('user', 'match', 'quota', 'used', 'remaining')
    list_filter = ('match',)
    search_fields = ('user__username', 'user__first_name', 'match__home_team')
    fields = ('user', 'match', 'quota')
    raw_id_fields = ('user', 'match')


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'block', 'discount_percent', 'used_count', 'max_uses', 'is_active', 'expires_at')
    list_filter = ('is_active', 'block')
    search_fields = ('code',)
    readonly_fields = ('used_count', 'created_at')

    def save_model(self, request, obj, form, change):
        if not obj.code:
            import random, string
            obj.code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        super().save_model(request, obj, form, change)


# ============================================================
#  ثبت مدل Order (سفارش‌ها)
# ============================================================

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """
    نمایش سفارش‌ها در پنل ادمین با اطلاعات کامل مالی
    """
    list_display = [
        'order_number',
        'user',
        'match',
        'ticket_count_display',
        'total_amount_display',
        'wallet_amount_display',
        'discount_amount_display',
        'payment_method',
        'payment_status',
        'created_at',
    ]
    list_filter = [
        'payment_method',
        'payment_status',
        'created_at',
        'match',
    ]
    search_fields = [
        'order_number',
        'user__username',
        'user__phone_number',
        'discount_code',
        'full_name',
        'phone_number',
    ]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    readonly_fields = ['order_number', 'created_at', 'updated_at']
    list_per_page = 25
    raw_id_fields = ['user', 'match']

    fieldsets = (
        ('اطلاعات اصلی', {
            'fields': ('order_number', 'user', 'match', 'full_name', 'phone_number')
        }),
        ('اطلاعات مالی', {
            'fields': ('subtotal', 'discount_percent', 'discount_amount', 'total_amount')
        }),
        ('اطلاعات کیف پول', {
            'fields': ('wallet_amount', 'wallet_balance_before', 'wallet_balance_after')
        }),
        ('پرداخت', {
            'fields': ('payment_method', 'payment_status', 'track_id', 'paid_at')
        }),
        ('کد تخفیف', {
            'fields': ('discount_code', 'discount_code_id')
        }),
        ('زمان‌ها', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def ticket_count_display(self, obj):
        count = obj.tickets.count()
        return f"{count} عدد"

    ticket_count_display.short_description = 'تعداد بلیط'

    def total_amount_display(self, obj):
        """نمایش مبلغ نهایی با رنگ مناسب"""
        color = '#28a745' if obj.payment_status == 'paid' else '#dc3545'
        return format_html(
            '<span style="color: {}; font-weight: 600;">{} ریال</span>',
            color,
            f"{obj.total_amount:,}"
        )

    total_amount_display.short_description = 'مبلغ نهایی'

    def wallet_amount_display(self, obj):
        """نمایش مبلغ پرداخت شده از کیف پول"""
        if obj.wallet_amount > 0:
            return format_html(
                '<span style="color: #17a2b8; font-weight: 600;">{} ریال</span>',
                f"{obj.wallet_amount:,}"
            )
        return "—"

    wallet_amount_display.short_description = 'پرداخت از کیف پول'

    def discount_amount_display(self, obj):
        """نمایش مبلغ تخفیف"""
        if obj.discount_amount > 0:
            return format_html(
                '<span style="color: #D4AF37; font-weight: 600;">{} ریال ({}%)</span>',
                f"{obj.discount_amount:,}",
                obj.discount_percent
            )
        return "—"

    discount_amount_display.short_description = 'تخفیف'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'match').prefetch_related('tickets')


# ============================================================
#  ثبت Proxy Model Transaction
# ============================================================

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """
    نمایش تراکنش‌ها در اپ tickets (با استفاده از Proxy Model)
    """
    list_display = [
        'id',
        'user',
        'amount_display',
        'transaction_type_display',
        'is_wallet',
        'description',
        'reference_id',
        'created_at',
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
            'fields': ('user', 'amount', 'transaction_type', 'description', 'is_wallet', 'reference_id',
                       'balance_after'),
        }),
        ('زمان', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

    def amount_display(self, obj):
        return format_html(
            '<span style="font-weight: 600;">{} ریال</span>',
            f"{obj.amount:,}"
        )

    amount_display.short_description = 'مبلغ'

    def transaction_type_display(self, obj):
        """نمایش نوع تراکنش با رنگ‌بندی و آیکون"""
        tx_type = getattr(obj, 'transaction_type', None)

        if not tx_type:
            return format_html('<span style="color: #6c757d;">نامشخص</span>')

        type_display = obj.get_transaction_type_display() or tx_type

        colors = {
            'deposit': '#28a745',
            'withdraw': '#fd7e14',
            'ticket_purchase': '#007bff',
            'refund': '#6f42c1',
        }
        icons = {
            'deposit': '💰',
            'withdraw': '💳',
            'ticket_purchase': '🎟️',
            'refund': '↩️',
        }

        color = colors.get(tx_type, '#6c757d')
        icon = icons.get(tx_type, '📌')

        return format_html(
            '<span style="color: {}; font-weight: 600;">{} {}</span>',
            color,
            icon,
            type_display
        )

    transaction_type_display.short_description = 'نوع تراکنش'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')