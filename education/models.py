import os
import uuid
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.urls import reverse
from django.utils import timezone


class PrivateEducationStorage(FileSystemStorage):
    @property
    def base_location(self):
        return getattr(settings, 'EDUCATION_PRIVATE_ROOT', settings.BASE_DIR / '.private-education')

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError('Education sources have no public URL.')


def private_storage():
    return PrivateEducationStorage()


def video_path(instance, filename):
    return f'sources/{instance.pk}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class Course(models.Model):
    class Kind(models.TextChoices):
        RECORDED = 'recorded', 'دورهٔ ضبط‌شده'
        CLASS = 'class', 'کلاس حضوری'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        PENDING = 'pending', 'در انتظار بررسی'
        REVISION = 'revision', 'نیاز به اصلاح'
        PUBLISHED = 'published', 'منتشرشده'
        PAUSED = 'paused', 'متوقف‌شده'

    SUBJECTS = [('acting', 'بازیگری'), ('directing', 'کارگردانی'), ('music', 'موسیقی و آواز'),
                ('writing', 'نویسندگی'), ('production', 'صحنه و تولید'), ('other', 'سایر هنرها')]
    LEVELS = [('all', 'همهٔ سطح‌ها'), ('beginner', 'مقدماتی'), ('intermediate', 'متوسط'), ('advanced', 'پیشرفته')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='teaching_courses')
    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=160, verbose_name='عنوان آموزش')
    teacher_name = models.CharField(max_length=120, blank=True, verbose_name='نام عمومی مدرس')
    academy = models.CharField(max_length=120, blank=True, verbose_name='نام آموزشگاه یا گروه')
    subject = models.CharField(max_length=20, choices=SUBJECTS, default='acting', verbose_name='حوزهٔ آموزش')
    level = models.CharField(max_length=16, choices=LEVELS, default='all', verbose_name='سطح آموزش')
    summary = models.CharField(max_length=500, blank=True, verbose_name='معرفی کوتاه')
    description = models.TextField(max_length=6000, blank=True, verbose_name='دربارهٔ آموزش')
    outcomes = models.TextField(max_length=2000, blank=True, verbose_name='چه چیزهایی یاد می‌گیریم؟')
    prerequisites = models.TextField(max_length=2000, blank=True, verbose_name='پیش‌نیازها')
    poster = models.ImageField(upload_to='education/posters/%Y/%m/', blank=True, verbose_name='تصویر معرفی')
    price_toman = models.PositiveBigIntegerField(default=0, verbose_name='شهریه یا قیمت (تومان)')
    city = models.CharField(max_length=80, blank=True, verbose_name='شهر')
    address = models.CharField(max_length=500, blank=True, verbose_name='نشانی محل کلاس')
    schedule = models.TextField(max_length=1500, blank=True, verbose_name='روزها، ساعت‌ها و تعداد جلسات')
    start_date = models.DateField(null=True, blank=True, verbose_name='روز آغاز کلاس')
    start_time = models.TimeField(null=True, blank=True, verbose_name='ساعت آغاز')
    end_date = models.DateField(null=True, blank=True, verbose_name='روز پایان کلاس')
    end_time = models.TimeField(null=True, blank=True, verbose_name='ساعت پایان')
    registration_deadline = models.DateField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True, verbose_name='ظرفیت هنرجویان')
    enrollment_open = models.BooleanField(default=True, verbose_name='ثبت‌نام باز است')
    access_suspended = models.BooleanField(default=False, verbose_name='توقف دسترسی به محتوای خریداری‌شده')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    review_note = models.TextField(max_length=2000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_courses')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.CheckConstraint(condition=models.Q(capacity__isnull=True) | models.Q(capacity__gte=1), name='education_positive_capacity')]
        verbose_name = 'آموزش'
        verbose_name_plural = 'آموزش‌ها'

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('education:detail', args=[self.pk])

    @property
    def starts_at(self):
        return timezone.make_aware(datetime.combine(self.start_date, self.start_time)) if self.start_date and self.start_time else None

    @property
    def ends_at(self):
        return timezone.make_aware(datetime.combine(self.end_date, self.end_time)) if self.end_date and self.end_time else None


class Lesson(models.Model):
    class State(models.TextChoices):
        QUEUED = 'queued', 'در صف آماده‌سازی'
        PROCESSING = 'processing', 'در حال آماده‌سازی'
        READY = 'ready', 'آمادهٔ پخش'
        FAILED = 'failed', 'نیاز به بررسی فایل'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='lessons')
    chapter = models.CharField(max_length=100, blank=True, verbose_name='نام فصل')
    title = models.CharField(max_length=160, verbose_name='عنوان درس')
    description = models.TextField(max_length=2000, blank=True, verbose_name='توضیح یا یادداشت درس')
    order = models.PositiveIntegerField(default=1, verbose_name='ترتیب درس')
    is_preview = models.BooleanField(default=False, verbose_name='جلسهٔ نمونهٔ رایگان')
    is_active = models.BooleanField(default=True, verbose_name='نمایش درس')
    source = models.FileField(storage=private_storage, upload_to=video_path)
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED, db_index=True)
    revision = models.UUIDField(default=uuid.uuid4)
    stream_revision = models.UUIDField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'created_at', 'pk']
        verbose_name = 'درس'
        verbose_name_plural = 'درس‌ها'

    @property
    def duration_minutes(self):
        return max(1, (self.duration_seconds + 59) // 60) if self.duration_seconds else 0

    def get_absolute_url(self):
        return reverse('education:watch', args=[self.pk])


class Enrollment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='enrollments')
    learner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='education_enrollments')
    learner_name = models.CharField(max_length=150)
    course_title = models.CharField(max_length=160)
    paid_rial = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=12, choices=[('active', 'ثبت‌نام فعال'), ('refunded', 'بازپرداخت‌شده')], default='active')
    purchased_at = models.DateTimeField(auto_now_add=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-purchased_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['course', 'learner'], name='education_unique_enrollment')]
        verbose_name = 'ثبت‌نام آموزش'
        verbose_name_plural = 'ثبت‌نام‌های آموزش'


class LessonProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='progress')
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT, related_name='progress')
    position_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['enrollment', 'lesson'], name='education_unique_progress')]
