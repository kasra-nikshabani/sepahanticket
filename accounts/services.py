import random
import requests
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import OTP

def generate_otp_code():
    """تولید کد تصادفی ۶ رقمی"""
    return str(random.randint(100000, 999999))

def send_sms_via_smsir(phone_number, message):
    """
    ارسال پیامک از طریق sms.ir
    مستندات: https://sms.ir/docs/rest-api/
    """
    url = settings.SMS_IR_SEND_URL
    headers = {
        'X-API-KEY': settings.SMS_IR_API_KEY,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    payload = {
        'lineNumber': settings.SMS_IR_LINE_NUMBER,
        'to': [phone_number],
        'message': message,
        'sendDateTime': None,  # ارسال فوری
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        result = response.json()

        if response.status_code == 200 and result.get('status') == 1:
            return True, result.get('message', 'پیامک با موفقیت ارسال شد.')
        else:
            error_msg = result.get('message', 'خطا در ارسال پیامک')
            return False, error_msg

    except requests.exceptions.RequestException as e:
        return False, str(e)

def create_otp(phone_number):
    """ایجاد کد OTP جدید و ارسال آن"""
    # حذف کدهای قبلی منقضی‌شده
    OTP.objects.filter(phone_number=phone_number, expires_at__lt=timezone.now()).delete()

    code = generate_otp_code()
    otp = OTP.objects.create(
        phone_number=phone_number,
        code=code,
        expires_at=timezone.now() + timedelta(minutes=5)
    )

    # ارسال پیامک
    message = f"کد تأیید شما: {code}\nاین کد تا ۵ دقیقه اعتبار دارد."
    success, msg = send_sms_via_smsir(phone_number, message)

    if not success:
        # در صورت خطا، OTP ایجاد شده را حذف کن تا کاربر دوباره تلاش کند
        otp.delete()
        raise Exception(f"خطا در ارسال پیامک: {msg}")

    return otp