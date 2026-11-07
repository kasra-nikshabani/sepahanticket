"""Staff-only management for Didavar's cultural events."""
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.templatetags.static import static
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET
from matches.forms import EventSceneImageFormSet
from matches.banner_defaults import DEFAULT_BANNERS, install_default_banners
from matches.models import Event, EventSceneImage, HomeBanner, Match, Stadium, Block, Row, Seat, MatchSeat, get_seat_price_map
from tickets.models import Ticket
from .models import User, EventSubmission, SiteSettings, SupportTicket, SupportMessage, ArtCardApplication
from .management_forms import ManagedEventForm, ManagedSessionForm, VenueForm, ManagedUserForm, ManagedSettingsForm, HomeBannerForm
from .program_views import statistics
from .submission_views import _review, _saved_form
from .venue_layout import validate_layout, layout_capacity
from .program_pricing import PricingForm, change_prices
from .publication_schedule import checked_schedule, create_initial_sessions, InitialSalesApprovalForm
from .management_reports import filter_sales, session_map, export_tickets, enabled_inventory

NAV = [('dashboard', 'نمای کلی', 'fa-chart-pie'), ('events', 'برنامه‌ها', 'fa-masks-theater'),
       ('artcards', 'درخواست‌های هنرکارت', 'fa-credit-card'),
       ('education', 'آموزش‌ها', 'fa-graduation-cap'),
       ('studios', 'پلاتوها و رزروها', 'fa-door-open'),
       ('artists', 'هنرمندان', 'fa-user-check'),
       ('opportunities', 'فرصت‌های همکاری', 'fa-briefcase'),
       ('banners', 'بنرهای صفحه اصلی', 'fa-images'),
       ('sessions', 'سانس‌ها', 'fa-calendar-days'), ('requests', 'درخواست‌های انتشار', 'fa-inbox'),
       ('venues', 'سالن‌ها و صندلی‌ها', 'fa-couch'), ('sales', 'فروش و بلیط‌ها', 'fa-ticket'),
       ('users', 'کاربران', 'fa-users'), ('support', 'تیکت‌های پشتیبانی', 'fa-headset'), ('activity', 'تاریخچه مدیریت', 'fa-clock-rotate-left'),
       ('settings', 'تنظیمات', 'fa-sliders')]


def managed(view):
    return staff_member_required(login_url='accounts:login_password')(
        never_cache(require_http_methods(['GET', 'POST'])(view)))


def show(request, template, section, title, **context):
    from artists.models import ArtistProfile, CollaborationOpportunity, CollaborationReport
    from education.models import Course
    from studios.models import Studio
    params = request.GET.copy()
    params.pop('page', None)
    params.pop('map_page', None)
    pending = {
        'pending_education': Course.objects.filter(status='pending').count(),
        'pending_studios': Studio.objects.filter(status='pending').count(),
        'pending_artists': ArtistProfile.objects.filter(status='pending').count(),
        'pending_support': SupportTicket.objects.filter(status='waiting').count(),
        'pending_art_cards': ArtCardApplication.objects.filter(status__in=['requested', 'sent_to_bank']).count(),
        'pending_requests': EventSubmission.objects.filter(status='submitted').count(),
        'pending_opportunities': CollaborationOpportunity.objects.filter(status='pending').count(),
        'pending_collaboration_reports': CollaborationReport.objects.filter(resolved_at__isnull=True).count(),
    }
    return render(request, 'management/' + template + '.html', {
        'panel_nav': NAV, 'panel_section': section, 'panel_title': title,
        **pending, 'pending_total': sum(pending.values()),
        'today': timezone.localtime(), 'filter_query': params.urlencode(), **context})


def audit(request, obj, message, created=False):
    LogEntry.objects.create(user_id=request.user.pk, content_type=ContentType.objects.get_for_model(obj),
        object_id=str(obj.pk), object_repr=str(obj)[:200], action_flag=ADDITION if created else CHANGE,
        change_message=message)


def paginate(request, rows):
    return Paginator(rows, 20).get_page(request.GET.get('page'))


def cultural_tickets():
    return Ticket.objects.filter(match__event__category__in=['theater', 'concert', 'event'])


