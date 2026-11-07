import uuid
from django.conf import settings
from django.db import models
from django.urls import reverse


class Studio(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        PENDING = 'pending', 'در انتظار بررسی'
        REVISION = 'revision', 'نیاز به اصلاح'
        PUBLISHED = 'published', 'منتشرشده'
        PAUSED = 'paused', 'متوقف‌شده'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='studios')
    title = models.CharField(max_length=160, verbose_name='نام پلاتو')
    city = models.CharField(max_length=80, blank=True, verbose_name='شهر')
    district = models.CharField(max_length=100, blank=True, verbose_name='محله')
    address = models.CharField(max_length=500, blank=True, verbose_name='نشانی کامل')
    description = models.TextField(max_length=6000, blank=True, verbose_name='معرفی فضا')
    amenities = models.TextField(max_length=2000, blank=True, verbose_name='امکانات')
    rules = models.TextField(max_length=2000, blank=True, verbose_name='قوانین استفاده')
    area = models.PositiveIntegerField(null=True, blank=True, verbose_name='مساحت (متر مربع)')
    capacity = models.PositiveIntegerField(null=True, blank=True, verbose_name='ظرفیت افراد')
    hourly_price = models.PositiveBigIntegerField(default=0, verbose_name='هزینهٔ پایهٔ هر ساعت (تومان)')
    cover = models.ImageField(upload_to='studios/%Y/%m/', blank=True, verbose_name='عکس اصلی پلاتو')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    booking_open = models.BooleanField(default=True)
    review_note = models.TextField(max_length=2000, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    schedule_version = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        verbose_name = 'پلاتو'
        verbose_name_plural = 'پلاتوها'

    def __str__(self): return self.title
    def get_absolute_url(self): return reverse('studios:detail', args=[self.pk])


class StudioPhoto(models.Model):
    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='studios/gallery/%Y/%m/')
    caption = models.CharField(max_length=160, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Booking(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    studio = models.ForeignKey(Studio, on_delete=models.PROTECT, related_name='bookings')
    renter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='studio_bookings')
    renter_name = models.CharField(max_length=150)
    studio_title = models.CharField(max_length=160)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    hours = models.PositiveSmallIntegerField()
    paid_rial = models.PositiveBigIntegerField()
    status = models.CharField(max_length=12, choices=[('confirmed', 'رزرو قطعی'), ('cancelled', 'لغو و بازپرداخت‌شده')], default='confirmed')
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_note = models.CharField(max_length=2000, blank=True)

    class Meta:
        ordering = ['-starts_at', '-pk']
        constraints = [models.CheckConstraint(condition=models.Q(ends_at__gt=models.F('starts_at')), name='studios_booking_valid_range')]
        verbose_name = 'رزرو پلاتو'
        verbose_name_plural = 'رزروهای پلاتو'


class StudioSlot(models.Model):
    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, related_name='slots')
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    price_toman = models.PositiveBigIntegerField()
    state = models.CharField(max_length=10, choices=[('open', 'قابل رزرو'), ('closed', 'بسته'), ('blocked', 'رزرو خارج از سایت')], default='open')
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, null=True, blank=True, related_name='slots')
    private_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['starts_at', 'pk']
        constraints = [models.UniqueConstraint(fields=['studio', 'starts_at'], name='studios_unique_start'),
                       models.CheckConstraint(condition=models.Q(ends_at__gt=models.F('starts_at')), name='studios_slot_valid_range')]
