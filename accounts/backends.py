# accounts/backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class PhoneBackend(ModelBackend):
    """احراز هویت با شماره تلفن (بدون رمز عبور)"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        phone = kwargs.get('phone') or username
        if phone is None:
            return None

        try:
            user = User.objects.get(phone_number=phone)
            if user.is_active and user.is_phone_verified:
                return user
            return None
        except User.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None