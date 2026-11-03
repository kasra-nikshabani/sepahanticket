# accounts/backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class PhoneBackend(ModelBackend):
    """احراز هویت با شماره تلفن (بدون رمز عبور)"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        # فقط وقتی صریحاً phone= پاس داده شود کار می‌کند (مسیر OTP).
        # هرگز username را به‌عنوان شماره تفسیر نکن -- وگرنه در فرم ورود با
        # رمز (VIP/ادمین)، اگر آن شماره قبلاً کاربر عادی بوده باشد، این
        # backend بدون چک رمز همان کاربر عادی را برمی‌گرداند و با وجود
        # کاربر ویژه روی همان شماره، رفتار ورود خراب/غیرامن می‌شود.
        phone = kwargs.get('phone')
        if not phone:
            return None

        return User.objects.filter(
            phone_number=phone,
            user_type='normal',
            is_active=True,
            is_phone_verified=True,
        ).first()

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None