@managed
def dashboard(request):
    if request.method != 'GET':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET'])
    from .management_overview import overview_context
    tickets = cultural_tickets()
    stats = statistics(tickets)
    days = 30 if request.GET.get('days') == '30' else 7
    context = overview_context(tickets, stats, timezone.now(), days)
    return show(request, 'dashboard', 'dashboard', 'همه‌چیز برای یک دیدار بهتر', stats=stats, **context)


@managed
def art_card_requests(request):
    rows = ArtCardApplication.objects.select_related('user').all()
    if request.method == 'POST':
        application = get_object_or_404(ArtCardApplication.objects.select_related('user'), pk=request.POST.get('application_id'))
        status = request.POST.get('status', '')
        valid_statuses = {key for key, _label in ArtCardApplication.STATUS_CHOICES}
        last_four = request.POST.get('card_last_four', '').strip()
        if status not in valid_statuses:
            messages.error(request, 'وضعیت انتخاب‌شده معتبر نیست.')
        elif last_four and (len(last_four) != 4 or not last_four.isascii() or not last_four.isdigit()):
            messages.error(request, 'برای کارت فقط چهار رقم پایانی را وارد کنید.')
        elif status == 'active' and not last_four:
            messages.error(request, 'برای ثبت کارت فعال، چهار رقم پایانی کارت را وارد کنید.')
        else:
            application.status = status
            application.bank_reference = request.POST.get('bank_reference', '').strip()[:100]
            application.card_last_four = last_four
            application.admin_note = request.POST.get('admin_note', '').strip()[:2000]
            application.save(update_fields=['status', 'bank_reference', 'card_last_four', 'admin_note', 'updated_at'])
            audit(request, application, f'به‌روزرسانی وضعیت هنرکارت: {application.get_status_display()}')
            messages.success(request, f'وضعیت درخواست هنرکارت {application.user.get_full_name() or application.user.username} ذخیره شد.')
        return redirect('management:artcards')
    selected_status = request.GET.get('state', '')
    if selected_status in {key for key, _label in ArtCardApplication.STATUS_CHOICES}:
        rows = rows.filter(status=selected_status)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        rows = rows.filter(Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query)
                           | Q(user__username__icontains=query) | Q(user__phone_number__icontains=query))
    return show(request, 'art_cards', 'artcards', 'درخواست‌های هنرکارت',
        page_obj=paginate(request, rows), states=ArtCardApplication.STATUS_CHOICES,
        selected_state=selected_status, query=query, total_count=ArtCardApplication.objects.count())


@managed
def events(request):
    rows = Event.objects.exclude(category='sport').annotate(session_count=Count('sessions', distinct=True))
    query = request.GET.get('q', '').strip()[:100]
    category = request.GET.get('category', '')
    if query:
        rows = rows.filter(Q(title__icontains=query) | Q(organizer__icontains=query))
    if category in ('theater', 'concert', 'event'):
        rows = rows.filter(category=category)
    state = request.GET.get('state', '')
    if state in ('active', 'inactive'):
        rows = rows.filter(is_active=state == 'active')
    elif state == 'unscheduled':
        rows = rows.filter(is_active=True, sessions__isnull=True)
    return show(request, 'list', 'events', 'مدیریت برنامه‌ها', page_obj=paginate(request, rows.order_by('-created_at', '-pk')), query=query, category=category, selected_state=state)


@managed
@require_GET
def event_report(request, event_id):
    event = get_object_or_404(Event.objects.exclude(category='sport'), pk=event_id)
    tickets = cultural_tickets().filter(match__event=event)
    totals = {item['match_id']: item for item in tickets.values('match_id').annotate(
        sold=Count('pk', filter=Q(status='paid')), revenue=Sum('price', filter=Q(status='paid'), default=0),
        used=Count('pk', filter=Q(status__in=['paid', 'admin_assigned', 'vip_issued'], is_used=True)))}
    sessions = event.sessions.select_related('stadium').order_by('date_time', 'pk')
    page = paginate(request, sessions)
    for item in page:
        item.report_sales = totals.get(item.pk, {'sold': 0, 'revenue': 0, 'used': 0})
        item.report_capacity = enabled_inventory(item).count()
        item.report_fill = min(100, round(item.report_sales['sold'] * 100 / item.report_capacity)) if item.report_capacity else 0
    submission = EventSubmission.objects.filter(published_event=event).select_related('owner').order_by('-updated_at').first()
    return show(request, 'event_report', 'events', event.title, event=event, submission=submission,
                stats=statistics(tickets), page_obj=page, session_count=sessions.count())


