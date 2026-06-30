from django.contrib import admin
from django.shortcuts import redirect
from django.contrib import messages
from .models import Ticket, DiscountCode
from .models import VIPQuota


@admin.action(description='تخصیص به کاربر ویژه (VIP)')
def assign_to_vip(modeladmin, request, queryset):
    """تبدیل بلیط‌های انتخاب‌شده به تخصیص VIP"""
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

@admin.register(Ticket)  # ← فقط یک بار ثبت می‌شود
class TicketAdmin(admin.ModelAdmin):
    list_display = ('ticket_number', 'user', 'match', 'full_name', 'status', 'is_admin_assigned', 'is_used', 'used_at')
    list_filter = ('status', 'is_admin_assigned', 'is_used', 'match')
    search_fields = ('ticket_number', 'user__username', 'full_name', 'national_code')
    actions = [assign_to_vip]

    readonly_fields = ('ticket_number', 'qr_code', 'pdf_file', 'used_at')
    fieldsets = (
        ('اطلاعات اصلی', {
            'fields': ('user', 'match', 'seat', 'full_name', 'national_code')
        }),
        ('وضعیت', {
            'fields': ('status', 'is_admin_assigned', 'is_used', 'used_at')
        }),
        ('فایل‌ها', {
            'fields': ('qr_code', 'pdf_file', 'ticket_number')
        }),
    )
    list_per_page = 20
    ordering = ('-purchase_date',)

    def get_queryset(self, request):
        return super().get_queryset(request)

@admin.register(VIPQuota)
class VIPQuotaAdmin(admin.ModelAdmin):
    list_display = ('user', 'match', 'quota', 'used', 'remaining')
    list_filter = ('match',)
    search_fields = ('user__username', 'user__first_name', 'match__home_team')
    fields = ('user', 'match', 'quota')


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
