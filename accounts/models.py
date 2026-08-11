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
    national_code = models.CharField(max_length=10, unique=True, null=True, blank=True, verbose_name="کد ملی")
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


SITE_SETTINGS_CACHE_KEY = 'site_settings:singleton'


class SiteSettings(models.Model):
    """
    تنظیمات سراسری سایت که ادمین بدون نیاز به دسترسی به سرور از پنل ادمین
    جنگو تغییرشون می‌ده. فقط یک ردیف (singleton، pk=1) وجود داره.
    """
    block_foreign_ips = models.BooleanField(
        default=True,
        verbose_name="مسدودسازی آی‌پی‌های خارج از ایران",
        help_text="در صورت فعال بودن، فقط بازدیدکننده‌هایی با آی‌پی ایران می‌توانند "
                   "سایت را ببینند (پنل ادمین از این قانون همیشه مستثناست). "
                   "با غیرفعال کردن این گزینه، آی‌پی‌های خارج از ایران هم اجازه‌ی "
                   "اتصال پیدا می‌کنند.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیمات سایت"
        verbose_name_plural = "تنظیمات سایت"

    def __str__(self):
        return "تنظیمات سایت"

    def save(self, *args, **kwargs):
        from django.core.cache import cache
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(SITE_SETTINGS_CACHE_KEY)

    @classmethod
    def get_solo(cls):
        from django.core.cache import cache
        obj = cache.get(SITE_SETTINGS_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(SITE_SETTINGS_CACHE_KEY, obj, 30)
        return obj


class SiteVisit(models.Model):
    """
    یک ردیف به‌ازای هر بازدیدکننده‌ی یکتا در هر ۲۴ ساعت (نه هر درخواست؛
    VisitTrackingMiddleware با یک فلگ در Redis از نوشتن تکراری در همین
    بازه جلوگیری می‌کند تا زیر بار زیاد فشار اضافه به دیتابیس نیاید).
    """
    visitor_id = models.CharField(max_length=64, db_index=True, help_text="user:<id> یا ip:<آدرس>")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user = models.ForeignKey('accounts.User', null=True, blank=True, on_delete=models.SET_NULL)
    visited_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-visited_at']
        verbose_name = "بازدید سایت"
        verbose_name_plural = "بازدیدهای سایت"

    def __str__(self):
        return f"{self.visitor_id} - {self.visited_at:%Y-%m-%d %H:%M}"
