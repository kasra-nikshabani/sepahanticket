import uuid
from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from matches.event_search import clean_query, search_expression, normalized
from wallet.models import Wallet, is_wallet_enabled, is_wallet_charge_enabled
from .forms import CourseForm, EnrollmentForm, LessonForm
from .models import Course, Enrollment, Lesson, LessonProgress
from .services import enroll, publication_errors, public_courses, registration_issue


def accessible_course(request, course_id):
    course = get_object_or_404(Course.objects.select_related('owner'), pk=course_id)
    privileged = request.user.is_authenticated and (request.user.is_staff or request.user.pk == course.owner_id)
    purchased = request.user.is_authenticated and Enrollment.objects.filter(course=course, learner=request.user, status='active').exists()
    if not privileged and not purchased and not public_courses().filter(pk=course.pk).exists():
        raise Http404
    return course


def editable_course(request, course_id, lock=False):
    rows = Course.objects.select_for_update() if lock else Course.objects.all()
    if not request.user.is_staff:
        rows = rows.filter(owner=request.user)
    course = get_object_or_404(rows, pk=course_id)
    if not request.user.is_staff and (course.published_at or course.status == 'paused'):
        raise Http404
    return course


@require_GET
def catalogue(request):
    rows = public_courses().annotate(lesson_count=Count('lessons', filter=Q(lessons__is_active=True), distinct=True)).order_by('-created_at', '-pk')
    query = clean_query(request.GET.get('q', ''))
    kind, subject = request.GET.get('kind', ''), request.GET.get('subject', '')
    city = clean_query(request.GET.get('city', ''))[:80]
    if query:
        rows = rows.alias(_search=search_expression('title', 'teacher_name', 'academy', 'city'))
        for term in query.split(maxsplit=5):
            if normalized(term):
                rows = rows.filter(_search__contains=normalized(term))
    if kind in Course.Kind.values:
        rows = rows.filter(kind=kind)
    else:
        kind = ''
    if subject in dict(Course.SUBJECTS):
        rows = rows.filter(subject=subject)
    else:
        subject = ''
    if city:
        rows = rows.alias(_city=search_expression('city')).filter(_city=normalized(city))
    params = request.GET.copy(); params.pop('page', None)
    return render(request, 'education/catalogue.html', {
        'page_obj': Paginator(rows, 12).get_page(request.GET.get('page')), 'query': query,
        'kind': kind, 'subject': subject, 'city': city, 'kinds': Course.Kind.choices, 'subjects': Course.SUBJECTS,
        'cities': public_courses().filter(kind='class').exclude(city='').order_by('city').values_list('city', flat=True).distinct(),
        'filter_query': params.urlencode(),
    })