@managed
def event_edit(request, event_id=None):
    event = get_object_or_404(Event.objects.exclude(category='sport'), pk=event_id) if event_id else None
    form = ManagedEventForm(request.POST or None, request.FILES or None, instance=event)
    if event:
        form.fields['category'].disabled = True
    scene_formset = EventSceneImageFormSet(request.POST or None, request.FILES or None, instance=form.instance, prefix='scenes')
    if request.method == 'POST' and form.is_valid() and scene_formset.is_valid():
        with transaction.atomic():
            obj = form.save()
            scene_formset.save()
            audit(request, obj, 'اطلاعات برنامه در پنل دیدآور ذخیره شد.', created=event is None)
        messages.success(request, 'اطلاعات برنامه ذخیره شد.')
        return redirect('management:events')
    return show(request, 'form', 'events', 'ویرایش برنامه' if event else 'ایجاد برنامه جدید', form=form, scene_formset=scene_formset, event=event)


@managed
def sessions(request):
    rows = Match.objects.exclude(event=None).exclude(event__category='sport').select_related('event', 'stadium')
    query = request.GET.get('q', '').strip()[:100]
    if query:
        rows = rows.filter(Q(event__title__icontains=query) | Q(stadium__name__icontains=query))
    if request.GET.get('event', '').isdigit():
        rows = rows.filter(event_id=request.GET['event'])
    state = request.GET.get('state', '')
    if state == 'upcoming':
        rows = rows.filter(date_time__gt=timezone.now(), is_cancelled=False)
    elif state == 'past':
        rows = rows.filter(date_time__lte=timezone.now(), is_cancelled=False)
    elif state == 'cancelled':
        rows = rows.filter(is_cancelled=True)
    elif state == 'selling':
        rows = rows.filter(date_time__gt=timezone.now(), is_cancelled=False, is_active=True,
                           ticket_sales_enabled=True, event__is_active=True)
    return show(request, 'list', 'sessions', 'مدیریت سانس‌ها', page_obj=paginate(request, rows.order_by('-date_time')), query=query, selected_state=state)


@managed
def session_edit(request, session_id=None):
    session = get_object_or_404(Match.objects.exclude(event=None).exclude(event__category='sport'), pk=session_id) if session_id else None
    form = ManagedSessionForm(request.POST or None, instance=session,
        initial={'event': request.GET.get('event'), 'ticket_sales_enabled': False} if not session else None)
    if session and session.match_seats.exists():
        form.fields['event'].disabled = True
    if request.method == 'POST' and form.is_valid():
        if form.cleaned_data.get('ticket_sales_enabled'):
            venue = form.cleaned_data['stadium']
            available = enabled_inventory(session).exists() if session and session.match_seats.exists() else Seat.objects.filter(
                row__block__stadium=venue, is_available=True, row__is_active=True, row__block__is_active=True).exists()
            if not available:
                form.add_error('ticket_sales_enabled', 'برای فعال‌کردن فروش، ابتدا صندلی‌های سالن را تعریف کن.')
        if not form.errors:
            with transaction.atomic():
                obj = form.save(commit=False)
                if not session:
                    obj.created_by = request.user
                obj.save()
                audit(request, obj, 'سانس در پنل دیدآور ذخیره شد.', created=session is None)
            messages.success(request, 'سانس ذخیره شد؛ فروش هر سانس مستقل است.')
            return redirect('management:session_sales', obj.pk)
    return show(request, 'form', 'sessions', 'ویرایش سانس' if session else 'تعریف سانس جدید', form=form, selected_session=session)


