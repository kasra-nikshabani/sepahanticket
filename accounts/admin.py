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
        'user_type',
        'is_phone_verified',
        'is_active',
        'is_staff',
    ]
    list_filter = ['user_type', 'is_phone_verified', 'is_active', 'is_staff']
    search_fields = ['phone_number', 'first_name', 'last_name']
    ordering = ['-date_joined']

    fieldsets = (
        (None, {'fields': ('phone_number', 'password')}),
        ('اطلاعات شخصی', {'fields': ('first_name', 'last_name', 'email')}),
        ('نوع کاربر', {'fields': ('user_type',)}),
        ('وضعیت', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_phone_verified')}),
        ('OTP', {'fields': ('otp_code', 'otp_expires_at', 'otp_attempts')}),
        ('تاریخ‌ها', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone_number', 'first_name', 'last_name', 'user_type'),
        }),
    )