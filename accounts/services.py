# accounts/services/sms.py
import random
import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from .models import OTP

import logging

logger = logging.getLogger(__name__)

OTP_COOLDOWN_SECONDS = 60


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
            response = requests.post(url, json=payload, headers=headers, timeout=10)
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
        response = requests.post(url, json=payload, headers=headers, timeout=10)
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


def create_otp(phone_number):
    """ایجاد کد OTP جدید و ارسال آن"""
    # ===== Rate limit سمت بک‌اند (مستقل از session) =====
    # cache.add اتمیک است: اگر کلید از قبل موجود باشد False برمی‌گرداند، پس
    # حتی دو درخواست هم‌زمان هم نمی‌توانند هر دو رد شوند.
    cooldown_key = f'otp_cooldown:{phone_number}'
    if not cache.add(cooldown_key, 1, timeout=OTP_COOLDOWN_SECONDS):
        ttl = cache.ttl(cooldown_key) if hasattr(cache, 'ttl') else None
        raise OTPRateLimitError(retry_after=int(ttl) if ttl else OTP_COOLDOWN_SECONDS)

    # چون قفل بالا از تولید بیش‌ازحد کد جلوگیری می‌کند، خیالمان راحت است که
    # کدهای قبلیِ استفاده‌نشده‌ی این شماره را هم پاک کنیم -- فقط آخرین کد
    # صادرشده معتبر باشد (چه هنوز منقضی نشده باشد چه شده باشد).
    OTP.objects.filter(phone_number=phone_number, is_used=False).delete()

    code = generate_otp_code()

    # ===== لاگ قوی برای دیباگ =====
    print(f"\n{'=' * 50}")
    print(f"📱 NEW OTP GENERATED")
    print(f"📞 Phone: {phone_number}")
    print(f"🔑 Code: {code}")
    print(f"⏰ Expires in 1 minute")
    print(f"{'=' * 50}\n")

    otp = OTP.objects.create(
        phone_number=phone_number,
        code=code,
        expires_at=timezone.now() + timezone.timedelta(minutes=1)
    )

    # ارسال پیامک
    success, msg = send_sms_via_smsir(phone_number, code)
    if not success:
        otp.delete()
        # چون پیامک واقعاً ارسال نشده، قفل ۶۰ ثانیه‌ای را هم آزاد می‌کنیم
        # تا خرابی موقت سرویس پیامک باعث انتظار بی‌خودِ کاربر نشود.
        cache.delete(cooldown_key)
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
