# accounts/services/sms.py
import random
import re
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from .models import OTP

import logging

logger = logging.getLogger(__name__)

OTP_COOLDOWN_SECONDS = 60

# ===== مدت اعتبار کد ورود =====
# یک دقیقه خیلی کوتاه بود: کاربر تا پیامک برسد و کد را وارد کند، اغلب کد
# منقضی شده بود و مجبور می‌شد دوباره درخواست بدهد -- که هم تجربه‌ی بدی بود
# و هم روز مسابقه بار اضافی روی سرویس پیامک و خودِ سایت می‌گذاشت.
OTP_VALIDITY_MINUTES = 5

# ===== احترام به مهلتی که خودِ سرویس پیامک اعلام می‌کند =====
# وقتی sms.ir حساب را محدود می‌کند، در متن خطا می‌گوید چند ثانیه بعد
# دوباره تلاش کنیم. تا وقتی این را نادیده می‌گرفتیم، هر کاربری که دکمه را
# می‌زد یک درخواست تازه می‌فرستاد، دوباره رد می‌شد و جریمه از نو شروع
# می‌شد -- مهلتِ اعلام‌شده از ۳۵ ثانیه به ۳۵ دقیقه رسیده بود، یعنی عملاً
# خودمان نمی‌گذاشتیم محدودیت تمام شود. حالا تا پایان آن مهلت اصلاً تماسی
# گرفته نمی‌شود.
#
# سقف عمداً کوتاه است: اگر عددِ اعلامی خیلی بزرگ باشد کورکورانه صبر
# نمی‌کنیم، بلکه حداکثر SMS_BLOCK_MAX_SECONDS صبر می‌کنیم و بعد یک تماس
# آزمایشی می‌زنیم تا اگر محدودیت زودتر برداشته شده بود، سرویس بلافاصله
# برگردد.
SMS_BLOCK_KEY = 'sms_provider_blocked_until'
SMS_BLOCK_MAX_SECONDS = 180
SMS_BLOCK_MIN_SECONDS = 20


# ===== تایم‌اوت تماس با سرویس پیامک =====
# عمداً کوتاه: این تماس داخل چرخه‌ی درخواست انجام می‌شود و هر ثانیه‌ای که
# طول بکشد یک worker گانیکورن را قفل نگه می‌دارد. زیر بار بالا (روز
# مسابقه) با تایم‌اوت ۱۰ ثانیه، چند صد درخواستِ معطلِ پیامک کافی بود تا
# همه‌ی workerها اشغال شوند و کل سایت کند شود.
SMS_TIMEOUT = 4

# ===== اتصال پایدار به سرویس پیامک =====
# requests.post ساده برای هر پیامک یک اتصال TLS تازه می‌سازد؛ خودِ
# handshake چند صد میلی‌ثانیه است و در تمام آن مدت یک نخ گانیکورن اشغال
# می‌ماند. روز مسابقه در نمونه‌برداری از پشته‌ی نخ‌ها، چندین نخ هم‌زمان
# داخل do_handshake دیده شدند. با یک Session مشترک، اتصال باز می‌ماند و
# پیامک‌های بعدی از همان استفاده می‌کنند (بدون handshake دوباره).
_sms_session = requests.Session()
_sms_session.mount('https://', requests.adapters.HTTPAdapter(
    pool_connections=8, pool_maxsize=64, max_retries=0,
))


class SMSProviderBusyError(Exception):
    """سرویس پیامک خودش ما را محدود کرده یا در دسترس نیست."""
    def __init__(self, message, retry_after=30):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class OTPRateLimitError(Exception):
    """
    برای یک شماره تلفن، در کمتر از OTP_COOLDOWN_SECONDS ثانیه دوباره
    درخواست کد شده. مستقل از session/کوکی است (کلید آن فقط شماره تلفن
    در Redis است)، پس هر ویویی که create_otp را صدا بزند -- ورود، ثبت‌نام،
    یا دکمه‌ی ارسال مجدد -- به‌طور یکسان محدود می‌شود؛ محدودیتِ سمت
    فرانت‌اند (تایمر) صرفاً برای تجربه‌ی کاربری است و به‌تنهایی قابل دور زدن است.
    """

    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__(f'لطفاً {retry_after} ثانیه دیگر دوباره تلاش کنید.')


# ================================================
#  تنظیمات Sandbox (از settings.py دریافت می‌شود)
# ================================================
# SMS_IR_SANDBOX = True  # در settings.py تعریف کنید
# SMS_IR_API_KEY = 'sandbox-api-key'  # کلید مخصوص Sandbox
# SMS_IR_SEND_URL = 'https://api.sms.ir/v1/send/verify'  # برای متد Verify
# SMS_IR_TEMPLATE_ID = 123456  # قالب پیش‌فرض Sandbox

# accounts/services/sms.py