@never_cache
@require_GET
def detail(request, course_id):
    course = accessible_course(request, course_id)
    lessons = list(course.lessons.filter(is_active=True)) if course.kind == 'recorded' else []
    chapters = OrderedDict()
    for lesson in lessons:
        chapters.setdefault(lesson.chapter or 'درس‌های دوره', []).append(lesson)
    enrollment = Enrollment.objects.filter(course=course, learner=request.user, status='active').first() if request.user.is_authenticated else None
    privileged = request.user.is_authenticated and (request.user.is_staff or course.owner_id == request.user.pk)
    enrolled_count = course.enrollments.filter(status='active').count()
    return render(request, 'education/detail.html', {
        'course': course, 'chapters': list(chapters.items()), 'lesson_count': len(lessons),
        'total_minutes': sum(lesson.duration_minutes for lesson in lessons), 'enrollment': enrollment,
        'privileged': privileged, 'registration_issue': registration_issue(course),
        'remaining': max(0, (course.capacity or 0)-enrolled_count),
        'first_lesson': next((lesson for lesson in lessons if lesson.stream_revision), None),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def checkout(request, course_id):
    course = accessible_course(request, course_id)
    if Enrollment.objects.filter(course=course, learner=request.user, status='active').exists():
        return redirect('education:my_learning')
    form = EnrollmentForm(request.POST or None, initial={'learner_name': request.user.get_full_name(), 'price': str(course.price_toman)})
    issue = registration_issue(course)
    if course.owner_id == request.user.pk:
        issue = 'از پنل تدریس به آموزش خودتان دسترسی دارید.'
    if request.method == 'POST' and form.is_valid():
        try:
            enroll(request.user, course.pk, form.cleaned_data['price'], form.cleaned_data['learner_name'])
        except ValueError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, 'ثبت‌نام شما انجام شد؛ به مسیر یادگیری خوش آمدید.')
            return redirect('education:my_learning')
    wallet = Wallet.objects.filter(user=request.user).first()
    balance = wallet.balance if wallet else 0
    return render(request, 'education/checkout.html', {
        'course': course, 'form': form, 'issue': issue, 'balance': balance,
        'shortfall': max(0, course.price_toman*10-balance),
        'wallet_enabled': is_wallet_enabled(), 'charge_enabled': is_wallet_charge_enabled(),
    })


@login_required
@never_cache
@require_GET
def my_learning(request):
    page = Paginator(Enrollment.objects.filter(learner=request.user).select_related('course'), 12).get_page(request.GET.get('page'))
    for enrollment in page:
        lessons = enrollment.course.lessons.filter(is_active=True, stream_revision__isnull=False)
        enrollment.lesson_count = lessons.count()
        enrollment.completed_count = enrollment.progress.filter(completed=True, lesson__in=lessons).count()
        enrollment.percent = round(enrollment.completed_count*100/enrollment.lesson_count) if enrollment.lesson_count else 0
        recent = enrollment.progress.filter(lesson__in=lessons, completed=False).select_related('lesson').order_by('-updated_at').first()
        enrollment.first_lesson = recent.lesson if recent else lessons.exclude(progress__enrollment=enrollment, progress__completed=True).first() or lessons.first()
    return render(request, 'education/my_learning.html', {'page_obj': page})


@login_required
@never_cache
@require_GET
def my_teaching(request):
    courses = Course.objects.filter(owner=request.user).annotate(
        student_count=Count('enrollments', filter=Q(enrollments__status='active')),
        revenue=Sum('enrollments__paid_rial', filter=Q(enrollments__status='active'))).order_by('-created_at', '-pk')
    return render(request, 'education/my_teaching.html', {'page_obj': Paginator(courses, 12).get_page(request.GET.get('page'))})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def course_edit(request, course_id=None):
    with transaction.atomic():
        course = editable_course(request, course_id, lock=request.method == 'POST') if course_id else Course(owner=request.user, kind='recorded')
        form = CourseForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=course)
        if request.method == 'POST' and form.is_valid():
            action = request.POST.get('action', 'save')
            if action not in ('save', 'submit'):
                return HttpResponseBadRequest('عملیات نامعتبر است.')
            if not course._state.adding and form.cleaned_data['version'] != course.updated_at.isoformat():
                form.add_error(None, 'اطلاعات در صفحهٔ دیگری تغییر کرده است؛ صفحه را تازه‌سازی کنید.')
            else:
                obj = form.save(commit=False)
                errors = publication_errors(obj) if action == 'submit' else []
                for error in errors:
                    form.add_error(None, error)
                if not errors:
                    if not obj.published_at:
                        obj.status = 'pending' if action == 'submit' else 'draft'
                        obj.review_note = ''
                        if action == 'submit': obj.submitted_at = timezone.now()
                    obj.save()
                    if request.user.is_staff and obj.owner_id != request.user.pk:
                        from accounts.management_views import audit
                        audit(request, obj, 'ویرایش اطلاعات آموزش توسط مدیریت')
                    messages.success(request, 'آموزش برای بررسی مدیریت ارسال شد.' if action == 'submit' else 'اطلاعات آموزش ذخیره شد.')
                    return redirect('education:manage', obj.pk)
    return render(request, 'education/edit.html', {'form': form, 'course': course})


