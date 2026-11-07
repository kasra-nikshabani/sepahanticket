"""Public event catalogue and central event management."""
from django.contrib import messages
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator

from django.db.models import Avg, Count, Prefetch, Q, Subquery, OuterRef, F
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from urllib.parse import urlencode
from .banner_defaults import DEFAULT_BANNERS
from django.templatetags.static import static
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
from .templatetags.jalali import to_jalali_date
from .event_search import (CATEGORIES, PERIODS, SORTS, active_filters,
                           matching_events, normalized, public_cities, public_sessions, search_options, suggested_artists)

from .forms import EventForm, EventSceneImageFormSet
from .models import (Event, HomeBanner, Match, Stadium, get_active_block_ids,
                     get_active_row_ids, get_seat_price_map)


def session_price(session):
    """Starting tariff for enabled inventory, respecting session overrides."""
    seat_ids = session.match_seats.filter(
        is_enabled=True, seat__is_available=True,
        seat__row_id__in=get_active_row_ids(session),
        seat__row__block_id__in=get_active_block_ids(session),
    ).values_list('seat_id', flat=True)
    from .models import Seat
    prices = get_seat_price_map(session, Seat.objects.filter(pk__in=seat_ids).select_related('row__block'))
    session.starting_price = min(prices.values(), default=None)
    return session.starting_price


def prepare_event(event):
    for session in event.upcoming_sessions:
        session_price(session)
        prepare_session_status(session)
    prices = [s.starting_price for s in event.upcoming_sessions if s.can_purchase]
    event.starting_price = min((p for p in prices if p is not None), default=None)
    event.sale_open = any(s.can_purchase for s in event.upcoming_sessions)
    event.sale_label = event_sale_label(event.upcoming_sessions)
    if not event.upcoming_sessions and event.sessions.filter(is_active=True, date_time__lte=timezone.now()).exists():
        event.sale_label = 'اجراهای این برنامه پایان یافته'
    return event


def prepare_session_status(session):
    """Explain unavailable sales without treating temporary holds as sold tickets."""
    session.can_purchase = False
    session.available_count = None
    if session.is_cancelled:
        status, label = 'cancelled', 'سانس لغو شده'
    elif session.date_time <= timezone.now():
        status, label = 'ended', 'فروش این سانس پایان یافته'
    elif not session.sales_available:
        status, label = 'closed', 'فروش این سانس بسته است'
    else:
        inventory = session.match_seats.filter(
            is_enabled=True, seat__is_available=True,
            seat__row_id__in=get_active_row_ids(session),
            seat__row__block_id__in=get_active_block_ids(session))
        total = inventory.count()
        sold = inventory.filter(ticket__status__in=['paid', 'admin_assigned', 'vip_issued']).distinct().count()
        if not total:
            status, label = 'preparing', 'صندلی‌های این سانس هنوز آماده نیستند'
        elif sold == total:
            status, label = 'sold_out', 'ظرفیت تکمیل شده'
        elif (available := inventory.exclude(ticket__status__in=['paid', 'admin_assigned', 'vip_issued']).filter(
                Q(is_available=True) | Q(reserved_until__lte=timezone.now())).count()):
            status, label = 'open', 'فروش باز است'
            session.can_purchase = True
            session.available_count = available
        elif inventory.filter(reserved_until__gt=timezone.now()).exists():
            status, label = 'reserved', 'صندلی‌ها در حال رزرو هستند؛ کمی بعد بررسی کنید'
        else:
            status, label = 'unavailable', 'فعلاً صندلی قابل خریدی نیست'
    session.sale_status, session.sale_label = status, label


def event_sale_label(sessions):
    if not sessions:
        return 'سانس‌ها به‌زودی اعلام می‌شوند'
    if any(s.can_purchase for s in sessions):
        return 'انتخاب سانس'
    if all(s.sale_status == 'sold_out' for s in sessions):
        return 'ظرفیت سانس‌ها تکمیل شده'
    if all(s.sale_status == 'ended' for s in sessions):
        return 'اجراهای این برنامه پایان یافته'
    if all(s.sale_status == 'cancelled' for s in sessions):
        return 'سانس‌ها لغو شده‌اند'
    return 'مشاهده وضعیت سانس‌ها'


