# accounts/backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class PhoneBackend(ModelBackend):
    """احراز هویت با شماره تلفن (بدون رمز عبور)"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        # این backend عمداً پسورد را چک نمی‌کند (ورود کاربران عادی فقط با
        # OTP انجام می‌شود). به همین دلیل باید سخت‌گیرانه به کاربران
        # user_type='normal' محدود بماند -- وگرنه چون این backend توی
        # AUTHENTICATION_BACKENDS ثبت شده، فرم ورود با رمز عبور (برای
        # ادمین/VIP) هم از طریق authenticate() این backend را امتحان
        # می‌کند؛ اگر شماره تلفن یک ادمین/VIP هم is_phone_verified باشد
        # (مثلاً بعد از ارتقا از کاربر عادی، یا با تیک‌زدن دستی در پنل
        # ادمین)، هر رمز دلخواهی با آن شماره به‌جای یوزرنیم قبول می‌شد.
        phone = kwargs.get('phone') or username
        if phone is None:
            return None

        try:
            user = User.objects.get(phone_number=phone)
            if user.user_type == 'normal' and user.is_active and user.is_phone_verified:
                return user
            return None
        except User.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None