@managed
def session_sales(request, session_id):
    session = get_object_or_404(Match.objects.exclude(event=None).exclude(event__category='sport').select_related('event', 'stadium'), pk=session_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action not in ('open_sales', 'close_sales'):
            raise Http404
        with transaction.atomic():
            session = Match.objects.select_for_update().get(pk=session.pk)
            if action == 'open_sales' and (session.is_cancelled or session.date_time <= timezone.now() or not session.is_active
                or not session.event.is_active or not enabled_inventory(session).exists()):
                messages.error(request, 'این سانس برای شروع فروش آماده نیست؛ تاریخ، انتشار و صندلی‌ها را بررسی کن.')
            else:
                session.ticket_sales_enabled = action == 'open_sales'
                session.save(update_fields=['ticket_sales_enabled'])
                audit(request, session, 'فروش سانس فعال شد.' if session.ticket_sales_enabled else 'فروش سانس متوقف شد.')
                messages.success(request, 'وضعیت فروش سانس ذخیره شد.')
        return redirect('management:session_sales', session.pk)
    rows = cultural_tickets().filter(match=session).select_related('user', 'match__event', 'seat__row__block').order_by('-purchase_date', '-pk')
    form, rows, summary = filter_sales(request, rows, session)
    submission = EventSubmission.objects.filter(published_event=session.event).order_by('-updated_at').first()
    publication = (submission.data.get('publication_snapshot') or submission.data) if submission else {}
    return show(request, 'sales', 'sessions', 'گزارش سانس', selected_session=session, stats=statistics(summary),
        filter_form=form, query=form.data.get('q', ''), selected_status=form.data.get('status', 'all'),
        seat_map=session_map(request, session, publication.get('seat_layout')),
        page_obj=paginate(request, rows), capacity=enabled_inventory(session).count())


@managed
def session_pricing(request, session_id):
    session = get_object_or_404(Match.objects.exclude(event=None).exclude(event__category='sport').select_related('event', 'stadium'), pk=session_id)
    form = PricingForm(request.POST if request.method == 'POST' else None, session=session,
        initial={'scope': 'session', 'target': 'base'})
    if request.method == 'POST' and form.is_valid():
        try:
            count = change_prices(SimpleNamespace(published_event=session.event), session, form.cleaned_data, request.POST.get('action') == 'reset')
        except ValidationError as error:
            form.add_error(None, error)
        else:
            audit(request, session, f'قیمت‌گذاری برای {count} سانس تغییر کرد.')
            messages.success(request, 'قیمت‌ها ذخیره شد؛ مبلغ بلیط‌های فروخته‌شده حفظ می‌شود.')
            return redirect('management:session_pricing', session.pk)
    inventory = list(Seat.objects.filter(match_seats__match=session).select_related('row__block').order_by('row__block__order', 'row__block_id', 'row__number', 'number'))
    prices = get_seat_price_map(session, inventory)
    options, rows = {}, {}
    for seat in inventory:
        options.setdefault(str(seat.row_id), []).append(seat.number)
        row = rows.setdefault(seat.row_id, {'row': seat.row, 'count': 0, 'values': []})
        row['count'] += 1
        row['values'].append(prices[seat.pk])
    for item in rows.values():
        item['minimum'], item['maximum'] = min(item['values']), max(item['values'])
    return show(request, 'pricing', 'sessions', 'قیمت‌گذاری سانس', form=form, selected_session=session, row_options=options, price_rows=list(rows.values()))


@managed
@require_GET
def sales(request):
    rows = cultural_tickets().select_related('user', 'match__event', 'seat__row__block').order_by('-purchase_date', '-pk')
    form, rows, summary = filter_sales(request, rows)
    return show(request, 'sales', 'sales', 'فروش و بلیط‌ها', page_obj=paginate(request, rows), stats=statistics(summary),
        filter_form=form, query=form.data.get('q', ''), selected_status=form.data.get('status', 'paid'))


@managed
@require_GET
def sales_export(request, session_id=None):
    session = get_object_or_404(Match.objects.exclude(event=None).exclude(event__category='sport'), pk=session_id) if session_id else None
    tickets = cultural_tickets().select_related('user', 'match__event', 'match__stadium', 'seat__row__block').order_by('-purchase_date', '-pk')
    if session:
        tickets = tickets.filter(match=session)
    form, tickets, summary = filter_sales(request, tickets, session)
    if not form.is_valid():
        return HttpResponseBadRequest('فیلتر گزارش معتبر نیست؛ تاریخ‌ها و گزینه‌ها را اصلاح کن.')
    return export_tickets(tickets)


@managed
@require_GET
def activity(request):
    rows = LogEntry.objects.select_related('user', 'content_type').filter(
        Q(content_type__app_label='accounts', content_type__model__in=['user', 'sitesettings', 'eventsubmission', 'supportticket']) |
        Q(content_type__app_label='matches', content_type__model__in=['event', 'homebanner', 'match', 'stadium', 'matchrowprice', 'matchseatprice', 'matchblockprice']))
    query = request.GET.get('q', '').strip()[:100]
    if query:
        rows = rows.filter(Q(object_repr__icontains=query) | Q(user__username__icontains=query) | Q(change_message__icontains=query))
    action = request.GET.get('action', '')
    if action in ('1', '2', '3'):
        rows = rows.filter(action_flag=int(action))
    return show(request, 'activity', 'activity', 'تاریخچه فعالیت مدیران',
        page_obj=paginate(request, rows.order_by('-action_time', '-pk')), query=query, selected_action=action)


@managed
def requests_list(request):
    state = request.GET.get('state', 'submitted')
    rows = EventSubmission.objects.select_related('owner', 'published_event')
    if state == 'published':
        rows = rows.filter(published_event__isnull=False).exclude(status='submitted')
    elif state == 'returned':
        rows = rows.filter(status='draft').exclude(data__review_feedback='').filter(data__has_key='review_feedback')
    elif state == 'all':
        rows = rows.filter(Q(status='submitted') | Q(published_event__isnull=False) | Q(data__has_key='review_feedback'))
    else:
        state = 'submitted'
        rows = rows.filter(status='submitted')
    query = request.GET.get('q', '').strip()[:100]
    if query:
        rows = rows.filter(Q(title__icontains=query) | Q(owner__first_name__icontains=query) | Q(owner__last_name__icontains=query))
    return show(request, 'list', 'requests', 'بررسی درخواست‌های انتشار', page_obj=paginate(request, rows.order_by('-updated_at', '-pk')), query=query, selected_state=state)


def build_venue(venue, plan, price):
    venue.seating_layout = validate_layout(plan)
    venue.save(update_fields=['seating_layout'])
    for index, section in enumerate(plan.get('sections', [])):
        block = Block.objects.create(stadium=venue, name=section['name'], order=index, price=price, zone_type='home')
        for row in section['rows']:
            actual = Row.objects.create(block=block, number=row['number'])
            Seat.objects.bulk_create([Seat(row=actual, number=number) for number in row['seats'] if number is not None])


@transaction.atomic
def publish_proposal(request, submission):
    if submission.published_event_id:
        raise ValidationError('این برنامه قبلاً منتشر شده است؛ تغییرات را از تیکت بررسی و در بخش مدیریت برنامه اعمال کن.')
    if not request.user.is_staff or submission.status != 'submitted':
        raise ValidationError('فقط ادمین می‌تواند درخواست ارسال‌شده برای بررسی را منتشر کند.')
    if submission.category in ('theater', 'concert'):
        if not submission.license_image or not submission.license_image.storage.exists(submission.license_image.name):
            raise ValidationError('نمایش و کنسرت بدون تصویر مجوز ارشاد قابل انتشار نیست؛ درخواست را برای تکمیل برگردان.')
        if request.POST.get('license_checked') != 'on':
            raise ValidationError('پیش از انتشار، مجوز ارشاد را مشاهده و بررسی آن را تأیید کن.')
    for step in range(1, 6):
        if not _saved_form(submission, step).is_valid():
            raise ValidationError('اطلاعات درخواست کامل نیست؛ ابتدا برای تکمیل به برگزارکننده برگردان.')
    schedule = checked_schedule(submission, request)
    data = submission.data
    event = submission.published_event or Event(category=submission.category)
    event.title = submission.title
    event.description = data.get('description') or data.get('summary', '')
    event.artists = data.get('credits', '')[:300]
    event.organizer = submission.owner.get_full_name() or submission.owner.username
    event.duration_minutes = data.get('duration', 120)
    event.is_active = True
    for key in ('poster', 'cover', 'teaser'):
        source = getattr(submission, key)
        if source:
            source.open('rb')
            try:
                getattr(event, key).save(Path(source.name).name, File(source), save=False)
            finally:
                source.close()
    event.save()
    copied = set(data.get('published_photo_ids', []))
    for photo in submission.photos.exclude(pk__in=copied):
        photo.image.open('rb')
        try:
            image = EventSceneImage(event=event)
            image.image.save(Path(photo.image.name).name, File(photo.image), save=True)
            copied.add(photo.pk)
        finally:
            photo.image.close()
    if not submission.venue_id and not submission.published_event_id and data.get('venue_mode') == 'custom':
        plan = validate_layout(data.get('seat_layout') or {})
        capacity = layout_capacity(plan) or data.get('ticket_capacity') or 1
        venue = Stadium.objects.create(name=data.get('venue', submission.title)[:100], city=data.get('city', ''), address=data.get('address', ''), capacity=capacity)
        build_venue(venue, plan, 0)
        submission.venue = venue
    submission.published_event = event
    submission.status = 'draft'
    submission.data = {**data, 'published_photo_ids': sorted(copied), 'publication_snapshot': {
        key: data.get(key) for key in ('admission_mode', 'ticket_capacity', 'ticket_price', 'seat_layout')},
        'license_review': {'file': submission.license_image.name, 'reviewed_by': request.user.pk,
                           'reviewed_at': timezone.now().isoformat()} if submission.category in ('theater', 'concert') else None,
        'review_feedback': '', 'reviewed_by': request.user.pk, 'reviewed_at': timezone.now().isoformat()}
    submission.save()
    created_sessions = create_initial_sessions(request, submission, schedule)
    if schedule is not None:
        submission.data = {**submission.data, 'initial_schedule_session_ids': [item.pk for item in created_sessions],
            'initial_sales_approved': schedule['approved'], 'initial_sales_reviewed_by': request.user.pk,
            'initial_base_price': schedule['base_price']}
        submission.save(update_fields=['data', 'updated_at'])
    audit(request, submission, 'درخواست بررسی و برنامه منتشر شد.')
    from .notifications import notify
    notify(submission.owner, 'publication', 'برنامهٔ شما تأیید و منتشر شد',
        f'«{submission.display_title}» پس از بررسی مدیریت منتشر شد. سانس‌ها و گزارش برنامه در برنامه‌های من در دسترس است.',
        reverse('accounts:program_detail', args=[submission.pk]), f'submission:{submission.pk}:published')
    return event


def send_review_message(request, submission, note, needs_changes=False):
    """One private conversation retains all feedback across repeated reviews."""
    ticket = submission.support_tickets.filter(requester=submission.owner, category='program').order_by('pk').first()
    if not ticket:
        ticket = SupportTicket.objects.create(requester=submission.owner, category='program',
            submission=submission, event=submission.published_event, subject=f'بررسی برنامه: {submission.title}'[:160])
    else:
        ticket = SupportTicket.objects.select_for_update().get(pk=ticket.pk)
    message = SupportMessage.objects.create(ticket=ticket, author=request.user, is_staff_reply=True, body=note)
    from .notifications import notify
    notify(submission.owner, 'review' if needs_changes else 'support',
        'اطلاعات برنامه نیاز به اصلاح دارد' if needs_changes else 'پیام مدیریت دربارهٔ برنامهٔ شما',
        f'برنامهٔ «{submission.display_title}»: {note}', reverse('accounts:support_detail', args=[ticket.pk]),
        f'support-message:{message.pk}')
    ticket.status = 'answered'
    ticket.save(update_fields=['status', 'updated_at'])
    submission.data = {**submission.data, 'review_support_ticket': ticket.pk}
    return ticket


@managed
def request_detail(request, submission_id):
    submission = get_object_or_404(EventSubmission.objects.select_related('owner', 'published_event', 'venue'), pk=submission_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        with transaction.atomic():
            submission = EventSubmission.objects.select_for_update().get(pk=submission.pk)
            if action not in ('message', 'return', 'publish'):
                raise Http404
            if action != 'message' and submission.published_event_id:
                messages.error(request, 'برنامه منتشر شده است؛ تغییرات فقط از طریق مدیریت برنامه و تیکت اعمال می‌شود.')
            elif action != 'message' and submission.status != 'submitted':
                messages.error(request, 'این درخواست در انتظار بررسی نیست.')
            elif action in ('return', 'message'):
                note = request.POST.get('feedback', '').strip()
                if not note or len(note) > 3000:
                    messages.error(request, 'پیام برای برگزارکننده را بنویس؛ حداکثر ۳۰۰۰ نویسه.')
                    return show(request, 'request', 'requests', 'بررسی درخواست برنامه', submission=submission,
                        review_groups=_review(submission), admin_review=True, feedback=note,
                        requires_license=submission.category in ('theater', 'concert'),
                        has_initial_schedule='opening_sessions' in submission.data,
                        initial_sales_form=InitialSalesApprovalForm(),
                        proposed_opening_count=len(submission.data.get('opening_sessions') or []))
                send_review_message(request, submission, note, needs_changes=action == 'return')
                if action == 'return':
                    submission.status = 'draft'
                    submission.data = {**submission.data, 'review_feedback': note}
                submission.save(update_fields=['status', 'data', 'updated_at'])
                audit(request, submission, 'درخواست همراه پیام برای اصلاح بازگشت.' if action == 'return' else 'پیام بررسی برای برگزارکننده ثبت شد.')
                messages.success(request, 'درخواست همراه پیام برای اصلاح برگشت.' if action == 'return' else 'پیام در تیکت مرتبط با برنامه ثبت شد.')
            elif action == 'publish':
                try:
                    event = publish_proposal(request, submission)
                except ValidationError as error:
                    submission.refresh_from_db()
                    messages.error(request, error.messages[0])
                    return show(request, 'request', 'requests', 'بررسی درخواست برنامه', submission=submission,
                        review_groups=_review(submission), admin_review=True,
                        requires_license=submission.category in ('theater', 'concert'),
                        has_initial_schedule='opening_sessions' in submission.data,
                        initial_sales_form=InitialSalesApprovalForm(request.POST),
                        proposed_opening_count=len(submission.data.get('opening_sessions') or []))
                else:
                    if event.sessions.exists():
                        opened = event.sessions.filter(ticket_sales_enabled=True).count()
                        messages.success(request, f'برنامه منتشر شد و سانس‌ها ساخته شدند؛ فروش {opened} سانس فعال است.')
                    else:
                        messages.success(request, 'برنامه منتشر شد؛ برای آغاز فروش، سانس و قیمت‌ها را تنظیم کن.')
                    return redirect(reverse('management:session_create') + f'?event={event.pk}') if not event.sessions.exists() else redirect('management:events')
        return redirect('management:request_detail', submission.pk)
    return show(request, 'request', 'requests', 'بررسی درخواست برنامه', submission=submission,
        review_groups=_review(submission), admin_review=True,
        requires_license=submission.category in ('theater', 'concert'),
        has_initial_schedule='opening_sessions' in submission.data, initial_sales_form=InitialSalesApprovalForm(),
        proposed_opening_count=len(submission.data.get('opening_sessions') or []))


@managed
def venues(request):
    rows = Stadium.objects.annotate(section_count=Count('blocks', distinct=True), seat_count=Count('blocks__rows__seats', distinct=True))
    query = request.GET.get('q', '').strip()[:100]
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(city__icontains=query))
    return show(request, 'list', 'venues', 'سالن‌ها و چیدمان صندلی‌ها', page_obj=paginate(request, rows.order_by('name')), query=query)


@managed
def venue_edit(request, venue_id=None):
    venue = get_object_or_404(Stadium, pk=venue_id) if venue_id else None
    form = VenueForm(request.POST or None, request.FILES or None, instance=venue)
    if venue and venue.blocks.exists():
        form.fields['seat_layout'].disabled = True
        form.fields['base_price'].disabled = True
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            obj = form.save()
            plan = form.cleaned_data['seat_layout']
            if plan.get('sections') and not obj.blocks.exists():
                obj.capacity = layout_capacity(plan)
                obj.save(update_fields=['capacity'])
                build_venue(obj, plan, form.cleaned_data['base_price'] * 10)
            audit(request, obj, 'سالن در پنل دیدآور ذخیره شد.', created=venue is None)
        messages.success(request, 'سالن ذخیره شد و در فهرست سالن‌های آماده در دسترس است.')
        return redirect('management:venues')
    return show(request, 'venue_form', 'venues', 'ویرایش اطلاعات سالن' if venue else 'ساخت سالن جدید', form=form, venue=venue,
        admin_builder=True, layout_locked=bool(venue and venue.blocks.exists()), blocks=list(venue.blocks.prefetch_related('rows__seats')) if venue else [])


@managed
def users(request):
    rows = User.objects.filter(user_type='normal').annotate(program_count=Count('event_submissions', distinct=True))
    query = request.GET.get('q', '').strip()[:100]
    if query:
        rows = rows.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(phone_number__icontains=query) | Q(username__icontains=query))
    return show(request, 'list', 'users', 'کاربران و برگزارکنندگان', page_obj=paginate(request, rows.order_by('-date_joined')), query=query)


