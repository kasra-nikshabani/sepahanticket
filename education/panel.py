from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.core.exceptions import ValidationError
from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from accounts.management_views import audit, managed, show
from accounts.notifications import notify
from .forms import ReviewForm
from .models import Course, Enrollment
from .services import publication_errors, refund_enrollment


@managed
def courses(request):
    rows = Course.objects.select_related('owner').annotate(student_count=Count('enrollments', filter=Q(enrollments__status='active'))).order_by('-created_at', '-pk')
    state = request.GET.get('state', '')
    query = request.GET.get('q', '').strip()[:120]
    if state in Course.Status.values: rows = rows.filter(status=state)
    if query: rows = rows.filter(Q(title__icontains=query) | Q(teacher_name__icontains=query) | Q(academy__icontains=query))
    return show(request, 'education_courses', 'education', 'مدیریت آموزش‌ها',
        page_obj=Paginator(rows, 20).get_page(request.GET.get('page')), states=Course.Status.choices, state=state, query=query,
        education_revenue=Enrollment.objects.filter(status='active').aggregate(value=Sum('paid_rial'))['value'] or 0,
        education_students=Enrollment.objects.filter(status='active').count())


@managed
def course_review(request, course_id):
    with transaction.atomic():
        rows = Course.objects.select_related('owner')
        if request.method == 'POST': rows = rows.select_for_update()
        course = get_object_or_404(rows, pk=course_id)
        form = ReviewForm(request.POST if request.method == 'POST' else None, initial={'version': course.updated_at.isoformat()})
        if request.method == 'POST' and form.is_valid():
            action = request.POST.get('action', '')
            if not action and request.GET.get('action') == 'refund':
                action = 'refund'
            note = form.cleaned_data['note'].strip()
            if form.cleaned_data['version'] != course.updated_at.isoformat():
                form.add_error(None, 'اطلاعات آموزش تغییر کرده است؛ صفحه را تازه‌سازی کنید و دوباره بررسی کنید.')
            elif action != 'approve' and not note:
                form.add_error('note', 'علت تصمیم را برای مدرس یا هنرجو بنویسید.')
            elif action == 'approve' and (course.status != 'pending' or not course.owner.is_active):
                form.add_error(None, 'فقط آموزش در انتظار بررسیِ حساب فعال قابل تأیید است.')
            elif action == 'approve' and publication_errors(course):
                form.add_error(None, ' '.join(publication_errors(course)))
            elif action == 'revision' and course.status != 'pending':
                form.add_error(None, 'فقط آموزش در انتظار بررسی قابل بازگشت برای اصلاح است.')
            elif action == 'reopen' and course.status != 'paused':
                form.add_error(None, 'این آموزش متوقف نشده است.')
            elif action in ('close_sales', 'open_sales') and course.status != 'published':
                form.add_error(None, 'ابتدا آموزش را بررسی و منتشر کنید.')
            elif action not in ('approve', 'revision', 'pause', 'reopen', 'close_sales', 'open_sales', 'suspend_access', 'restore_access', 'refund'):
                form.add_error(None, 'عملیات نامعتبر است.')
            else:
                if action == 'refund':
                    try:
                        enrollment = get_object_or_404(Enrollment, course=course, pk=request.POST.get('enrollment_id'))
                    except (ValidationError, ValueError):
                        raise Http404
                    try:
                        refunded = refund_enrollment(enrollment.pk)
                    except ValueError as error:
                        form.add_error(None, str(error))
                    else:
                        audit(request, course, f'بازپرداخت ثبت‌نام {refunded.pk}: {note}')
                        notify(refunded.learner, 'payment', 'پیام مدیریت دربارهٔ بازپرداخت', note,
                               reverse('education:my_learning'), f'education-refund-note:{refunded.pk}:{refunded.refunded_at.isoformat()}')
                        messages.success(request, 'ثبت‌نام لغو و مبلغ پرداختی به کیف پول هنرجو برگشت.')
                        return redirect('management:education_detail', course.pk)
                else:
                    if action in ('approve', 'revision', 'pause', 'reopen'):
                        course.status = {'approve': 'published', 'revision': 'revision', 'pause': 'paused', 'reopen': 'pending'}[action]
                    if action == 'approve' and not course.published_at: course.published_at = timezone.now()
                    if action in ('close_sales', 'open_sales'): course.enrollment_open = action == 'open_sales'
                    if action in ('suspend_access', 'restore_access'): course.access_suspended = action == 'suspend_access'
                    course.review_note = note; course.reviewed_by = request.user; course.reviewed_at = timezone.now()
                    course.save()
                    audit(request, course, f'مدیریت آموزش: {action}. {note}')
                    notify(course.owner, 'publication' if action == 'approve' else 'review', 'پیام مدیریت دربارهٔ آموزش',
                           f'«{course.title}»؛ {course.get_status_display()}. {note}', reverse('education:manage', args=[course.pk]),
                           f'education-review:{course.pk}:{course.updated_at.isoformat()}')
                    messages.success(request, 'تصمیم مدیریت ثبت شد و پیام برای مدرس ارسال شد.')
                    return redirect('management:education_detail', course.pk)
    return show(request, 'education_detail', 'education', course.title, course=course, form=form,
        lessons=course.lessons.all(), page_obj=Paginator(course.enrollments.all(), 30).get_page(request.GET.get('page')))
