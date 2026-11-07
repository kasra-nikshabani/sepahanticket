import uuid
from pathlib import Path
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class CreativeRole(models.TextChoices):
    STAGE = 'stage', 'دستیار صحنه'
    DIRECTOR = 'director', 'دستیار کارگردان'
    ACTOR = 'actor', 'بازیگر'
    MUSIC = 'music', 'خواننده / نوازنده'
    LIGHT = 'light', 'طراح و عوامل نور'
    SOUND = 'sound', 'صدابردار و عوامل صدا'
    DESIGN = 'design', 'طراح صحنه / لباس / گریم'
    WRITER = 'writer', 'نویسنده'
    PRODUCTION = 'production', 'عوامل تولید و اجرایی'
    OTHER = 'other', 'سایر تخصص‌ها'


def artist_image_path(instance, filename):
    return f'artists/{instance.pk}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class ArtistProfile(models.Model):
    class Discipline(models.TextChoices):
        ACTOR = 'actor', 'بازیگری'
        DIRECTOR = 'director', 'کارگردانی'
        MUSIC = 'music', 'موسیقی و آواز'
        WRITER = 'writer', 'نویسندگی'
        DESIGN = 'design', 'طراحی و هنرهای تجسمی'
        PRODUCTION = 'production', 'عوامل صحنه و تولید'
        TECHNICAL = 'technical', 'نور، صدا و عوامل فنی'
        OTHER = 'other', 'سایر هنرها'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        PENDING = 'pending', 'در انتظار تأیید'
        APPROVED = 'approved', 'تأیید شده'
        REVISION = 'revision', 'نیاز به اصلاح'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='artist_profile')
    display_name = models.CharField(max_length=120, verbose_name='نام هنری یا نام و نام خانوادگی')
    discipline = models.CharField(max_length=20, choices=Discipline.choices, default=Discipline.ACTOR, verbose_name='حوزهٔ فعالیت')
    specialty = models.CharField(max_length=160, blank=True, verbose_name='معرفی کوتاه تخصص')
    city = models.CharField(max_length=80, blank=True, verbose_name='شهر فعالیت')
    biography = models.TextField(max_length=3000, blank=True, verbose_name='دربارهٔ من')
    avatar = models.ImageField(upload_to=artist_image_path, blank=True, verbose_name='تصویر پروفایل')
    cover = models.ImageField(upload_to=artist_image_path, blank=True, verbose_name='تصویر کاور')
    website = models.URLField(blank=True, verbose_name='وب‌سایت یا شبکهٔ اجتماعی')
    portfolio_url = models.URLField(blank=True, verbose_name='پیوند نمونه‌کار')
    skills = models.TextField(max_length=1000, blank=True, verbose_name='مهارت‌ها')
    experience = models.TextField(max_length=3000, blank=True, verbose_name='سوابق همکاری')
    preferred_role = models.CharField(max_length=20, choices=CreativeRole.choices, blank=True, verbose_name='تخصص موردنظر برای همکاری')
    looking_for_work = models.BooleanField(default=False, verbose_name='آمادهٔ همکاری هستم')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_visible = models.BooleanField(default=True)
    review_note = models.TextField(max_length=2000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_artists')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_name', 'pk']
        verbose_name = 'پروفایل هنرمند'
        verbose_name_plural = 'پروفایل‌های هنرمندان'

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse('artists:detail', args=[self.pk])

    @property
    def is_public(self):
        return self.status == self.Status.APPROVED and self.is_visible and self.owner.is_active


class ArtistFollow(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='artist_follows')
    artist = models.ForeignKey(ArtistProfile, on_delete=models.CASCADE, related_name='follows')
    notify_events = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['user', 'artist'], name='unique_artist_follow')]


class ArtistCredit(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تأیید هنرمند'
        ACCEPTED = 'accepted', 'تأیید شده'
        DECLINED = 'declined', 'تأیید نشده'

    artist = models.ForeignKey(ArtistProfile, on_delete=models.CASCADE, related_name='event_credits')
    event = models.ForeignKey('matches.Event', on_delete=models.CASCADE, related_name='artist_credits')
    role = models.CharField(max_length=80, verbose_name='نقش در برنامه')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='created_artist_credits')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['event__title', 'role', 'pk']
        constraints = [models.UniqueConstraint(fields=['artist', 'event', 'role'], name='unique_artist_event_role')]
        verbose_name = 'نقش هنرمند در برنامه'
        verbose_name_plural = 'ارتباط هنرمندان و برنامه‌ها'

    def __str__(self):
        return f'{self.artist} · {self.role} · {self.event}'


