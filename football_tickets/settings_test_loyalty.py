# football_tickets/settings_test_loyalty.py
"""
Settings مخصوص اجرای تست‌های Endpoint جدید Loyalty Polling (Phase 12 در sepapp) --
استفاده:

    DJANGO_SETTINGS_MODULE=football_tickets.settings_test_loyalty python manage.py test tickets.tests

هم‌دلیل settings_test.py (Phase 7): کاربر دیتابیس این پروژه (sepahan_user) عمداً
CREATEDB ندارد، پس migrate/test روی settings.py اصلی با خطای دسترسی شکست می‌خورد.
برخلاف settings_test.py که فقط برای accounts.tests است (و عمداً migrations
tickets/matches را غیرفعال می‌کند)، این‌جا دقیقاً برعکس لازم است: تست‌های
tickets.tests به جدول‌های واقعی Order/Match/Stadium نیاز دارند -- پس فقط
payments/wallet (که برای این تست‌ها لازم نیستند) غیرفعال می‌شوند.

هیچ‌چیز در settings.py یا settings_test.py تغییر نکرده -- کاملاً جدا و اختیاری است.

نکته: migration جدول tickets به wallet وابسته است (Transaction مربوط به کیف‌پول) --
پس wallet را نمی‌شود غیرفعال کرد، فقط payments (که چیزی از آن به tickets وابسته نیست).
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

MIGRATION_MODULES = {app: None for app in ('payments',)}

# مقدار فقط برای تست -- production واقعی از .env (LOYALTY_POLL_SERVICE_TOKEN) می‌خواند
LOYALTY_POLL_SERVICE_TOKEN = 'test-only-token-never-used-in-production'
