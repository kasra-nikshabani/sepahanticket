# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta


class User(AbstractUser):
    USER_TYPES = (
        ('normal', 'کاربر معمولی'),
        ('vip', 'کاربر ویژه'),
        ('admin', 'مدیر'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='normal')
    phone_number = models.CharField(max_length=11, unique=True, null=True, blank=True)
    is_phone_verified = models.BooleanField(default=False)

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"


# accounts/models.py
from django.db import models
from django.utils import timezone
from datetime import timedelta


class OTP(models.Model):
    phone_number = models.CharField(max_length=11, db_index=True)
    code = models.CharField(max_length=5)  # ← تغییر به ۵
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def is_valid(self):
        if self.is_used:
            return False
        if self.attempts >= 3:
            return False
        if timezone.now() > self.expires_at:
            return False
        return True

    def use(self):
        self.is_used = True
        self.save(update_fields=['is_used'])

    def increment_attempts(self):
        self.attempts += 1
        self.save(update_fields=['attempts'])

    def __str__(self):
        return f"{self.phone_number} - {self.code}"
