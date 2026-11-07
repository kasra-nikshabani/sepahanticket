"""Shared, bounded public catalogue search; no private account fields."""
import unicodedata
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Case, Exists, F, IntegerField, OuterRef, Q, Value, When
from django.db.models.functions import Concat, Lower, Replace
from django.utils import timezone

from .models import Event, Match


CATEGORIES = (('theater', 'نمایش'), ('concert', 'کنسرت'), ('event', 'رویداد'))
PERIODS = (('today', 'امروز'), ('week', 'هفت روز آینده'), ('month', 'سی روز آینده'))
SORTS = (('relevance', 'مرتبط‌ترین'), ('soon', 'نزدیک‌ترین اجرا'),
         ('new', 'تازه‌ترین‌ها'), ('rating', 'بالاترین امتیاز'), ('title', 'نام برنامه'))
TRANSLATION = str.maketrans('يك٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', 'یک01234567890123456789')
REMOVED = '\u200c\u200d\u200e\u200f\u0640\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0670'


def clean_query(value):
    return ' '.join(value[:200].split())[:120]


def normalized(value):
    value = unicodedata.normalize('NFKC', value).translate(TRANSLATION).lower()
    return ''.join(c for c in value if c not in REMOVED and not c.isspace()
                   and unicodedata.category(c) != 'Mn')


def search_expression(*fields):
    expression = Concat(*(item for field in fields for item in (F(field), Value(' '))))
    expression = Lower(expression)
    for old, new in zip('يك٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', 'یک01234567890123456789'):
        expression = Replace(expression, Value(old), Value(new))
    for char in ' \t\n\r' + REMOVED:
        expression = Replace(expression, Value(char), Value(''))
    return expression


def search_options(params):
    query = clean_query(params.get('q', ''))
    category = params.get('category', '')
    period = params.get('period', '')
    sort = params.get('sort', '')
    return {
        'q': query, 'category': category if category in dict(CATEGORIES) else '',
        'city': clean_query(params.get('city', ''))[:80],
        'period': period if period in dict(PERIODS) else '',
        'sort': sort if sort in dict(SORTS) else ('relevance' if query else 'soon'),
    }


def public_sessions(options=None):
    options = options or {}
    now = timezone.now()
    sessions = Match.objects.filter(is_active=True, is_cancelled=False, date_time__gt=now)
    if options.get('period'):
        days = {'today': 1, 'week': 7, 'month': 30}[options['period']]
        end = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
        sessions = sessions.filter(date_time__lt=end)
    if options.get('city'):
        sessions = sessions.alias(_city=search_expression('stadium__city')).filter(_city=normalized(options['city']))
    return sessions


def public_cities():
    return public_sessions().filter(event__is_active=True, event__category__in=dict(CATEGORIES)).exclude(
        stadium__city='').order_by('stadium__city').values_list('stadium__city', flat=True).distinct()


def matching_events(options, sessions):
    from artists.services import public_credits

    events = Event.objects.filter(is_active=True, category__in=dict(CATEGORIES))
    future = sessions.filter(event_id=OuterRef('pk'))
    if options['city'] or options['period'] or options['sort'] not in ('new', 'relevance', 'rating'):
        events = events.filter(Exists(future))
    elif options['q'] or options['sort'] != 'new':
        # Announced programmes can be found before scheduling; past-only programmes cannot.
        active = Match.objects.filter(event_id=OuterRef('pk'), is_active=True)
        events = events.filter(Q(Exists(future)) | Q(~Exists(active)))
    if options['category']:
        events = events.filter(category=options['category'])
    tokens = list(dict.fromkeys(normalized(token) for token in options['q'].split(maxsplit=5)))
    tokens = [token for token in tokens if token]
    if not tokens:
        return events
    events = events.alias(_text=search_expression('title', 'artists', 'organizer'),
                          _title=search_expression('title'))
    for token in tokens:
        venues = future.alias(_text=search_expression('stadium__name', 'stadium__city')).filter(_text__contains=token)
        credits = public_credits().filter(event_id=OuterRef('pk')).alias(
            _text=search_expression('artist__display_name')).filter(_text__contains=token)
        events = events.filter(Q(_text__contains=token) | Q(Exists(venues)) | Q(Exists(credits)))
    phrase = normalized(options['q'])
    return events.annotate(search_rank=Case(
        When(_title=phrase, then=Value(100)),
        When(_title__startswith=phrase, then=Value(70)),
        When(_title__contains=phrase, then=Value(50)),
        default=Value(10), output_field=IntegerField()))


def matching_artists(query):
    from artists.services import public_artists
    artists = public_artists().alias(_text=search_expression('display_name', 'specialty', 'city'),
                                    _name=search_expression('display_name'))
    tokens = [normalized(token) for token in query.split(maxsplit=5)]
    for token in filter(None, tokens):
        artists = artists.filter(_text__contains=token)
    phrase = normalized(query)
    return artists.annotate(search_rank=Case(
        When(_name=phrase, then=Value(100)), When(_name__startswith=phrase, then=Value(70)),
        default=Value(10), output_field=IntegerField())).order_by('-search_rank', 'display_name', 'pk')


def suggested_artists(options, sessions):
    from artists.services import public_credits
    artists = matching_artists(options['q'])
    if options['city'] or options['category'] or options['period']:
        credits = public_credits().filter(artist_id=OuterRef('pk'),
            event_id__in=matching_events(options, sessions).values('pk'))
        artists = artists.filter(Exists(credits))
    return artists


def active_filters(options, catalogue_url):
    labels = {'q': 'جست‌وجو: ', 'category': '', 'city': 'شهر: ', 'period': ''}
    chips = []
    for key, prefix in labels.items():
        if options[key]:
            params = {k: v for k, v in options.items() if v and k != key}
            if key == 'q' and params.get('sort') == 'relevance':
                params['sort'] = 'soon'
            value = dict(CATEGORIES if key == 'category' else PERIODS).get(options[key], options[key])
            chips.append({'label': prefix + value, 'url': catalogue_url + '?' + urlencode(params)})
    return chips