@managed
def user_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id, user_type='normal', is_staff=False, is_superuser=False)
    form = ManagedUserForm(request.POST or None, instance=user)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        audit(request, obj, 'اطلاعات کاربر در پنل دیدآور ذخیره شد.')
        messages.success(request, 'اطلاعات کاربر ذخیره شد.')
        return redirect('management:user_detail', user.pk)
    return show(request, 'form', 'users', user.get_full_name() or user.username, form=form, target_user=user,
        user_programs=user.event_submissions.all()[:10], stats=statistics(cultural_tickets().filter(user=user)))


@managed
def site_settings(request):
    form = ManagedSettingsForm(request.POST or None, instance=SiteSettings.get_solo())
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        audit(request, obj, 'تنظیمات دیدآور ذخیره شد.')
        messages.success(request, 'تنظیمات سایت ذخیره شد.')
        return redirect('management:settings')
    return show(request, 'form', 'settings', 'تنظیمات دیدآور', form=form)


@managed
@require_GET
def banners(request):
    items = HomeBanner.objects.select_related('event')
    query = request.GET.get('q', '').strip()[:100]
    state = request.GET.get('state', '')
    if query:
        items = items.filter(title__icontains=query)
    if state in ('active', 'inactive'):
        items = items.filter(is_active=state == 'active')
    return show(request, 'banners', 'banners', 'بنرهای اسلایدر صفحه اصلی',
        page_obj=paginate(request, items), query=query, selected_state=state,
        using_defaults=not HomeBanner.objects.exists(), default_banners=[{'title': title, 'image_url': static('events/uploads/' + image)} for title, image in DEFAULT_BANNERS], active_count=HomeBanner.objects.filter(is_active=True).count())


