# tickets/utils.py
import requests
from django.conf import settings
from django.core.cache import cache

# تایم‌اوت تماس با سرویس بیرونیِ هواداری (ثانیه)
FAN_API_TIMEOUT = 5


def get_access_token():
    """دریافت توکن از API و ذخیره در کش"""
    token = cache.get('fan_token')
    if token:
        return token

    if not settings.FAN_API_USERNAME or not settings.FAN_API_PASSWORD:
        raise Exception("FAN_API_USERNAME/FAN_API_PASSWORD در .env تنظیم نشده است")

    url = "https://fans.footballeticket.ir/api/v1/authenticate/login"
    payload = {
        "username": settings.FAN_API_USERNAME,
        "password": settings.FAN_API_PASSWORD
    }

    # ===== تایم‌اوت حیاتی است =====
    # این تماس داخل چرخه‌ی درخواستِ کاربر انجام می‌شود. بدون تایم‌اوت، اگر
    # سرویس بیرونی کند یا قطع باشد، worker گانیکورن تا ابد همان‌جا می‌ماند --
    # چند تای این‌ها کافی است تا کل سایت از کار بیفتد.
    response = requests.post(url, json=payload, timeout=FAN_API_TIMEOUT)
    if response.status_code == 200:
        data = response.json()
        token = data.get('token')
        cache.set('fan_token', token, timeout=3600)  # ۱ ساعت
        return token
    else:
        raise Exception("خطا در دریافت توکن")