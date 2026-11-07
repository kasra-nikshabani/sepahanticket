from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .models import (ArtistProfile, CreativeRole, CollaborationOpportunity as Opportunity,
    CollaborationApplication as Application, CollaborationMessage, CollaborationStatusChange as StatusChange,
    CollaborationReport)
from .collaboration_forms import OpportunityForm, ApplicationForm, CollaborationMessageForm, ReportForm
from .collaboration_services import public_opportunities, change_application_status, notify_application


def pagination(request, rows, size=12):
    params = request.GET.copy()
    params.pop('page', None)
    return {'page_obj': Paginator(rows, size).get_page(request.GET.get('page')), 'filter_query': params.urlencode()}


@never_cache
@require_GET
def opportunity_list(request):
    rows = public_opportunities().select_related('owner').annotate(
        reserved_positions=Count('applications', filter=Q(applications__status__in=['selected', 'accepted']))
    ).filter(reserved_positions__lt=F('positions')).order_by('-created_at', '-pk')
    query = request.GET.get('q', '').strip()[:100]
    city = request.GET.get('city', '').strip()[:80]
    role = request.GET.get('role', '')
    pay = request.GET.get('pay', '')
    if query:
        rows = rows.filter(Q(title__icontains=query) | Q(project_name__icontains=query) | Q(requirements__icontains=query))
    if city:
        rows = rows.filter(city__icontains=city)
    if role in CreativeRole.values:
        rows = rows.filter(role=role)
    else:
        role = ''
    if pay in Opportunity.Pay.values:
        rows = rows.filter(pay_type=pay)
    else:
        pay = ''
    artist = ArtistProfile.objects.filter(owner=request.user, status='approved', is_visible=True).first() if request.user.is_authenticated else None
    recommended = []
    if artist and artist.looking_for_work and (artist.city or artist.preferred_role):
        match = Q(pk__in=[])
        if artist.city:
            match |= Q(city__iexact=artist.city.strip())
        if artist.preferred_role:
            match |= Q(role=artist.preferred_role)
        recommended = public_opportunities().exclude(owner=request.user).filter(match).annotate(
            reserved_positions=Count('applications', filter=Q(applications__status__in=['selected', 'accepted'])),
            match_score=Case(When(role=artist.preferred_role, then=Value(3)), default=Value(0), output_field=IntegerField())
                + Case(When(city__iexact=artist.city.strip(), then=Value(2)), default=Value(0), output_field=IntegerField())
        ).filter(reserved_positions__lt=F('positions')).order_by('-match_score', '-created_at', '-pk')[:3]
    return render(request, 'collaboration/list.html', {**pagination(request, rows),
        'query': query, 'city': city, 'role': role, 'pay': pay, 'roles': CreativeRole.choices,
        'pay_types': Opportunity.Pay.choices, 'recommended': recommended, 'artist': artist})


def accessible_opportunity(request, opportunity_id):
    rows = Opportunity.objects.select_related('owner', 'event')
    if not request.user.is_authenticated or not request.user.is_staff:
        allowed = Q(status__in=['published', 'closed'], owner__is_active=True)
        if request.user.is_authenticated:
            allowed |= Q(owner=request.user)
        rows = rows.filter(allowed)
    return get_object_or_404(rows, pk=opportunity_id)


@never_cache
@require_GET
def opportunity_detail(request, opportunity_id):
    opportunity = accessible_opportunity(request, opportunity_id)
    application = opportunity.applications.filter(applicant=request.user).first() if request.user.is_authenticated else None
    occupied = opportunity.applications.filter(status__in=['selected', 'accepted']).count()
    can_apply = opportunity.is_open and occupied < opportunity.positions and (not application or application.status == 'withdrawn')
    return render(request, 'collaboration/detail.html', {'opportunity': opportunity, 'application': application,
        'can_apply': can_apply, 'occupied': occupied, 'report_form': ReportForm(),
        'is_owner': request.user.is_authenticated and opportunity.owner_id == request.user.pk})