def generate_otp_code():
    """تولید کد تصادفی ۵ رقمی"""
    return str(random.randint(1000, 9999))  # ← ۴ رقمی


# accounts/services/sms.py

# accounts/services/sms.py

def send_sms_via_smsir(phone_number, code):
    """
    ارسال پیامک از طریق sms.ir (با پشتیبانی از Sandbox)
    """
    # ===== حالت Sandbox (آزمایشی) =====
    if settings.SMS_IR_SANDBOX:
        url = settings.SMS_IR_SEND_URL
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/plain',
            'x-api-key': settings.SMS_IR_API_KEY,
        }
        payload = {
            'mobile': phone_number,
            'templateId': settings.SMS_IR_TEMPLATE_ID,
            'parameters': [
                {
                    'name': 'Code',
                    'value': code
                }
            ]
        }

        try:
            response = _sms_session.post(url, json=payload, headers=headers, timeout=SMS_TIMEOUT)
            result = response.json()

            if response.status_code == 200 and result.get('status') == 1:
                return True, result.get('message', 'پیامک با موفقیت ارسال شد (Sandbox).')
            else:
                error_msg = result.get('message', 'خطا در ارسال پیامک (Sandbox)')
                return False, error_msg

        except requests.exceptions.RequestException as e:
            return False, str(e)

    # ===== حالت شبیه‌سازی در محیط توسعه (DEBUG) =====
    if settings.DEBUG:
        print(f"\n{'=' * 40}")
        print(f"📱 SIMULATED SMS TO: {phone_number}")
        print(f"📝 CODE: {code}")
        print(f"{'=' * 40}\n")
        return True, "شبیه‌سازی پیامک موفق (محیط توسعه)"

    # ===== ارسال واقعی (Production) =====
    url = settings.SMS_IR_SEND_URL
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'text/plain',
        'x-api-key': settings.SMS_IR_API_KEY,
    }
    payload = {
        'mobile': phone_number,
        'templateId': settings.SMS_IR_TEMPLATE_ID,
        'parameters': [
            {
                'name': 'Code',
                'value': code
            }
        ]
    }

    try:
        response = _sms_session.post(url, json=payload, headers=headers, timeout=SMS_TIMEOUT)
        result = response.json()

        if response.status_code == 200 and result.get('status') == 1:
            logger.info(
                f"SMS sent successfully to {phone_number}, MessageId: {result.get('data', {}).get('messageId')}"
            )
            return True, result.get('message', 'پیامک با موفقیت ارسال شد.')
        else:
            error_msg = result.get('message', 'خطا در ارسال پیامک')
            logger.error(f"SMS error for {phone_number}: {error_msg}")
            return False, error_msg

    except requests.exceptions.RequestException as e:
        logger.error(f"SMS request failed for {phone_number}: {str(e)}")
        return False, str(e)


def _sms_block_remaining():
    """چند ثانیه دیگر تا پایان محدودیتِ اعلام‌شده مانده؟ صفر یعنی آزادیم."""
    try:
        ttl = cache.ttl(SMS_BLOCK_KEY) if hasattr(cache, 'ttl') else None
    except Exception:
        return 0
    return int(ttl) if ttl and ttl > 0 else 0


def _set_sms_block(msg):
    """مهلت اعلام‌شده در متن خطا را بخوان و تا آن زمان تماس نگیر."""
    seconds = SMS_BLOCK_MIN_SECONDS
    m = re.search(r'(\d+)\s*ثانیه', msg or '')
    if m:
        try:
            seconds = int(m.group(1))
        except ValueError:
            pass
    seconds = max(SMS_BLOCK_MIN_SECONDS, min(seconds, SMS_BLOCK_MAX_SECONDS))
    try:
        cache.set(SMS_BLOCK_KEY, 1, timeout=seconds)
    except Exception:
        pass
    return seconds


