# accounts/context_processors.py
from django.conf import settings


def site_settings(request):
    """
    `settings` همان تنظیمات جنگو است (رفتار قبلی، دست‌نخورده).
    `wallet_enabled` از روی SiteSettings خوانده می‌شود تا هر تمپلیتی -- مثل
    منوی بالا و نوار پایین -- بتواند بخش کیف پول را در حالت غیرفعال پنهان کند.
    """
    wallet_enabled = True
    try:
        from .models import SiteSettings
        wallet_enabled = SiteSettings.get_solo().wallet_enabled
    except Exception:
        # موقع migrate اولیه یا اگر جدول هنوز ساخته نشده باشد، نباید کل سایت
        # به خطا بخورد؛ پیش‌فرض همان رفتار قبلی (کیف پول فعال) است.
        pass

    return {
        'settings': settings,
        'wallet_enabled': wallet_enabled,
    }
