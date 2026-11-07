# accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta
import uuid
import os
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage


class PrivateSubmissionStorage(FileSystemStorage):
    @property
    def base_location(self):
        return getattr(settings, 'SUBMISSION_UPLOAD_ROOT', settings.BASE_DIR / '.private-submissions')

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def submission_storage():
    return PrivateSubmissionStorage()


def submission_upload_path(instance, filename):
    submission_id = instance.submission_id if hasattr(instance, 'submission_id') else instance.pk
    return f'event_submissions/{submission_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class EventSubmission(models.Model):
    """Organizer-owned proposals, kept separate from live events and ticket inventory."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='event_submissions')
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=(('theater', 'نمایش'), ('concert', 'کنسرت'), ('event', 'رویداد')))
    venue = models.ForeignKey('matches.Stadium', on_delete=models.PROTECT, null=True, blank=True,
                              related_name='organizer_submissions', verbose_name='سالن آماده سامانه')
    published_event = models.OneToOneField('matches.Event', on_delete=models.PROTECT, null=True,
                                          blank=True, related_name='organizer_submission',
                                          verbose_name='برنامه منتشرشده')
    data = models.JSONField(default=dict, blank=True)
    completed_step = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=20, choices=(('draft', 'پیش‌نویس'), ('submitted', 'در انتظار بررسی')), default='draft')
    poster = models.ImageField(upload_to=submission_upload_path, storage=submission_storage, blank=True)
    cover = models.ImageField(upload_to=submission_upload_path, storage=submission_storage, blank=True)
    teaser = models.FileField(upload_to=submission_upload_path, storage=submission_storage, blank=True)
    license_image = models.ImageField(upload_to=submission_upload_path, storage=submission_storage, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'درخواست ایجاد برنامه'
        verbose_name_plural = 'درخواست‌های ایجاد برنامه'

    @property
    def display_title(self):
        return self.published_event.title if self.published_event_id else self.title

    def __str__(self):
        return self.title


class SubmissionPhoto(models.Model):
    submission = models.ForeignKey(EventSubmission, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to=submission_upload_path, storage=submission_storage)

    class Meta:
        ordering = ['pk']


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
    # شناسه‌ی Subject کاربر در Keycloak (Fan ID مرکزی سوپراپ -- ریپوی جدا sepapp).
    # Nullable و Backward-compatible: کاربران قدیمی/موجود این مقدار را ندارند و
    # چیزی برایشان تغییر نمی‌کند. فقط وقتی یک کاربر برای اولین‌بار با توکن
    # Fan ID وارد شود پر می‌شود (JIT Provisioning در accounts/keycloak_auth.py).
    # هدف: از Lookup مکرر بر اساس national_code جلوگیری و Audit/Revoke دقیق‌تر
    # در آینده -- نه جایگزین national_code/phone_number به‌عنوان شناسه‌ی اصلی.
    fan_id_subject = models.CharField(max_length=36, unique=True, null=True, blank=True, verbose_name="Fan ID Subject")

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"


class ArtCardApplication(models.Model):
    """User's request for a Shahr Bank Didavar art card; never stores card secrets."""
    STATUS_CHOICES = (
        ('requested', 'درخواست ثبت‌شده'),
        ('sent_to_bank', 'ارسال‌شده به بانک'),
        ('active', 'صادرشده و فعال'),
        ('rejected', 'نیازمند پیگیری'),
    )
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='art_card_application', verbose_name='کاربر')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='requested', db_index=True)
    bank_reference = models.CharField(max_length=100, blank=True, verbose_name='شناسه پیگیری بانک')
    card_last_four = models.CharField(max_length=4, blank=True, verbose_name='چهار رقم پایانی کارت')
    admin_note = models.TextField(max_length=2000, blank=True, verbose_name='پیام به کاربر')
    requested_at = models.DateTimeField(auto_now_add=True, verbose_name='زمان درخواست')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخرین به‌روزرسانی')

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'درخواست هنرکارت'
        verbose_name_plural = 'درخواست‌های هنرکارت'

    def __str__(self):
        return f'هنرکارت {self.user.get_full_name() or self.user.username}'

    def clean(self):
        if self.card_last_four and (len(self.card_last_four) != 4 or not self.card_last_four.isascii() or not self.card_last_four.isdigit()):
            raise ValidationError({'card_last_four': 'فقط چهار رقم پایانی کارت را وارد کنید.'})


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
    # ===== چرا این کلید پیش‌فرض خاموش است =====
    # روشن شدن این گزینه یعنی مبلغی که همین حالا در کیف پول‌ها بلوکه است
    # می‌تواند از خزانه‌ی باشگاه خارج شود. این یک تصمیم مالی است نه فنی، پس
    # نباید با یک دیپلوی به‌صورت ضمنی روشن شود؛ باید وقتی خزانه‌داری آماده‌ی
    # واریز است، آگاهانه از همین پنل روشن شود.
    withdrawal_enabled = models.BooleanField(
        default=False,
        verbose_name="امکان برداشت وجه از کیف پول",
        help_text="در حالت فعال، کاربر می‌تواند برای پولی که باشگاه به کیف پولش "
                  "برگردانده (جبران بلیط صادرنشده، بازگشت وجه، پرداخت دوباره) "
                  "درخواست برداشت به شبا ثبت کند. پولی که خودِ کاربر از درگاه "
                  "شارژ کرده قابل برداشت نیست. هر درخواست باید در پنل تأیید و "
                  "سپس به‌صورت دستی واریز شود؛ خاموش کردن این گزینه فقط جلوی "
                  "ثبت درخواست تازه را می‌گیرد و درخواست‌های در جریان را لغو نمی‌کند.",
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


class SupportTicket(models.Model):
    class Category(models.TextChoices):
        PROGRAM = 'program', 'مربوط به برنامه'
        GENERAL = 'general', 'پشتیبانی کاربران'

    class Status(models.TextChoices):
        WAITING = 'waiting', 'منتظر پاسخ پشتیبانی'
        ANSWERED = 'answered', 'پاسخ داده شده'
        CLOSED = 'closed', 'بسته شده'

    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_tickets')
    category = models.CharField(max_length=16, choices=Category.choices)
    event = models.ForeignKey('matches.Event', on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    submission = models.ForeignKey(EventSubmission, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    course = models.ForeignKey('education.Course', on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    studio = models.ForeignKey('studios.Studio', on_delete=models.SET_NULL, null=True, blank=True, related_name='support_tickets')
    subject = models.CharField(max_length=160)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.WAITING, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']
        verbose_name = 'تیکت پشتیبانی'
        verbose_name_plural = 'تیکت‌های پشتیبانی'

    @property
    def managed_event_id(self):
        return self.event_id or (self.submission.published_event_id if self.submission_id else None)

    @property
    def program_title(self):
        if self.studio_id:
            return self.studio.title
        if self.course_id:
            return self.course.title
        if self.event_id:
            return self.event.title
        return self.submission.display_title if self.submission_id else 'برنامه حذف شده'

    def __str__(self):
        return self.subject


class SupportMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='support_messages')
    is_staff_reply = models.BooleanField(default=False)
    body = models.TextField(max_length=8000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class Notification(models.Model):
    class Kind(models.TextChoices):
        PUBLICATION = 'publication', 'تأیید برنامه'
        REVIEW = 'review', 'اصلاح اطلاعات برنامه'
        SUPPORT = 'support', 'پاسخ پشتیبانی'
        PURCHASE = 'purchase', 'خرید موفق'
        PAYMENT = 'payment', 'پرداخت تکمیل‌نشده'
        ARTIST = 'artist', 'خبر هنرمندان'

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=180)
    body = models.TextField()
    action_url = models.CharField(max_length=500)
    dedupe_key = models.CharField(max_length=180)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['recipient', 'dedupe_key'], name='notification_recipient_key')]
        indexes = [models.Index(fields=['recipient', 'read_at'], name='notification_unread_idx')]
        verbose_name = 'اعلان کاربر'
        verbose_name_plural = 'اعلان‌های کاربران'