def homepage(request):
    # Preserve old search links; the landing page itself contains no filters.
    if any(request.GET.get(key) for key in ('q', 'category', 'city', 'period', 'sort', 'page')):
        return catalogue(request)
    sessions = Match.objects.filter(is_active=True, is_cancelled=False,
                                    date_time__gte=timezone.now()).select_related('stadium', 'event').order_by('date_time')
    sections = []
    for category, title in (('theater', 'نمایش‌ها'), ('concert', 'کنسرت‌ها'), ('event', 'رویدادها')):
        events = list(Event.objects.filter(is_active=True, category=category)
                      .annotate(rating_average=Avg('ratings__score'), rating_count=Count('ratings', distinct=True))
                      .order_by('-created_at', '-pk')
                      .prefetch_related(Prefetch('sessions', queryset=sessions, to_attr='upcoming_sessions'))[:5])
        sections.append({'category': category, 'title': title,
                         'events': [prepare_event(event) for event in events]})
    banners = []
    if HomeBanner.objects.exists():
        for banner in HomeBanner.objects.filter(is_active=True).select_related('event'):
            banners.append({'title': banner.title, 'image_url': banner.image.url,
                'url': reverse('matches:event_detail', args=[banner.event_id]) if banner.event and banner.event.is_active else None})
    else:
        for title, image in DEFAULT_BANNERS:
            featured = Event.objects.filter(is_active=True, title=title, sessions__in=sessions).first()
            banners.append({'title': title, 'image_url': static('events/uploads/' + image),
                            'url': reverse('matches:event_detail', args=[featured.pk]) if featured else
                            reverse('matches:event_catalogue') + '?' + urlencode({'q': title})})
    return render(request, 'events/home.html', {'sections': sections, 'featured_banners': banners})


def catalogue(request):
    options = search_options(request.GET)
    query, category, city, period, sort = (options[key] for key in ('q', 'category', 'city', 'period', 'sort'))
    sessions = public_sessions(options).select_related('stadium', 'event').order_by('date_time', 'pk')
    events = matching_events(options, sessions).annotate(
        rating_average=Avg('ratings__score'), rating_count=Count('ratings', distinct=True),
        next_session=Subquery(sessions.filter(event_id=OuterRef('pk')).values('date_time')[:1]),
    ).prefetch_related(Prefetch('sessions', queryset=sessions, to_attr='upcoming_sessions'))
    if sort == 'title':
        events = events.order_by('title', 'pk')
    elif sort == 'new':
        events = events.order_by('-created_at', '-pk')
    elif sort == 'rating':
        events = events.order_by(F('rating_average').desc(nulls_last=True), '-rating_count', 'pk')
    elif sort == 'relevance' and normalized(query):
        events = events.order_by('-search_rank', F('next_session').asc(nulls_last=True), '-created_at', 'pk')
    else:
        events = events.order_by(F('next_session').asc(nulls_last=True), 'pk')
    page = Paginator(events, 12).get_page(request.GET.get('page'))
    for event in page:
        prepare_event(event)
    params = {key: value for key, value in options.items() if value}
    catalogue_url = reverse('matches:event_catalogue')
    return render(request, 'events/catalogue.html', {
        'page_obj': page, 'categories': CATEGORIES, 'periods': PERIODS, 'sorts': SORTS,
        'cities': public_cities(), 'query': query, 'selected_category': category, 'selected_city': city,
        'catalogue_title': 'نتایج جست‌وجو' if query else {'theater': 'نمایش‌ها', 'concert': 'کنسرت‌ها', 'event': 'رویدادها'}.get(category, 'همه برنامه‌ها'),
        'catalogue_noun': {'theater': 'نمایش', 'concert': 'کنسرت', 'event': 'رویداد'}.get(category, 'برنامه'),
        'selected_period': period, 'selected_sort': sort, 'active_filters': active_filters(options, catalogue_url),
        'filter_query': urlencode(params),
        'newest_query': urlencode({**params, 'sort': 'new'}),
        'artist_matches': list(suggested_artists(options, sessions)[:4]) if len(normalized(query)) >= 2 else [],
        'is_demo': getattr(settings, 'EVENT_DEMO_MODE', False),
    })


