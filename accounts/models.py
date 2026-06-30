# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta


class User(AbstractUser):
    USER_TYPES = (
        ('admin', 'مدیر'),
        ('vip', 'کاربر ویژه'),
        ('normal', 'کاربر معمولی'),
    )

    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='normal')
    national_code = models.CharField(max_length=10, unique=True, verbose_name="کد ملی")
    phone_number = models.CharField(max_length=11, verbose_name="شماره موبایل")

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

class OTP(models.Model):
    phone_number = models.CharField(max_length=11, verbose_name="شماره موبایل")
    code = models.CharField(max_length=6, verbose_name="کد تأیید")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        verbose_name = "کد یکبار مصرف"
        verbose_name_plural = "کدهای یکبار مصرف"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.phone_number} - {self.code}"

    def is_valid(self):
        return timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=5)
        super().save(*args, **kwargs)