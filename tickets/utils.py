# tickets/utils.py
import requests
from django.conf import settings
from django.core.cache import cache

# تایم‌اوت تماس با سرویس بیرونیِ هواداری (ثانیه)
FAN_API_TIMEOUT = 4

# اتصال پایدار (همان دلیل _sms_session در accounts/services.py): بدون آن
# هر استعلام یک TLS handshake کامل است و در تمام مدتش یک نخ اشغال می‌ماند.
fan_session = requests.Session()
fan_session.mount('https://', requests.adapters.HTTPAdapter(
    pool_connections=8, pool_maxsize=64, max_retries=0,
))

# ===== مدار شکن (circuit breaker) برای سرویس هواداری =====
# تایم‌اوت به‌تنهایی کافی نیست. وقتی fans.footballeticket.ir هنگ می‌کند
# (TCP وصل می‌شود ولی هیچ پاسخی نمی‌دهد)، هر درخواستِ استعلام یک نخِ
# گانیکورن را تا آخرِ تایم‌اوت قفل نگه می‌دارد. روز مسابقه با ~۱۵۰۰
# استعلام در دقیقه، همین کافی بود که همه‌ی نخ‌ها اشغال شوند، صف
# listen گانیکورن پر شود و nginx حتی نتواند وصل شود -- یعنی کل سایت
# به‌خاطر خرابیِ یک سرویس بیرونی از کار می‌افتاد.
#
# منطق: بعد از FAN_API_FAIL_THRESHOLD خطای پشت‌سرهم، مدار «باز» می‌شود و
# به مدت FAN_API_OPEN_SECONDS ثانیه اصلاً تماسی گرفته نمی‌شود؛ بلافاصله
# خطای قابل‌فهم برمی‌گردد (بدون قفل کردن نخ). اولین تماسِ موفق بعد از آن،
# مدار را می‌بندد.
FAN_API_FAIL_THRESHOLD = 5
FAN_API_OPEN_SECONDS = 60
_FAN_FAIL_KEY = 'fan_api_fails'
_FAN_OPEN_KEY = 'fan_api_circuit_open'


class FanAPIDownError(Exception):
    """سرویس استعلام هواداری در دسترس نیست (مدار باز است)."""

    def __init__(self, message='سرویس استعلام ثبت‌احوال موقتاً در دسترس نیست. لطفاً چند دقیقه دیگر دوباره تلاش کنید.'):
        super().__init__(message)
        self.message = message


def fan_api_is_down():
    """آیا مدار باز است؟ (یعنی نباید به سرویس بیرونی دست بزنیم)"""
    return bool(cache.get(_FAN_OPEN_KEY))


def record_fan_api_failure():
    """یک خطای تماس با سرویس هواداری را ثبت کن و در صورت لزوم مدار را باز کن."""
    try:
        fails = cache.get(_FAN_FAIL_KEY, 0) + 1
        cache.set(_FAN_FAIL_KEY, fails, timeout=FAN_API_OPEN_SECONDS)
        if fails >= FAN_API_FAIL_THRESHOLD:
            cache.set(_FAN_OPEN_KEY, 1, timeout=FAN_API_OPEN_SECONDS)
    except Exception:
        # خرابیِ کش نباید خودش باعث خطا شود
        pass


def record_fan_api_success():
    """تماس موفق: شمارنده و مدار را پاک کن."""
    try:
        cache.delete(_FAN_FAIL_KEY)
        cache.delete(_FAN_OPEN_KEY)
    except Exception:
        pass


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
    # اگر مدار باز است، اصلاً تماس نگیر -- فوراً خطا بده تا نخ آزاد بماند.
    if fan_api_is_down():
        raise FanAPIDownError()

    try:
        response = fan_session.post(url, json=payload, timeout=FAN_API_TIMEOUT)
    except requests.exceptions.RequestException:
        record_fan_api_failure()
        raise FanAPIDownError()

    if response.status_code == 200:
        data = response.json()
        token = data.get('token')
        cache.set('fan_token', token, timeout=3600)  # ۱ ساعت
        record_fan_api_success()
        return token
    else:
        record_fan_api_failure()
        raise FanAPIDownError()