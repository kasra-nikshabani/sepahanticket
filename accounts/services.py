# accounts/services/sms.py
import random
import requests
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import OTP

import logging

logger = logging.getLogger(__name__)


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
    return str(random.randint(10000, 99999))  # ← ۵ رقمی


def send_sms_via_smsir(phone_number, code):
    """
    ارسال پیامک از طریق sms.ir (با پشتیبانی از Sandbox)
    مستندات: https://sms.ir/docs/rest-api/
    """
    # ===== استفاده از Sandbox در محیط تست =====
    if settings.SMS_IR_SANDBOX:
        url = settings.SMS_IR_SEND_URL  # https://api.sms.ir/v1/send/verify
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'text/plain',
            'x-api-key': settings.SMS_IR_API_KEY,
        }
        payload = {
            'mobile': phone_number,
            'templateId': settings.SMS_IR_TEMPLATE_ID,  # 123456
            'parameters': [
                {
                    'name': 'Code',  # نام پارامتر در قالب
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

    # ===== شبیه‌سازی در محیط توسعه (اگر Sandbox غیرفعال باشد) =====
    if settings.DEBUG:
        print(f"\n{'=' * 40}")
        print(f"📱 SIMULATED SMS TO: {phone_number}")
        print(f"📝 CODE: {code}")
        print(f"{'=' * 40}\n")
        return True, "شبیه‌سازی پیامک موفق (محیط توسعه)"

    # ===== ارسال واقعی در تولید (Production) =====
    # (در صورت نیاز، کد ارسال واقعی را اینجا قرار دهید)
    # ...
    return False, "محیط تولید پیکربندی نشده است."


def create_otp(phone_number):
    """ایجاد کد OTP جدید و ارسال آن"""
    # حذف کدهای قبلی منقضی‌شده
    OTP.objects.filter(phone_number=phone_number, expires_at__lt=timezone.now()).delete()

    code = generate_otp_code()

    # ===== لاگ قوی برای دیباگ =====
    print(f"\n{'=' * 50}")
    print(f"📱 NEW OTP GENERATED")
    print(f"📞 Phone: {phone_number}")
    print(f"🔑 Code: {code}")
    print(f"⏰ Expires in 5 minutes")
    print(f"{'=' * 50}\n")

    otp = OTP.objects.create(
        phone_number=phone_number,
        code=code,
        expires_at=timezone.now() + timezone.timedelta(minutes=5)
    )

    # ارسال پیامک
    success, msg = send_sms_via_smsir(phone_number, code)
    if not success:
        otp.delete()
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
