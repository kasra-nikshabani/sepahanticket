# football_tickets/settings_test.py
"""
Settings مخصوص اجرای تست‌های Phase 7 (Fan ID/Keycloak) -- استفاده:

    DJANGO_SETTINGS_MODULE=football_tickets.settings_test python manage.py test accounts.tests

چرا این فایل لازم است: کاربر دیتابیس این پروژه (sepahan_user) عمداً
CREATEDB ندارد (بررسی‌شده در Phase 7)، پس `manage.py test` معمولی روی
settings.py اصلی با خطای «permission denied to create database» شکست
می‌خورد. override_settings داخل خود تست هم کار نمی‌کند چون Django پایگاه‌داده‌ی
تست را قبل از اجرای هر TestCase (نه به‌ازای هرکدام) می‌سازد. راه‌حل
استاندارد جنگو دقیقاً همین است: یک Settings Module جدا فقط برای تست.

هیچ‌چیز در settings.py اصلی تغییر نکرده -- این فایل کاملاً اختیاری و جدا
است و روی اجرای عادی/Production پروژه هیچ اثری ندارد.
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# اپ‌هایی که تست‌های accounts.tests به جدول‌هایشان نیازی ندارند و ممکن است
# مدل‌های مخصوص Postgres (مثلاً JSONField) داشته باشند که زیر SQLite نشکنند.
MIGRATION_MODULES = {app: None for app in ('matches', 'tickets', 'payments', 'wallet')}
