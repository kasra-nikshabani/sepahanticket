from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import Payment
from matches.models import MatchSeat

STATUS_COLORS = {
    'success': '#28a745',
    'failed': '#dc3545',
    'pending': '#ffc107',
}


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    این مدل صرفاً برای مشاهده/رهگیری است -- عمداً read-only. تغییر دستی status
    از اینجا نتیجه‌ی واقعی پرداخت (کیف پول/صدور بلیط) را دوباره اجرا نمی‌کند،
    فقط رکورد را از واقعیت دور می‌کند. برای بررسی یک تراکنش گیرکرده،
    track_id را روی پنل زیبال چک کنید.
    """
    list_display = (
        'id', 'user', 'purpose', 'status_display', 'gateway_amount_display',
        'track_id', 'match', 'order_link', 'created_at', 'processed_at',
    )
    list_filter = ('purpose', 'status', 'created_at')
    search_fields = ('track_id', 'user__username', 'user__phone_number', 'order__order_number')
    date_hierarchy = 'created_at'
    list_per_page = 50
    ordering = ('-created_at',)

    readonly_fields = (
        'user', 'purpose', 'status', 'track_id', 'gateway_amount_display',
        'match', 'buyer_info_display', 'seat_ids', 'discount_code', 'discount_percent',
        'subtotal_display', 'discount_amount_display', 'wallet_amount_used_display',
        'order_link', 'next_url', 'created_at', 'updated_at', 'processed_at',
    )

    fieldsets = (
        ('اطلاعات کلی', {
            'fields': ('user', 'purpose', 'status', 'track_id', 'gateway_amount_display')
        }),
        ('مربوط به خرید بلیط', {
            'fields': (
                'match', 'buyer_info_display', 'seat_ids', 'discount_code', 'discount_percent',
                'subtotal_display', 'discount_amount_display', 'wallet_amount_used_display', 'order_link',
            )
        }),
        ('زمان‌ها', {
            'fields': ('next_url', 'created_at', 'updated_at', 'processed_at')
        }),
    )

    def has_add_permission(self, request):
        # این رکوردها فقط باید از مسیر واقعی پرداخت (payments.views) ساخته شوند
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def status_display(self, obj):
        color = STATUS_COLORS.get(obj.status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: 700;">{}</span>', color, obj.get_status_display()
        )
    status_display.short_description = 'وضعیت'

    def gateway_amount_display(self, obj):
        return f"{obj.gateway_amount:,} ریال"
    gateway_amount_display.short_description = 'مبلغ ارسالی به درگاه'

    def subtotal_display(self, obj):
        return f"{obj.subtotal:,} ریال"
    subtotal_display.short_description = 'جمع قبل از تخفیف'

    def discount_amount_display(self, obj):
        return f"{obj.discount_amount:,} ریال"
    discount_amount_display.short_description = 'مبلغ تخفیف'

    def wallet_amount_used_display(self, obj):
        return f"{obj.wallet_amount_used:,} ریال"
    wallet_amount_used_display.short_description = 'مبلغ کسرشده از کیف پول'

    def order_link(self, obj):
        if not obj.order_id:
            return '—'
        url = reverse('admin:tickets_order_change', args=[obj.order_id])
        return mark_safe(f'<a href="{url}">{obj.order.order_number}</a>')
    order_link.short_description = 'سفارش'

    def buyer_info_display(self, obj):
        """نمایش خوانا به‌جای dump خام JSON (شامل نام و کد ملی خریداران -- اطلاعات حساس)"""
        if not obj.buyer_info:
            return '—'

        seat_pks = sorted({
            key.rsplit('_', 1)[1] for key in obj.buyer_info if '_' in key
        })
        if not seat_pks:
            return format_html('<pre style="margin:0">{}</pre>', obj.buyer_info)

        # کلیدهای buyer_info با شناسه‌ی MatchSeat ساخته می‌شوند (فیلد
        # مخفی match_seat_id_{{ seat.id }} در ticket_info.html)، نه Seat --
        # برای نمایش جایگاه/بلوک/ردیف/صندلی باید از همین رابطه عبور کرد.
        match_seats = {
            str(ms.id): ms
            for ms in MatchSeat.objects.filter(id__in=seat_pks).select_related('seat__row__block')
        }

        rows = []
        for pk in seat_pks:
            name = obj.buyer_info.get(f'full_name_{pk}', '')
            national_code = obj.buyer_info.get(f'national_code_{pk}', '')
            dob = obj.buyer_info.get(f'tarikhe_tavallod_{pk}', '')
            phone = obj.buyer_info.get(f'shomare_hamrah_{pk}', '')

            match_seat = match_seats.get(pk)
            if match_seat:
                zone = match_seat.seat.row.zone_label
                block = match_seat.seat.row.block.name
                row_number = match_seat.seat.row.number
                seat_number = match_seat.seat.number
            else:
                zone = block = row_number = seat_number = '—'

            rows.append(
                f'<tr><td>{name}</td><td>{national_code}</td><td>{dob}</td><td>{phone}</td>'
                f'<td>{zone}</td><td>{block}</td><td>{row_number}</td><td>{seat_number}</td></tr>'
            )

        table = (
            '<table style="border-collapse:collapse">'
            '<tr><th style="text-align:right;padding:2px 8px">نام</th>'
            '<th style="text-align:right;padding:2px 8px">کد ملی</th>'
            '<th style="text-align:right;padding:2px 8px">تاریخ تولد</th>'
            '<th style="text-align:right;padding:2px 8px">موبایل</th>'
            '<th style="text-align:right;padding:2px 8px">جایگاه</th>'
            '<th style="text-align:right;padding:2px 8px">بلوک</th>'
            '<th style="text-align:right;padding:2px 8px">ردیف</th>'
            '<th style="text-align:right;padding:2px 8px">صندلی</th></tr>'
            + ''.join(rows) + '</table>'
        )
        return mark_safe(table)
    buyer_info_display.short_description = 'اطلاعات خریداران'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'match', 'order')