def create_otp(phone_number):
    """ایجاد کد OTP جدید و ارسال آن"""
    # ===== این بررسی باید *اولین* کار باشد =====
    # اگر اپراتور ما را محدود کرده، همین‌جا برمی‌گردیم -- قبل از اینکه کدِ
    # قبلیِ کاربر پاک شود. وقتی این بررسی پایین‌تر بود، کاربری که کد را
    # گرفته بود و دکمه‌ی «ارسال مجدد» را می‌زد، کد سالمش حذف می‌شد و کد
    # جدیدی هم نمی‌آمد؛ یعنی درست همان کسانی که پیامک را دریافت کرده بودند
    # هم از ورود جا می‌ماندند. (نشانه‌اش این بود: ۲۵۰ پیامک موفق در ۹۰
    # ثانیه، ولی صفر کاربر جدید.)
    blocked_ttl = _sms_block_remaining()
    if blocked_ttl:
        raise SMSProviderBusyError(
            'ارسال پیامک موقتاً از سمت اپراتور محدود شده است. '
            f'لطفاً حدود {blocked_ttl} ثانیه دیگر دوباره تلاش کنید.',
            retry_after=blocked_ttl,
        )

    # ===== Rate limit سمت بک‌اند (مستقل از session) =====
    # cache.add اتمیک است: اگر کلید از قبل موجود باشد False برمی‌گرداند، پس
    # حتی دو درخواست هم‌زمان هم نمی‌توانند هر دو رد شوند.
    cooldown_key = f'otp_cooldown:{phone_number}'
    if not cache.add(cooldown_key, 1, timeout=OTP_COOLDOWN_SECONDS):
        ttl = cache.ttl(cooldown_key) if hasattr(cache, 'ttl') else None
        raise OTPRateLimitError(retry_after=int(ttl) if ttl else OTP_COOLDOWN_SECONDS)

    # ===== کد قبلی فقط بعد از ارسالِ *موفقِ* کد جدید پاک می‌شود =====
    # قبلاً همین‌جا (قبل از ارسال) پاک می‌شد. نتیجه این بود که اگر ارسال
    # شکست می‌خورد، کاربر هم کد قبلی‌اش را از دست می‌داد و هم کد جدیدی
    # نمی‌گرفت -- یعنی یک خرابیِ گذرای اپراتور، کسی را که کد سالم در دست
    # داشت هم از ورود محروم می‌کرد. حالا حذف به پایین (بعد از تأیید ارسال)
    # منتقل شده و در مسیر شکست، کد قبلی دست‌نخورده می‌ماند.
    code = generate_otp_code()

    # ===== کد OTP هرگز در لاگ نوشته نمی‌شود =====
    # قبلاً کد و شماره‌ی موبایل با print چاپ می‌شدند و چون gunicorn با
    # --capture-output اجرا می‌شود، مستقیم داخل logs/gunicorn-error.log
    # می‌نشستند: بیش از ۲۳ هزار جفتِ «شماره + کد» در یک فایل با دسترسی
    # ۶۴۴ (خواندنی برای هر کاربر سرور). هرکسی که آن فایل را می‌خواند
    # می‌توانست به‌جای کاربر وارد شود.
    # فقط در حالت DEBUG (توسعه‌ی محلی، بدون کاربر واقعی) چاپ می‌شود.
    if settings.DEBUG:
        print(f"[DEV] OTP for {phone_number}: {code}")
    else:
        logger.info("OTP generated for %s***", phone_number[:6])

    otp = OTP.objects.create(
        phone_number=phone_number,
        code=code,
        expires_at=timezone.now() + timezone.timedelta(minutes=OTP_VALIDITY_MINUTES)
    )

    # ارسال پیامک
    success, msg = send_sms_via_smsir(phone_number, code)
    if success:
        # ارسال تأیید شد: حالا کدهای قبلیِ همین شماره را باطل کن تا فقط
        # تازه‌ترین کد معتبر باشد.
        OTP.objects.filter(
            phone_number=phone_number, is_used=False
        ).exclude(pk=otp.pk).delete()
    if not success:
        otp.delete()
        # چون پیامک واقعاً ارسال نشده، قفل ۶۰ ثانیه‌ای را هم آزاد می‌کنیم
        # تا خرابی موقت سرویس پیامک باعث انتظار بی‌خودِ کاربر نشود.
        cache.delete(cooldown_key)
        # اگر خودِ سرویس پیامک ما را محدود کرده باشد، این یک خطای موقت است
        # نه خرابی سرور -- نباید به کاربر صفحه‌ی ۵۰۰ نشان داده شود.
        low = (msg or '').lower()
        if 'بیشتر از حد مجاز' in (msg or '') or 'too many' in low or 'limit' in low:
            wait = _set_sms_block(msg)
            raise SMSProviderBusyError(
                'ارسال پیامک موقتاً از سمت اپراتور محدود شده است. '
                f'لطفاً حدود {wait} ثانیه دیگر دوباره تلاش کنید.',
                retry_after=wait,
            )
        raise Exception(f"خطا در ارسال پیامک: {msg}")

    return otp


def get_valid_otp(phone_number, code):
    """دریافت OTP معتبر برای شماره و کد داده‌شده"""
    try:
        otp = OTP.objects.get(phone_number=phone_number, code=code, is_used=False)
        logger.debug(f"OTP found for {phone_number}: code={code}, expires={otp.expires_at}")
        if otp.is_valid():
            logger.debug("OTP is valid")
            return otp
        else:
            logger.warning(
                f"OTP invalid: is_used={otp.is_used}, attempts={otp.attempts}, expired={timezone.now() > otp.expires_at}")
            return None
    except OTP.DoesNotExist:
        logger.warning(f"No OTP found for {phone_number} with code {code}")
        return None
