# football_tickets/accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User  # مدل کاربری که خودتان ساختی

class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'user_type', 'national_code', 'phone_number')
    list_filter = ('user_type', 'is_active')
    # اضافه کردن فیلدهای جدید به پنل ادمین
    fieldsets = UserAdmin.fieldsets + (
        ('اطلاعات اضافی', {'fields': ('user_type', 'national_code', 'phone_number')}),
    )

admin.site.register(User, CustomUserAdmin)