@login_required
@never_cache
@require_GET
def my_opportunities(request):
    rows = Opportunity.objects.filter(owner=request.user).annotate(application_count=Count('applications'),
        accepted_count=Count('applications', filter=Q(applications__status='accepted'))).order_by('-created_at', '-pk')
    return render(request, 'collaboration/my_opportunities.html', pagination(request, rows))


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def opportunity_edit(request, opportunity_id=None):
    opportunity = get_object_or_404(Opportunity, pk=opportunity_id, owner=request.user) if opportunity_id else None
    if opportunity and opportunity.status == 'paused':
        return render(request, 'collaboration/blocked.html', {'opportunity': opportunity}, status=403)
    form = OpportunityForm(instance=opportunity, user=request.user,
        initial={'organizer_name': request.user.get_full_name() or request.user.username, 'positions': 1, 'pay_type': 'negotiable'})
    if request.method == 'POST':
        action = request.POST.get('action')
        if action not in ('save', 'submit'):
            return HttpResponseBadRequest('عملیات نامعتبر است.')
        with transaction.atomic():
            if opportunity:
                opportunity = get_object_or_404(Opportunity.objects.select_for_update(), pk=opportunity.pk, owner=request.user)
                if opportunity.status == 'paused':
                    return HttpResponseForbidden('فراخوان توسط مدیریت متوقف شده است.')
                if request.POST.get('version') != opportunity.updated_at.isoformat():
                    messages.error(request, 'فراخوان در صفحهٔ دیگری تغییر کرده است؛ اطلاعات تازه را بررسی کنید.')
                    return redirect('artists:opportunity_edit', opportunity.pk)
            form = OpportunityForm(request.POST, instance=opportunity, user=request.user, partial=action == 'save')
            if form.is_valid():
                item = form.save(commit=False)
                item.owner = request.user
                item.status = 'pending' if action == 'submit' else 'draft'
                item.reviewed_at = None
                item.reviewed_by = None
                item.review_note = ''
                item.save()
                messages.success(request, 'فراخوان برای بررسی مدیریت ارسال شد.' if action == 'submit' else 'پیش‌نویس ذخیره شد؛ برای انتشار، آن را برای بررسی ارسال کنید.')
                return redirect('artists:opportunity_manage', item.pk)
    return render(request, 'collaboration/edit.html', {'form': form, 'opportunity': opportunity})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def opportunity_manage(request, opportunity_id):
    opportunity = get_object_or_404(Opportunity, pk=opportunity_id, owner=request.user)
    if request.method == 'POST':
        if request.POST.get('action') != 'close':
            return HttpResponseBadRequest('عملیات نامعتبر است.')
        with transaction.atomic():
            opportunity = Opportunity.objects.select_for_update().get(pk=opportunity.pk)
            if opportunity.status != 'published':
                return HttpResponseBadRequest('فقط فراخوان منتشرشده قابل پایان‌دادن است.')
            opportunity.status = 'closed'
            opportunity.save(update_fields=['status', 'updated_at'])
        messages.success(request, 'دریافت درخواست تازه بسته شد؛ بررسی درخواست‌های قبلی ادامه دارد.')
        return redirect('artists:opportunity_manage', opportunity.pk)
    rows = opportunity.applications.select_related('artist', 'applicant').order_by('-created_at', '-pk')
    state = request.GET.get('state', '')
    if state in Application.Status.values:
        rows = rows.filter(status=state)
    return render(request, 'collaboration/manage.html', {**pagination(request, rows), 'opportunity': opportunity,
        'state': state, 'states': Application.Status.choices, 'total': opportunity.applications.count(),
        'accepted_count': opportunity.applications.filter(status='accepted').count()})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def opportunity_apply(request, opportunity_id):
    opportunity = get_object_or_404(public_opportunities().exclude(owner=request.user), pk=opportunity_id)
    artist = ArtistProfile.objects.filter(owner=request.user, status='approved', is_visible=True).first()
    if not artist:
        messages.info(request, 'برای ارسال درخواست، ابتدا صفحهٔ هنری خود را تکمیل کنید و تأیید مدیریت بگیرید.')
        return redirect('artists:edit')
    existing = opportunity.applications.filter(applicant=request.user).first()
    if existing and existing.status != 'withdrawn':
        return redirect(existing)
    form = ApplicationForm(request.POST if request.method == 'POST' else None,
        initial={'portfolio_url': artist.portfolio_url})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            opportunity = Opportunity.objects.select_for_update().select_related('owner').get(pk=opportunity.pk)
            artist = ArtistProfile.objects.select_for_update().filter(owner=request.user, status='approved', is_visible=True).first()
            if not artist or not opportunity.is_open:
                return HttpResponseBadRequest('وضعیت پروفایل یا فراخوان تغییر کرده است؛ صفحه را تازه کنید.')
            existing = opportunity.applications.select_for_update().filter(applicant=request.user).first()
            if existing and existing.status != 'withdrawn':
                return redirect(existing)
            if opportunity.applications.filter(status__in=['selected', 'accepted']).count() >= opportunity.positions:
                form.add_error(None, 'ظرفیت فراخوان در مرحلهٔ انتخاب تکمیل شده است.')
            else:
                application = existing or Application(opportunity=opportunity, applicant=request.user, artist=artist)
                for field in ('introduction', 'availability', 'portfolio_url'):
                    setattr(application, field, form.cleaned_data[field])
                application.profile_snapshot = {'name': artist.display_name, 'city': artist.city,
                    'specialty': artist.specialty, 'biography': artist.biography, 'skills': artist.skills,
                    'experience': artist.experience, 'portfolio_url': artist.portfolio_url}
                application.status = 'submitted'
                application.save()
                change = StatusChange.objects.create(application=application, actor=request.user, status='submitted')
                notify_application(application, opportunity.owner, 'درخواست همکاری تازه دارید',
                    f'برای «{opportunity.title}» یک درخواست همکاری دریافت شد.', f'collaboration-apply:{change.pk}')
                messages.success(request, 'درخواست شما ارسال شد؛ نتیجه و گفت‌وگو را از همین صفحه پیگیری کنید.')
                return redirect(application)
    return render(request, 'collaboration/apply.html', {'form': form, 'opportunity': opportunity, 'artist': artist})


