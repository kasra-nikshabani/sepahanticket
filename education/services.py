from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from accounts.notifications import notify
from wallet.models import Wallet, is_wallet_enabled
from .models import Course, Enrollment


def public_courses():
    return Course.objects.filter(status='published', owner__is_active=True, access_suspended=False)


def registration_issue(course):
    if course.status != 'published' or not course.owner.is_active or course.access_suspended:
        return 'ثبت‌نام این آموزش در دسترس نیست.'
    if not course.enrollment_open:
        return 'ثبت‌نام این آموزش بسته است.'
    if course.kind == 'class':
        if not course.starts_at or course.starts_at <= timezone.now():
            return 'مهلت ثبت‌نام این کلاس پایان یافته است.'
        if course.registration_deadline and course.registration_deadline < timezone.localdate():
            return 'مهلت ثبت‌نام این کلاس پایان یافته است.'
        if not course.capacity or course.enrollments.filter(status='active').count() >= course.capacity:
            return 'ظرفیت کلاس تکمیل شده است.'
    elif not course.lessons.filter(is_active=True, stream_revision__isnull=False).exists():
        return 'محتوای این دوره هنوز آماده نیست.'
    return ''


def publication_errors(course):
    errors = []
    for field, label in [('teacher_name', 'نام مدرس'), ('summary', 'معرفی کوتاه'), ('description', 'توضیحات'), ('outcomes', 'سرفصل‌ها و دستاوردها')]:
        if not getattr(course, field).strip():
            errors.append(f'{label} را کامل کنید.')
    if course.kind == 'class':
        if not all([course.city.strip(), course.address.strip(), course.schedule.strip(), course.starts_at, course.ends_at, course.capacity, course.registration_deadline]):
            errors.append('محل، برنامهٔ جلسات، تاریخ‌ها، مهلت ثبت‌نام و ظرفیت کلاس را کامل کنید.')
        if course.starts_at and course.starts_at <= timezone.now():
            errors.append('تاریخ آغاز کلاس باید در آینده باشد.')
        if course.starts_at and course.ends_at and course.ends_at < course.starts_at:
            errors.append('پایان کلاس نمی‌تواند پیش از آغاز آن باشد.')
        if course.registration_deadline and course.registration_deadline < timezone.localdate():
            errors.append('مهلت ثبت‌نام گذشته است.')
        if course.registration_deadline and course.starts_at and course.registration_deadline > timezone.localtime(course.starts_at).date():
            errors.append('مهلت ثبت‌نام نمی‌تواند پس از آغاز کلاس باشد.')
    else:
        lessons = course.lessons.filter(is_active=True)
        if not lessons.exists():
            errors.append('حداقل یک درس ویدئویی اضافه کنید.')
        elif lessons.exclude(state='ready', stream_revision=F('revision')).exists():
            errors.append('آماده‌سازی همهٔ ویدئوهای فعال باید تکمیل شود.')
    return errors


@transaction.atomic
def enroll(user, course_id, expected_price, learner_name):
    course = Course.objects.select_for_update().select_related('owner').get(pk=course_id)
    existing = Enrollment.objects.select_for_update().filter(course=course, learner=user).first()
    if existing and existing.status == 'active':
        return existing, False
    if user.pk == course.owner_id:
        raise ValueError('مدرس از پنل تدریس به محتوای خودش دسترسی دارد.')
    if issue := registration_issue(course):
        raise ValueError(issue)
    if str(course.price_toman) != str(expected_price):
        raise ValueError('قیمت آموزش تغییر کرده است؛ مبلغ تازه را بررسی و دوباره تأیید کنید.')
    amount = course.price_toman * 10
    if amount:
        if not is_wallet_enabled():
            raise ValueError('پرداخت از کیف پول در حال حاضر غیرفعال است.')
        wallet, _ = Wallet.objects.get_or_create(user=user)
        if not wallet.deduct_balance(amount, f'آموزش: {course.title}', f'education-{course.pk}-{user.pk}', tx_type='education_purchase'):
            raise ValueError('موجودی کیف پول کافی نیست؛ ابتدا کیف پول را شارژ کنید.')
    enrollment = existing or Enrollment(course=course, learner=user)
    enrollment.learner_name = learner_name
    enrollment.course_title = course.title
    enrollment.paid_rial = amount
    enrollment.status = 'active'
    enrollment.refunded_at = None
    if existing:
        enrollment.purchased_at = timezone.now()
    enrollment.save()
    key = f'education:{enrollment.pk}:{enrollment.purchased_at.isoformat()}'
    notify(user, 'purchase', 'به مسیر یادگیری خوش آمدید', f'ثبت‌نام شما در «{course.title}» انجام شد.', reverse('education:my_learning'), key)
    notify(course.owner, 'purchase', 'هنرجوی تازه در آموزش شما', f'یک ثبت‌نام تازه برای «{course.title}» انجام شد.', reverse('education:manage', args=[course.pk]), key)
    return enrollment, True


@transaction.atomic
def refund_enrollment(enrollment_id):
    course_id = Enrollment.objects.values_list('course_id', flat=True).get(pk=enrollment_id)
    Course.objects.select_for_update().get(pk=course_id)
    enrollment = Enrollment.objects.select_for_update().select_related('learner').get(pk=enrollment_id)
    if enrollment.status != 'active':
        raise ValueError('این ثبت‌نام قبلاً بازپرداخت شده است.')
    if enrollment.paid_rial:
        wallet, _ = Wallet.objects.get_or_create(user=enrollment.learner)
        wallet.add_balance(enrollment.paid_rial, f'بازپرداخت آموزش: {enrollment.course_title}', f'refund-education-{enrollment.pk}-{enrollment.purchased_at.isoformat()}', tx_type='refund')
    enrollment.status = 'refunded'
    enrollment.refunded_at = timezone.now()
    enrollment.save(update_fields=['status', 'refunded_at'])
    notify(enrollment.learner, 'payment', 'بازپرداخت ثبت‌نام آموزش', f'ثبت‌نام «{enrollment.course_title}» لغو شد و مبلغ پرداختی به کیف پول بازگشت.', reverse('education:my_learning'), f'education-refund:{enrollment.pk}:{enrollment.refunded_at.isoformat()}')
    return enrollment