@require_GET
@never_cache
def search_suggestions(request):
    options = search_options(request.GET)
    options['sort'] = 'relevance'
    if len(normalized(options['q'])) < 2:
        return JsonResponse({'events': [], 'artists': [], 'has_more': False})
    sessions = public_sessions(options).order_by('date_time', 'pk')
    events = matching_events(options, sessions).annotate(
        next_date=Subquery(sessions.filter(event_id=OuterRef('pk')).values('date_time')[:1]),
        next_venue=Subquery(sessions.filter(event_id=OuterRef('pk')).values('stadium__name')[:1]),
        next_city=Subquery(sessions.filter(event_id=OuterRef('pk')).values('stadium__city')[:1]),
    ).order_by('-search_rank', F('next_date').asc(nulls_last=True), '-created_at', 'pk')
    found = list(events[:7])
    artists = suggested_artists(options, sessions)
    profiles = list(artists[:3])
    return JsonResponse({
        'events': [{'title': event.title, 'category': dict(CATEGORIES)[event.category],
                    'venue': event.next_venue or 'سانس‌ها به‌زودی اعلام می‌شوند',
                    'city': event.next_city or '', 'date': to_jalali_date(event.next_date),
                    'url': reverse('matches:event_detail', args=[event.pk]),
                    'image': event.poster.url if event.poster else ''} for event in found[:6]],
        'artists': [{'title': artist.display_name, 'specialty': artist.specialty or artist.get_discipline_display(),
                     'url': artist.get_absolute_url(), 'image': artist.avatar.url if artist.avatar else ''} for artist in profiles],
        'has_more': len(found) > 6,
    }, json_dumps_params={'ensure_ascii': False})


def event_detail(request, event_id):
    event = get_object_or_404(Event.objects.annotate(
        rating_average=Avg('ratings__score'), rating_count=Count('ratings', distinct=True)),
        pk=event_id, is_active=True)
    sessions = list(event.sessions.filter(is_active=True).select_related('stadium', 'event').order_by('date_time'))
    # Future performances first; retain completed performances for a clear ended state.
    now = timezone.now()
    upcoming = [s for s in sessions if s.date_time > now]
    sessions = upcoming or sessions
    for session in sessions:
        session_price(session)
        prepare_session_status(session)
    prices = [s.starting_price for s in sessions if s.can_purchase and s.starting_price is not None]
    venues = {session.stadium_id: session.stadium for session in sessions}
    groups = {}
    for session in sessions:
        day = timezone.localtime(session.date_time).date().isoformat()
        groups.setdefault(day, {'key': day, 'date': session.date_time, 'sessions': []})['sessions'].append(session)
    nearest_session = next((s for s in sessions if s.can_purchase), None)
    from artists.services import public_credits
    artist_credits = public_credits().filter(event=event).select_related('artist')
    return render(request, 'events/detail.html', {
        'event': event, 'sessions': sessions, 'scene_images': list(event.scene_images.all()),
        'starting_price': min(prices, default=None),
        'sale_open': any(s.can_purchase for s in sessions),
        'sale_label': event_sale_label(sessions),
        'venues': list(venues.values()),
        'session_groups': list(groups.values()), 'nearest_session': nearest_session,
        'artist_credits': artist_credits,
    })


@staff_member_required
def event_list(request):
    return render(request, 'events/admin_list.html', {'events': Event.objects.all()})


@staff_member_required
def event_edit(request, event_id=None):
    event = get_object_or_404(Event, pk=event_id) if event_id else None
    form = EventForm(request.POST or None, request.FILES or None, instance=event)
    scene_formset = EventSceneImageFormSet(request.POST or None, request.FILES or None,
                                         instance=form.instance, prefix='scenes')
    if request.method == 'POST' and form.is_valid() and scene_formset.is_valid():
        with transaction.atomic():
            form.save()
            scene_formset.save()
        messages.success(request, 'رویداد ذخیره شد. اکنون می‌توانید سانس‌های آن را تعریف کنید.')
        return redirect('matches:event_list')
    return render(request, 'events/admin_form.html', {'form': form, 'event': event,
                                                    'scene_formset': scene_formset})