@managed
@require_http_methods(['POST'])
def banner_import_defaults(request):
    try:
        with transaction.atomic():
            banners = install_default_banners()
            for banner in banners:
                audit(request, banner, 'بنر اولیه سایت به بخش مدیریت وارد شد.', created=True)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, 'بنرهای اولیه اکنون قابل ویرایش و مدیریت هستند.' if banners else 'بنرهای قابل مدیریت از قبل ثبت شده‌اند؛ تغییری انجام نشد.')
    return redirect('management:banners')


@managed
def banner_edit(request, banner_id=None):
    banner = get_object_or_404(HomeBanner, pk=banner_id) if banner_id else None
    form = HomeBannerForm(request.POST if request.method == 'POST' else None, request.FILES or None,
        instance=banner, initial={'is_active': True} if banner is None else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            obj = form.save()
            audit(request, obj, 'بنر صفحه اصلی ذخیره شد.', created=banner is None)
        messages.success(request, 'بنر ذخیره شد؛ اسلایدر صفحه اصلی از بنرهای فعال همین بخش استفاده می‌کند.')
        return redirect('management:banners')
    return show(request, 'banner_form', 'banners', 'ویرایش بنر' if banner else 'بارگذاری بنر جدید', form=form, banner=banner, using_defaults=not HomeBanner.objects.exists())


@managed
@require_http_methods(['POST'])
def banner_toggle(request, banner_id):
    with transaction.atomic():
        banner = get_object_or_404(HomeBanner.objects.select_for_update(), pk=banner_id)
        if request.POST.get('action') not in ('activate', 'deactivate'):
            raise Http404
        banner.is_active = request.POST['action'] == 'activate'
        banner.save(update_fields=['is_active', 'updated_at'])
        audit(request, banner, 'بنر فعال شد.' if banner.is_active else 'بنر غیرفعال شد.')
    messages.success(request, 'وضعیت نمایش بنر ذخیره شد.')
    return redirect('management:banners')