class CollaborationOpportunity(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        PENDING = 'pending', 'در انتظار بررسی'
        REVISION = 'revision', 'نیاز به اصلاح'
        PUBLISHED = 'published', 'منتشرشده'
        CLOSED = 'closed', 'پایان جذب'
        PAUSED = 'paused', 'متوقف‌شده توسط مدیریت'

    class Pay(models.TextChoices):
        RANGE = 'range', 'دستمزد مشخص'
        NEGOTIABLE = 'negotiable', 'دستمزد توافقی'
        UNPAID = 'unpaid', 'بدون دستمزد'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='collaboration_opportunities')
    event = models.ForeignKey('matches.Event', null=True, blank=True, on_delete=models.SET_NULL, related_name='collaboration_opportunities')
    title = models.CharField(max_length=160, verbose_name='عنوان فراخوان')
    project_name = models.CharField(max_length=160, verbose_name='نام پروژه')
    organizer_name = models.CharField(max_length=120, verbose_name='نام عمومی گروه یا مسئول پروژه')
    role = models.CharField(max_length=20, choices=CreativeRole.choices, verbose_name='تخصص موردنیاز')
    description = models.TextField(max_length=6000, verbose_name='شرح همکاری و وظایف')
    requirements = models.TextField(max_length=3000, blank=True, verbose_name='مهارت‌ها و تجربهٔ موردنیاز')
    city = models.CharField(max_length=80, verbose_name='شهر')
    location = models.CharField(max_length=200, blank=True, verbose_name='محل تمرین یا همکاری')
    schedule = models.TextField(max_length=1500, verbose_name='زمان‌بندی تمرین‌ها و همکاری')
    positions = models.PositiveSmallIntegerField(default=1, verbose_name='تعداد افراد موردنیاز')
    deadline = models.DateField(null=True, blank=True, verbose_name='مهلت ارسال درخواست')
    pay_type = models.CharField(max_length=20, choices=Pay.choices, verbose_name='شرایط مالی')
    pay_min = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='حداقل دستمزد (تومان)')
    pay_max = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='حداکثر دستمزد (تومان)')
    pay_details = models.CharField(max_length=500, verbose_name='توضیح پرداخت و نوع همکاری')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    review_note = models.TextField(max_length=2000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_opportunities')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        verbose_name = 'فرصت همکاری'
        verbose_name_plural = 'فرصت‌های همکاری'
        constraints = [models.CheckConstraint(condition=models.Q(positions__gte=1), name='collaboration_positions_positive')]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('artists:opportunity_detail', args=[self.pk])

    @property
    def is_open(self):
        return self.status == self.Status.PUBLISHED and self.owner.is_active and self.deadline is not None and self.deadline >= timezone.localdate()


class CollaborationApplication(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'ارسال‌شده'
        REVIEWING = 'reviewing', 'در حال بررسی'
        INVITED = 'invited', 'دعوت به گفت‌وگو'
        SELECTED = 'selected', 'منتخب؛ منتظر پاسخ شما'
        ACCEPTED = 'accepted', 'همکاری تأییدشده'
        DECLINED = 'declined', 'پذیرفته‌نشده'
        WITHDRAWN = 'withdrawn', 'انصراف داده‌شده'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opportunity = models.ForeignKey(CollaborationOpportunity, on_delete=models.CASCADE, related_name='applications')
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='collaboration_applications')
    artist = models.ForeignKey(ArtistProfile, on_delete=models.PROTECT, related_name='collaboration_applications')
    introduction = models.TextField(max_length=3000, verbose_name='چرا برای این همکاری مناسب هستید؟')
    availability = models.CharField(max_length=500, verbose_name='زمان‌های در دسترس شما')
    portfolio_url = models.URLField(blank=True, verbose_name='پیوند نمونه‌کار مرتبط')
    profile_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['opportunity', 'applicant'], name='unique_collaboration_application')]

    def __str__(self):
        return f'{self.opportunity} · {self.profile_snapshot.get("name", "متقاضی")}'

    def get_absolute_url(self):
        return reverse('artists:application_detail', args=[self.pk])


class CollaborationMessage(models.Model):
    application = models.ForeignKey(CollaborationApplication, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField(max_length=3000, verbose_name='پیام')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class CollaborationStatusChange(models.Model):
    application = models.ForeignKey(CollaborationApplication, on_delete=models.CASCADE, related_name='status_changes')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=CollaborationApplication.Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class CollaborationReport(models.Model):
    opportunity = models.ForeignKey(CollaborationOpportunity, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    reason = models.TextField(max_length=2000, verbose_name='علت گزارش')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='resolved_collaboration_reports')
    resolution = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        constraints = [models.UniqueConstraint(fields=['opportunity', 'reporter'], condition=models.Q(resolved_at__isnull=True), name='unique_open_collaboration_report')]