@login_required
@never_cache
@require_GET
def manage(request, course_id):
    rows = Course.objects.all() if request.user.is_staff else Course.objects.filter(owner=request.user)
    course = get_object_or_404(rows, pk=course_id)
    enrollments = course.enrollments.all()
    active = enrollments.filter(status='active')
    return render(request, 'education/manage.html', {
        'course': course, 'lessons': course.lessons.all(), 'page_obj': Paginator(enrollments, 30).get_page(request.GET.get('page')),
        'student_count': active.count(), 'revenue': active.aggregate(value=Sum('paid_rial'))['value'] or 0,
        'refund_total': enrollments.filter(status='refunded').aggregate(value=Sum('paid_rial'))['value'] or 0,
        'can_edit': request.user.is_staff or (not course.published_at and course.status != 'paused'),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def lesson_edit(request, course_id, lesson_id=None):
    with transaction.atomic():
        course = editable_course(request, course_id, lock=request.method == 'POST')
        if course.kind != 'recorded': raise Http404
        lesson = get_object_or_404(Lesson, pk=lesson_id, course=course) if lesson_id else Lesson(course=course, order=course.lessons.count()+1)
        form = LessonForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=lesson)
        if request.method == 'POST' and form.is_valid():
            obj = form.save(commit=False)
            if request.FILES.get('source'):
                obj.revision = uuid.uuid4(); obj.state = 'queued'; obj.processing_error = ''
            fields = ['chapter', 'title', 'description', 'order', 'is_preview', 'is_active', 'updated_at']
            if request.FILES.get('source'):
                fields += ['source', 'revision', 'state', 'processing_error']
            obj.save(update_fields=fields if not obj._state.adding else None)
            if not course.published_at:
                course.status = 'draft'; course.review_note = ''
            course.save(update_fields=['status', 'review_note', 'updated_at'])
            if request.user.is_staff:
                from accounts.management_views import audit
                audit(request, course, f'ویرایش درس: {lesson.title}')
            messages.success(request, 'درس ذخیره شد؛ ویدئوی تازه پس از آماده‌سازی قابل پخش می‌شود.')
            return redirect('education:manage', course.pk)
    return render(request, 'education/lesson_edit.html', {'course': course, 'lesson': lesson, 'form': form})


@login_required
@require_POST
def retry_video(request, lesson_id):
    with transaction.atomic():
        lesson = get_object_or_404(Lesson, pk=lesson_id)
        course = editable_course(request, lesson.course_id, lock=True)
        if lesson.state != 'failed': return HttpResponseBadRequest('ویدئو نیاز به آماده‌سازی دوباره ندارد.')
        lesson.state = 'queued'; lesson.revision = uuid.uuid4(); lesson.processing_error = ''
        lesson.save(update_fields=['state', 'revision', 'processing_error', 'updated_at'])
        course.save(update_fields=['updated_at'])
    messages.success(request, 'ویدئو دوباره در صف آماده‌سازی قرار گرفت.')
    return redirect('education:manage', course.pk)


@login_required
@never_cache
@require_GET
def watch(request, lesson_id):
    from .playback import playable_lesson
    lesson, enrollment = playable_lesson(request, lesson_id)
    lessons = list(lesson.course.lessons.filter(is_active=True))
    progress = LessonProgress.objects.filter(enrollment=enrollment, lesson=lesson).first() if enrollment else None
    completed = set(enrollment.progress.filter(completed=True).values_list('lesson_id', flat=True)) if enrollment else set()
    current_index = next((i for i, item in enumerate(lessons) if item.pk == lesson.pk), -1)
    return render(request, 'education/watch.html', {
        'lesson': lesson, 'course': lesson.course, 'enrollment': enrollment, 'lessons': lessons,
        'progress': progress, 'completed_ids': completed,
        'next_lesson': lessons[current_index+1] if 0 <= current_index < len(lessons)-1 else None,
        'watermark': (enrollment.learner_name + ' · ' + str(enrollment.pk)[:8]) if enrollment else 'پیش‌نمایش دیدآور',
    })


@login_required
@never_cache
@require_POST
def progress(request, lesson_id):
    from .playback import playable_lesson
    lesson, enrollment = playable_lesson(request, lesson_id)
    if not enrollment: raise Http404
    action = request.POST.get('action', 'position')
    if action not in ('position', 'complete', 'incomplete'):
        return HttpResponseBadRequest('عملیات نامعتبر است.')
    try:
        position = max(0, min(int(request.POST.get('position', '0')), lesson.duration_seconds))
    except (ValueError, TypeError):
        return HttpResponseBadRequest('زمان نامعتبر است.')
    with transaction.atomic():
        row, _ = LessonProgress.objects.select_for_update().get_or_create(enrollment=enrollment, lesson=lesson)
        if action == 'position': row.position_seconds = position
        else: row.completed = action == 'complete'
        row.save()
    if action == 'position': return JsonResponse({'saved': True})
    return redirect('education:watch', lesson.pk)
