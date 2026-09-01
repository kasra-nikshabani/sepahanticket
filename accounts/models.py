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
    GENDER_CHOICES = (
        ('male', 'مرد'),
        ('female', 'زن'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPES, default='normal')
    phone_number = models.CharField(max_length=11, unique=True, null=True, blank=True)
    national_code = models.CharField(max_length=10, unique=True, null=True, blank=True, verbose_name="کد ملی")
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, null=True, blank=True, verbose_name="جنسیت")
    is_phone_verified = models.BooleanField(default=False)
    # عمداً user_type جدید (مثلاً 'basa') نساختیم -- ورود با OTP همین الان فقط
    # برای user_type='normal' مجازه (accounts/backends.py) و اضافه‌کردن یک
    # user_type جدید یعنی دست‌زدن به مسیر احراز هویت. عضو باسا بودن فقط یک
    # فلگ روی کاربر عادیه، رفتار لاگین/خریدش هیچ فرقی با بقیه ندارد.
    is_basa_member = models.BooleanField(default=False, verbose_name="عضو باسا")

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
    bypass_civil_registry_inquiry = models.BooleanField(
        default=False,
        verbose_name="غیرفعال‌سازی استعلام ثبت‌احوال (حالت اضطراری)",
        help_text="فقط برای مواقعی که سرویس استعلام ثبت‌احوال قطع/خراب است. در صورت "
                   "فعال بودن، خریدار بلیط بدون تأیید هویت از ثبت‌احوال می‌تواند خرید را "
                   "تکمیل کند (فقط فرمت اطلاعات -- نام فارسی و کد ملی ۱۰ رقمی -- چک "
                   "می‌شود). محاسبه‌ی قیمت و سن هیچ‌وقت به این سرویس وابسته نیست و همیشه "
                   "سمت سرور مستقل دوباره محاسبه می‌شود.",
    )
    wallet_enabled = models.BooleanField(
        default=True,
        verbose_name="فعال بودن کیف پول",
        help_text="با غیرفعال کردن این گزینه، کیف پول کاملاً از چرخه خارج می‌شود: "
                   "کاربر نه می‌تواند کیف پولش را شارژ کند و نه می‌تواند بخشی از "
                   "هزینه‌ی بلیط را از کیف پول بپردازد. موجودی فعلی کاربران پاک "
                   "نمی‌شود و صفحه‌ی کیف پول برای دیدن موجودی و تاریخچه باز می‌ماند؛ "
                   "با فعال کردن دوباره، همان موجودی قبلی دوباره قابل استفاده است. "
                   "بازگشت وجه (لغو مسابقه یا مابه‌التفاوت پرداخت) همیشه — حتی در "
                   "حالت غیرفعال — به کیف پول واریز می‌شود تا پول کاربر گم نشود.",
    )

    # ===== چرا این کلید از wallet_enabled جدا شد =====
    # «خرج کردن موجودی» و «شارژ کردن کیف پول» دو تصمیم مستقل‌اند. بعد از
    # جبرانِ پرداخت‌های تحویل‌نشده، موجودیِ واریزشده باید قابل استفاده باشد
    # ولی باشگاه نمی‌خواهد کاربر پول تازه‌ای وارد کیف پول کند. با یک کلیدِ
    # مشترک، این حالت اصلاً قابل بیان نبود.
    wallet_charge_enabled = models.BooleanField(
        default=False,
        verbose_name="امکان شارژ کیف پول",
        help_text="اگر خاموش باشد کاربر نمی‌تواند کیف پولش را شارژ کند، ولی "
                  "موجودی فعلی‌اش همچنان برای خرید بلیط قابل استفاده است "
                  "(به شرطی که «فعال بودن کیف پول» روشن باشد).",
    )
    free_under_15 = models.BooleanField(
        default=True,
        verbose_name="رایگان بودن بلیط برای زیر ۱۵ سال",
        help_text="در حالت فعال، هر بلیطی که سنِ تأییدشده‌ی صاحبش کمتر از ۱۵ سال "
                   "باشد رایگان می‌شود. با غیرفعال کردن، زیر ۱۵ ساله‌ها هم مثل "
                   "بقیه قیمت کامل بلوک را می‌پردازند (تخفیف باسا و کد تخفیف "
                   "طبق روال عادی روی همان قیمت اعمال می‌شود). این تنظیم روی "
                   "بلیط‌هایی که از قبل رایگان صادر شده‌اند اثری ندارد.",
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
        # حافظه‌ی محلیِ همین پروسه را هم باطل کن، وگرنه پروسه‌ای که تغییر را
        # ذخیره کرده تا SOLO_LOCAL_TTL ثانیه مقدار قدیمی خودش را می‌بیند.
        SiteSettings._local_cache = (0.0, None)

    # ===== حافظه‌ی محلیِ هر پروسه =====
    # get_solo روی *هر* درخواست حداقل دو بار صدا زده می‌شود (میدل‌ور کنترل
    # دسترسی جغرافیایی + context processor کیف پول). حتی با کش Redis، هر
    # فراخوانی یعنی یک رفت‌وبرگشت شبکه به‌علاوه‌ی unpickle کردن یک شیء مدل --
    # و در نمونه‌برداری از CPU روز دربی همین دو نقطه بالاترین سهم را داشتند،
    # چون روی ۱۰۰٪ ترافیک اجرا می‌شوند. چند ثانیه نگه‌داشتن نتیجه داخل خودِ
    # پروسه، این هزینه را عملاً صفر می‌کند. تأخیر انتشار تغییرات حداکثر
    # SOLO_LOCAL_TTL ثانیه است (کش Redis از قبل هم ۳۰ ثانیه تأخیر داشت).
    SOLO_LOCAL_TTL = 5
    _local_cache = (0.0, None)

    @classmethod
    def get_solo(cls):
        import time
        from django.core.cache import cache

        ts, cached = SiteSettings._local_cache
        now = time.monotonic()
        if cached is not None and (now - ts) < cls.SOLO_LOCAL_TTL:
            return cached

        obj = cache.get(SITE_SETTINGS_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(SITE_SETTINGS_CACHE_KEY, obj, 30)
        SiteSettings._local_cache = (now, obj)
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
