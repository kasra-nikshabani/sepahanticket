# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings
from .models import User, SiteVisit, SiteSettings, ArtCardApplication


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User

    def get_list_filter(self, request):
        if getattr(settings, 'CULTURAL_PLATFORM', False):
            return ('is_active', 'is_staff', 'is_phone_verified')
        return super().get_list_filter(request)

    def get_list_display(self, request):
        return tuple(item for item in super().get_list_display(request) if item != 'gender')

    def get_fieldsets(self, request, obj=None):
        if getattr(settings, 'CULTURAL_PLATFORM', False):
            return ((None, {'fields': ('username', 'password')}),
                    ('اطلاعات کاربر', {'fields': ('first_name', 'last_name', 'email', 'phone_number')}),
                    ('وضعیت و دسترسی', {'fields': ('user_type', 'is_active', 'is_phone_verified', 'is_staff', 'is_superuser')}))
        return super().get_fieldsets(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if getattr(settings, 'CULTURAL_PLATFORM', False) and 'user_type' in form.base_fields:
            form.base_fields['user_type'].choices = [('normal', 'کاربر'), ('admin', 'مدیر')]
        return form
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


@admin.register(ArtCardApplication)
class ArtCardApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'card_last_four', 'bank_reference', 'requested_at', 'updated_at')
    list_filter = ('status', 'requested_at')
    search_fields = ('user__username', 'user__phone_number', 'user__first_name', 'user__last_name', 'bank_reference')
    list_select_related = ('user',)
    readonly_fields = ('user', 'requested_at', 'updated_at')
    fields = ('user', 'status', 'bank_reference', 'card_last_four', 'admin_note', 'requested_at', 'updated_at')
    actions = None


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """
    تنظیمات سراسری سایت (فعلاً فقط سوییچ مسدودسازی آی‌پی‌های خارج از ایران).
    فقط یک ردیف (singleton) وجود داره؛ کلیک روی این آیتم توی سایدبار
    مستقیم می‌بره به همون یک فرم ویرایش، بدون نیاز به رفتن توی یه لیست.
    """
    fields = ('block_foreign_ips', 'bypass_civil_registry_inquiry', 'wallet_enabled', 'free_under_15', 'updated_at')
    readonly_fields = ('updated_at',)

    def get_fields(self, request, obj=None):
        if getattr(settings, 'CULTURAL_PLATFORM', False):
            return ('block_foreign_ips', 'wallet_enabled', 'wallet_charge_enabled', 'withdrawal_enabled', 'updated_at')
        return super().get_fields(request, obj)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.get_solo()
        return redirect(reverse('admin:accounts_sitesettings_change', args=[obj.pk]))


from django.utils.html import format_html, format_html_join
from .models import EventSubmission


@admin.register(EventSubmission)
class EventSubmissionAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'venue', 'owner', 'status', 'updated_at', 'submitted_at')
    list_select_related = ('owner', 'venue')
    list_filter = ('status', 'category')
    search_fields = ('title', 'owner__phone_number', 'owner__first_name', 'owner__last_name')
    readonly_fields = ('owner', 'title', 'category', 'venue', 'published_event', 'data', 'status', 'completed_step',
                       'created_at', 'updated_at', 'submitted_at', 'uploaded_files')
    fields = readonly_fields

    def uploaded_files(self, obj):
        links = [(reverse('accounts:event_submission_asset', args=[obj.pk, key]), label)
                 for key, label in (('poster', 'پوستر'), ('cover', 'بنر'), ('teaser', 'تیزر'), ('license_image', 'مجوز'))
                 if getattr(obj, key)]
        links += [(reverse('accounts:event_submission_photo', args=[obj.pk, photo.pk]), 'عکس صحنه') for photo in obj.photos.all()]
        return format_html_join(' · ', '<a href="{}" target="_blank" rel="noopener">{}</a>', links)
    uploaded_files.short_description = 'فایل‌های برنامه (دسترسی خصوصی)'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