@login_required
@never_cache
@require_GET
def my_applications(request):
    rows = Application.objects.filter(applicant=request.user).select_related('opportunity')
    return render(request, 'collaboration/my_applications.html', pagination(request, rows))


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def application_detail(request, application_id):
    rows = Application.objects.select_related('opportunity__owner', 'applicant', 'artist__owner')
    if not request.user.is_staff:
        rows = rows.filter(Q(applicant=request.user) | Q(opportunity__owner=request.user))
    application = get_object_or_404(rows, pk=application_id)
    participant = request.user.pk in (application.applicant_id, application.opportunity.owner_id)
    message_form = CollaborationMessageForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if not participant:
            return HttpResponseForbidden('مدیریت فقط دسترسی بررسی دارد.')
        if message_form.is_valid():
            with transaction.atomic():
                # Keep the same lock order used by status changes and moderation.
                opportunity = Opportunity.objects.select_for_update().select_related('owner').get(pk=application.opportunity_id)
                application = Application.objects.select_for_update().select_related('applicant').get(pk=application.pk)
                if opportunity.status == 'paused' or not opportunity.owner.is_active or not application.applicant.is_active or application.status in ('withdrawn', 'declined'):
                    message_form.add_error(None, 'گفت‌وگو در وضعیت فعلی بسته است.')
                else:
                    message = message_form.save(commit=False)
                    message.application = application
                    message.sender = request.user
                    message.save()
                    recipient = application.applicant if request.user.pk == opportunity.owner_id else opportunity.owner
                    notify_application(application, recipient, 'پیام تازه دربارهٔ همکاری',
                        f'در گفت‌وگوی «{opportunity.title}» پیام تازه‌ای دارید.', f'collaboration-message:{message.pk}')
                    return redirect(application)
    owner_actions = {
        'submitted': [('reviewing', 'شروع بررسی'), ('invited', 'دعوت به گفت‌وگو'), ('selected', 'انتخاب برای همکاری'), ('declined', 'نپذیرفتن درخواست')],
        'reviewing': [('invited', 'دعوت به گفت‌وگو'), ('selected', 'انتخاب برای همکاری'), ('declined', 'نپذیرفتن درخواست')],
        'invited': [('selected', 'انتخاب برای همکاری'), ('declined', 'نپذیرفتن درخواست')],
        'selected': [('declined', 'لغو پیشنهاد همکاری')],
    }
    return render(request, 'collaboration/application.html', {'application': application,
        'opportunity': application.opportunity, 'message_form': message_form,
        **pagination(request, application.messages.select_related('sender').order_by('-created_at', '-pk'), 30),
        'history': application.status_changes.all(), 'participant': participant,
        'is_owner': request.user.pk == application.opportunity.owner_id,
        'owner_actions': owner_actions.get(application.status, []) if application.opportunity.status in ('published', 'closed') else [],
        'can_withdraw': application.status not in ('accepted', 'declined', 'withdrawn') and application.opportunity.status != 'paused',
        'can_accept': application.status == 'selected' and application.opportunity.status in ('published', 'closed'),
        'can_message': participant and application.status not in ('withdrawn', 'declined') and application.opportunity.status != 'paused'})


@login_required
@require_POST
def application_status(request, application_id):
    application = get_object_or_404(Application.objects.filter(
        Q(applicant=request.user) | Q(opportunity__owner=request.user)), pk=application_id)
    try:
        change_application_status(application.pk, request.user, request.POST.get('action'))
        messages.success(request, 'وضعیت درخواست همکاری ثبت شد.')
    except ValueError as error:
        messages.error(request, str(error))
    return redirect(application)


@login_required
@never_cache
@require_POST
def opportunity_report(request, opportunity_id):
    opportunity = accessible_opportunity(request, opportunity_id)
    form = ReportForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            Opportunity.objects.select_for_update().get(pk=opportunity.pk)
            report, created = CollaborationReport.objects.get_or_create(opportunity=opportunity,
                reporter=request.user, resolved_at=None, defaults={'reason': form.cleaned_data['reason']})
        messages.success(request, 'گزارش برای بررسی مدیریت ثبت شد.' if created else 'گزارش قبلی شما هنوز در حال بررسی است.')
        return redirect(opportunity)
    return render(request, 'collaboration/report.html', {'opportunity': opportunity, 'form': form}, status=400)
