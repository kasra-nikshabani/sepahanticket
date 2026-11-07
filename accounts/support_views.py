"""Private support conversations, separated from admission tickets."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest, Http404
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET
from .models import SupportTicket, SupportMessage, EventSubmission
from .support_forms import SupportCreateForm, SupportReplyForm
from .management_views import managed, show, audit


def list_context(request, rows, staff=False):
    counts = dict(rows.values('category').annotate(total=Count('pk')).values_list('category', 'total'))
    category = request.GET.get('category', '')
    status = request.GET.get('status', '')
    query = request.GET.get('q', '').strip()[:160]
    if category in SupportTicket.Category.values:
        rows = rows.filter(category=category)
    else:
        category = ''
    if status in SupportTicket.Status.values:
        rows = rows.filter(status=status)
    else:
        status = ''
    if query:
        search = Q(subject__icontains=query) | Q(event__title__icontains=query) | Q(submission__title__icontains=query) | Q(course__title__icontains=query) | Q(studio__title__icontains=query)
        if staff:
            search |= Q(requester__first_name__icontains=query) | Q(requester__last_name__icontains=query) | Q(requester__phone_number__icontains=query)
        rows = rows.filter(search)
    params = request.GET.copy()
    params.pop('page', None)
    return {'page_obj': Paginator(rows.select_related('event', 'submission__published_event', 'course', 'studio', 'requester'), 20).get_page(request.GET.get('page')),
        'category': category, 'status': status, 'query': query, 'statuses': SupportTicket.Status.choices,
        'program_count': counts.get('program', 0), 'general_count': counts.get('general', 0),
        'filter_query': params.urlencode(), 'staff_support': staff}


@login_required
@never_cache
@require_GET
def support_list(request):
    return render(request, 'accounts/support_list.html', list_context(request, SupportTicket.objects.filter(requester=request.user)))


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def support_create(request):
    initial = {'category': 'program' if request.GET.get('category') == 'program' else 'general'}
    if initial['category'] == 'program':
        initial['event'] = request.GET.get('event')
    change_program = None
    education_course = None
    studio = None
    if request.GET.get('studio'):
        from studios.models import Studio
        if request.GET.get('education') or request.GET.get('change') == '1': raise Http404
        try:
            studio = get_object_or_404(Studio.objects.filter(Q(owner=request.user) | Q(bookings__renter=request.user)).distinct(), pk=request.GET['studio'])
        except (ValueError, ValidationError): raise Http404
        initial.update(category='program', event=None, subject=f'درخواست دربارهٔ پلاتو: {studio.title}'[:160])
    if request.GET.get('education'):
        from education.models import Course
        try:
            education_course = get_object_or_404(Course.objects.filter(
                Q(owner=request.user) | Q(enrollments__learner=request.user, enrollments__status='active')).distinct(),
                pk=request.GET['education'])
        except (ValueError, ValidationError):
            raise Http404
        initial.update(category='program', event=None, subject=f'درخواست دربارهٔ آموزش: {education_course.title}'[:160])
        if request.GET.get('change') == '1':
            raise Http404
    if request.GET.get('change') == '1':
        try:
            event_id = int(request.GET.get('event', ''))
        except (ValueError, TypeError):
            raise Http404
        change_program = get_object_or_404(EventSubmission.objects.select_related('published_event'),
            owner=request.user, published_event_id=event_id)
        initial.update(category='program', event=event_id,
            subject=f'درخواست تغییر برنامه: {change_program.published_event.title}'[:160])
    form = SupportCreateForm(request.POST if request.method == 'POST' else None,
        user=request.user, initial=initial, change_program=change_program, education_course=education_course, studio=studio)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            ticket = form.save(commit=False)
            ticket.requester = request.user
            if change_program:
                ticket.submission = change_program
            if education_course:
                ticket.course = education_course
            if studio:
                ticket.studio = studio
            ticket.save()
            SupportMessage.objects.create(ticket=ticket, author=request.user, body=form.cleaned_data['body'])
        messages.success(request, 'تیکت شما ثبت شد. پاسخ پشتیبانی را در همین گفتگو خواهید دید.')
        return redirect('accounts:support_detail', ticket_id=ticket.pk)
    return render(request, 'accounts/support_create.html', {'form': form, 'change_program': change_program, 'education_course': education_course, 'studio': studio})


def conversation(request, ticket_id, staff=False):
    scoped = SupportTicket.objects.all() if staff else SupportTicket.objects.filter(requester=request.user)
    ticket = get_object_or_404(scoped.select_related('requester', 'event', 'submission__published_event', 'course', 'studio'), pk=ticket_id)
    form = SupportReplyForm()
    detail_name = 'management:support_detail' if staff else 'accounts:support_detail'
    if request.method == 'POST':
        action = request.POST.get('action', 'reply')
        if action not in ['reply', 'close', 'reopen']:
            return HttpResponseBadRequest('عملیات نامعتبر است.')
        form = SupportReplyForm(request.POST) if action == 'reply' else SupportReplyForm()
        valid_reply = action != 'reply' or form.is_valid()
        if valid_reply:
            with transaction.atomic():
                ticket = get_object_or_404(scoped.select_for_update(), pk=ticket_id)
                if action == 'reply' and ticket.status == 'closed':
                    form.add_error(None, 'برای ارسال پیام، ابتدا تیکت را دوباره باز کنید.')
                else:
                    if action == 'reply':
                        message = SupportMessage.objects.create(ticket=ticket, author=request.user,
                            is_staff_reply=staff, body=form.cleaned_data['body'])
                        if staff:
                            from .notifications import notify
                            notify(ticket.requester, 'support', 'پشتیبانی به تیکت شما پاسخ داد',
                                f'تیکت «{ticket.subject}»: {message.body}',
                                reverse('accounts:support_detail', args=[ticket.pk]), f'support-message:{message.pk}')
                        ticket.status = 'answered' if staff else 'waiting'
                        notice = 'پاسخ شما در گفتگو ثبت شد.'
                    else:
                        ticket.status = 'closed' if action == 'close' else 'waiting'
                        notice = 'تیکت بسته شد.' if action == 'close' else 'تیکت دوباره باز شد و در انتظار پاسخ پشتیبانی است.'
                    ticket.save(update_fields=['status', 'updated_at'])
                    if staff:
                        audit(request, ticket, notice)
                    messages.success(request, notice)
                    return redirect(detail_name, ticket_id=ticket.pk)
    context = {'support_ticket': ticket, 'thread': ticket.messages.select_related('author'),
        'form': form, 'staff_support': staff, 'list_url': reverse('management:support' if staff else 'accounts:support_list')}
    if staff:
        return show(request, 'support_detail', 'support', ticket.subject, **context)
    return render(request, 'accounts/support_detail.html', context)


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def support_detail(request, ticket_id):
    return conversation(request, ticket_id)


@managed
def management_list(request):
    if request.method != 'GET':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET'])
    return show(request, 'support_list', 'support', 'تیکت‌های پشتیبانی',
        **list_context(request, SupportTicket.objects.all(), staff=True))


@managed
def management_detail(request, ticket_id):
    return conversation(request, ticket_id, staff=True)
