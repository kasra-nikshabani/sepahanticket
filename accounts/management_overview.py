"""Read-only overview of the cultural platform; monetary values are in rial."""
from datetime import datetime, time, timedelta

from django.contrib.admin.models import LogEntry
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.urls import reverse
from django.utils import timezone

from artists.models import ArtistProfile, CollaborationApplication, CollaborationOpportunity, CollaborationReport
from education.models import Course, Enrollment, Lesson
from matches.models import Event, Match, Stadium
from studios.models import Booking, Studio, StudioSlot
from .models import EventSubmission, SupportTicket, User


def overview_context(tickets, ticket_stats, now, days=7):
    local_now = timezone.localtime(now)
    today = local_now.date()
    start_today = timezone.make_aware(datetime.combine(today, time.min))
    until = start_today + timedelta(days=1)
    since = start_today - timedelta(days=days - 1)

    events = Event.objects.filter(category__in=['theater', 'concert', 'event'])
    sessions = Match.objects.filter(event__in=events, date_time__gt=now, is_cancelled=False)
    event_counts = events.aggregate(total=Count('pk'), live=Count('pk', filter=Q(is_active=True)))
    session_counts = sessions.aggregate(total=Count('pk'), selling=Count('pk', filter=Q(
        is_active=True, ticket_sales_enabled=True, event__is_active=True)))
    course_counts = Course.objects.aggregate(total=Count('pk'),
        live=Count('pk', filter=Q(status='published', owner__is_active=True)),
        recorded=Count('pk', filter=Q(kind='recorded')), classes=Count('pk', filter=Q(kind='class')),
        pending=Count('pk', filter=Q(status='pending')))
    studio_counts = Studio.objects.aggregate(total=Count('pk'),
        live=Count('pk', filter=Q(status='published', owner__is_active=True)),
        pending=Count('pk', filter=Q(status='pending')))
    artist_counts = ArtistProfile.objects.aggregate(total=Count('pk'),
        live=Count('pk', filter=Q(status='approved', is_visible=True, owner__is_active=True)),
        available=Count('pk', filter=Q(status='approved', is_visible=True, owner__is_active=True, looking_for_work=True)),
        pending=Count('pk', filter=Q(status='pending')))
    opportunity_counts = CollaborationOpportunity.objects.aggregate(total=Count('pk'),
        open=Count('pk', filter=Q(status='published', owner__is_active=True, deadline__gte=today)),
        pending=Count('pk', filter=Q(status='pending')))
    application_counts = CollaborationApplication.objects.aggregate(total=Count('pk'),
        accepted=Count('pk', filter=Q(status='accepted')))
    support_counts = SupportTicket.objects.aggregate(total=Count('pk'),
        waiting=Count('pk', filter=Q(status='waiting')),
        program=Count('pk', filter=Q(status='waiting', category='program')),
        general=Count('pk', filter=Q(status='waiting', category='general')))
    requests = EventSubmission.objects.filter(status='submitted')
    pending_requests = requests.count()
    report_rows = CollaborationReport.objects.filter(resolved_at__isnull=True)
    report_count = report_rows.count()
    failed_lessons = Lesson.objects.filter(is_active=True, state='failed', course__status__in=['pending', 'published'])
    video_counts = Lesson.objects.filter(is_active=True).aggregate(
        processing=Count('pk', filter=Q(state__in=['queued', 'processing'])))
    failed_count = failed_lessons.count()
    users = User.objects.filter(user_type='normal', is_staff=False).aggregate(
        total=Count('pk'), new=Count('pk', filter=Q(date_joined__gte=since, date_joined__lt=until)))
    free_hours = StudioSlot.objects.filter(starts_at__gt=now, state='open', booking__isnull=True,
        studio__status='published', studio__booking_open=True, studio__owner__is_active=True).count()

    channels = []
    recent_sales = []
    daily = {since.date() + timedelta(days=i): {
        'day': since + timedelta(days=i), 'revenue': 0, 'count': 0, 'ticket': 0, 'education': 0, 'studio': 0,
    } for i in range(days)}
    sources = [
        ('ticket', 'فروش بلیط', 'fa-ticket', tickets.filter(status='paid'), 'purchase_date', 'price', 'management:sales'),
        ('education', 'فروش آموزش', 'fa-graduation-cap', Enrollment.objects.filter(status='active'), 'purchased_at', 'paid_rial', 'management:education'),
        ('studio', 'اجارهٔ پلاتو', 'fa-door-open', Booking.objects.filter(status='confirmed'), 'created_at', 'paid_rial', 'management:studios'),
    ]
    for key, label, icon, rows, date_field, amount_field, route in sources:
        totals = ({'count': ticket_stats['sold'], 'revenue': ticket_stats['revenue']} if key == 'ticket' else
            rows.aggregate(count=Count('pk'), revenue=Sum(amount_field, default=0)))
        period_count = period_revenue = today_count = today_revenue = 0
        trend = rows.filter(**{date_field + '__gte': since, date_field + '__lt': until}).order_by().annotate(
            day=TruncDate(date_field, tzinfo=timezone.get_current_timezone())).values('day').annotate(
                revenue=Sum(amount_field, default=0), count=Count('pk'))
        for point in trend:
            item = daily[point['day']]
            item[key] = point['revenue']
            item['revenue'] += point['revenue']
            item['count'] += point['count']
            period_revenue += point['revenue']
            period_count += point['count']
            if point['day'] == today:
                today_revenue, today_count = point['revenue'], point['count']
        channels.append({'key': key, 'label': label, 'icon': icon, 'url': reverse(route), **totals,
            'unit': {'ticket': 'بلیط', 'education': 'ثبت‌نام', 'studio': 'رزرو'}[key],
            'period_count': period_count, 'period_revenue': period_revenue,
            'today_count': today_count, 'today_revenue': today_revenue})
        related = {'ticket': ('match__event',), 'education': ('course',), 'studio': ('studio',)}[key]
        for sale in rows.select_related(*related).order_by('-' + date_field, '-pk')[:6]:
            if key == 'ticket':
                title, name, route, pk = sale.match.display_title, sale.full_name, 'management:session_sales', sale.match_id
            elif key == 'education':
                title, name, route, pk = sale.course_title, sale.learner_name, 'management:education_detail', sale.course_id
            else:
                title, name, route, pk = sale.studio_title, sale.renter_name, 'management:studio_detail', sale.studio_id
            recent_sales.append({'kind': label, 'key': key, 'icon': icon, 'title': title, 'name': name,
                'date': getattr(sale, date_field), 'amount': getattr(sale, amount_field) or 0, 'url': reverse(route, args=[pk])})
    peak = max((item['revenue'] for item in daily.values()), default=0)
    chart = list(daily.values())
    for item in chart:
        item['height'] = round(item['revenue'] / peak * 100, 2) if peak else 0
        item['segments'] = [{'key': c['key'], 'share': round(item[c['key']] / item['revenue'] * 100, 2) if item['revenue'] else 0} for c in channels]

    attention = [
        ('program', 'انتشار برنامه', pending_requests, 'fa-inbox', 'management:requests', ''),
        ('education', 'انتشار آموزش', course_counts['pending'], 'fa-graduation-cap', 'management:education', '?state=pending'),
        ('studio', 'انتشار پلاتو', studio_counts['pending'], 'fa-door-open', 'management:studios', '?state=pending'),
        ('artist', 'تأیید هنرمند', artist_counts['pending'], 'fa-user-check', 'management:artists', '?state=pending'),
        ('opportunity', 'انتشار فراخوان', opportunity_counts['pending'], 'fa-briefcase', 'management:opportunities', '?state=pending'),
        ('support', 'پاسخ به تیکت', support_counts['waiting'], 'fa-headset', 'management:support', '?status=waiting'),
        ('report', 'گزارش همکاری', report_count, 'fa-flag', 'management:opportunities', '?reports=open'),
    ]
    attention = [{'key': key, 'label': label, 'count': count, 'icon': icon, 'url': reverse(route) + suffix}
        for key, label, count, icon, route, suffix in attention]
    publication_count = sum(item['count'] for item in attention[:5])
    attention_count = sum(item['count'] for item in attention) + failed_count

    review_queue = []
    review_sources = [
        (requests, 'برنامه', 'fa-masks-theater', 'management:request_detail', 'title', 'submitted_at'),
        (Course.objects.filter(status='pending'), 'آموزش', 'fa-graduation-cap', 'management:education_detail', 'title', 'submitted_at'),
        (Studio.objects.filter(status='pending'), 'پلاتو', 'fa-door-open', 'management:studio_detail', 'title', 'submitted_at'),
        (ArtistProfile.objects.filter(status='pending'), 'هنرمند', 'fa-user-check', 'management:artist_detail', 'display_name', 'updated_at'),
        (CollaborationOpportunity.objects.filter(status='pending'), 'فراخوان', 'fa-briefcase', 'management:opportunity_detail', 'title', 'updated_at'),
    ]
    for rows, kind, icon, route, title_field, date_field in review_sources:
        for obj in rows.select_related('owner').annotate(_queue_date=Coalesce(date_field, 'created_at')).order_by('_queue_date', 'pk')[:6]:
            review_queue.append({'kind': kind, 'icon': icon, 'title': getattr(obj, title_field),
                'owner': obj.owner.get_full_name() or obj.owner.username, 'date': obj._queue_date,
                'url': reverse(route, args=[obj.pk])})
    review_queue.sort(key=lambda item: (item['date'], item['kind'], item['url']))

    upcoming = []
    for session in sessions.select_related('event', 'stadium').order_by('date_time', 'pk')[:6]:
        upcoming.append({'title': session.display_title, 'kind': 'سانس برنامه', 'icon': 'fa-masks-theater',
            'date': session.date_time, 'detail': session.stadium.name, 'state': 'فروش باز' if session.sales_available else 'فروش بسته',
            'url': reverse('management:session_sales', args=[session.pk])})
    for booking in Booking.objects.filter(status='confirmed', starts_at__gt=now).select_related('studio').order_by('starts_at', 'pk')[:6]:
        upcoming.append({'title': booking.studio_title, 'kind': 'رزرو پلاتو', 'icon': 'fa-door-open', 'date': booking.starts_at,
            'detail': booking.renter_name, 'state': 'رزرو قطعی', 'url': reverse('management:studio_detail', args=[booking.studio_id])})
    classes = Course.objects.filter(kind='class', status='published', owner__is_active=True,
        start_time__isnull=False).filter(Q(start_date__gt=today) | Q(start_date=today, start_time__gt=local_now.time()))
    for course in classes.order_by('start_date', 'start_time', 'pk')[:6]:
        upcoming.append({'title': course.title, 'kind': 'آغاز کلاس', 'icon': 'fa-graduation-cap', 'date': course.starts_at,
            'detail': course.academy or course.city, 'state': 'کلاس حضوری', 'url': reverse('management:education_detail', args=[course.pk])})
    upcoming.sort(key=lambda item: (item['date'], item['kind'], item['url']))

    def metric(label, value):
        return {'label': label, 'value': value}

    modules = [
        {'title': 'برنامه‌ها و بلیط', 'icon': 'fa-masks-theater', 'url': reverse('management:events'), 'pending': pending_requests,
            'metrics': [metric('کل برنامه‌ها', event_counts['total']), metric('برنامهٔ فعال', event_counts['live']), metric('سانس پیش رو', session_counts['total']), metric('فروش باز سانس', session_counts['selling'])]},
        {'title': 'آموزش', 'icon': 'fa-graduation-cap', 'url': reverse('management:education'), 'pending': course_counts['pending'],
            'metrics': [metric('آموزش منتشرشده', course_counts['live']), metric('دورهٔ ضبط‌شده', course_counts['recorded']), metric('کلاس حضوری', course_counts['classes']), metric('ثبت‌نام فعال', channels[1]['count'])]},
        {'title': 'پلاتو', 'icon': 'fa-door-open', 'url': reverse('management:studios'), 'pending': studio_counts['pending'],
            'metrics': [metric('پلاتو منتشرشده', studio_counts['live']), metric('کل پلاتوها', studio_counts['total']), metric('ساعت قابل رزرو', free_hours), metric('رزرو قطعی', channels[2]['count'])]},
        {'title': 'هنرمندان', 'icon': 'fa-user-check', 'url': reverse('management:artists'), 'pending': artist_counts['pending'],
            'metrics': [metric('پروفایل عمومی', artist_counts['live']), metric('کل پروفایل‌ها', artist_counts['total']), metric('آمادهٔ همکاری', artist_counts['available']), metric('در انتظار تأیید', artist_counts['pending'])]},
        {'title': 'فرصت‌های همکاری', 'icon': 'fa-briefcase', 'url': reverse('management:opportunities'), 'pending': opportunity_counts['pending'],
            'metrics': [metric('فراخوان باز', opportunity_counts['open']), metric('کل فراخوان‌ها', opportunity_counts['total']), metric('درخواست همکاری', application_counts['total']), metric('همکاری تأییدشده', application_counts['accepted'])]},
        {'title': 'پشتیبانی', 'icon': 'fa-headset', 'url': reverse('management:support'), 'pending': support_counts['waiting'],
            'metrics': [metric('تیکت منتظر پاسخ', support_counts['waiting']), metric('مرتبط با برنامه', support_counts['program']), metric('پشتیبانی کاربران', support_counts['general']), metric('کل تیکت‌ها', support_counts['total'])]},
    ]
    return {
        'overview_days': days, 'overview_users': users, 'modules': modules, 'attention': attention,
        'attention_count': attention_count, 'publication_count': publication_count,
        'finance': {'channels': channels, 'total_revenue': sum(c['revenue'] for c in channels),
            'total_count': sum(c['count'] for c in channels), 'period_revenue': sum(c['period_revenue'] for c in channels),
            'period_count': sum(c['period_count'] for c in channels), 'today_revenue': sum(c['today_revenue'] for c in channels),
            'today_count': sum(c['today_count'] for c in channels)},
        'overview_chart': chart, 'recent_sales': sorted(recent_sales, key=lambda item: item['date'], reverse=True)[:6],
        'review_queue': review_queue[:6], 'upcoming': upcoming[:6],
        'support_queue': SupportTicket.objects.filter(status='waiting').select_related('requester').order_by('updated_at', 'pk')[:4],
        'report_queue': report_rows.select_related('opportunity').order_by('created_at', 'pk')[:3],
        'failed_lessons': failed_lessons.select_related('course').order_by('updated_at', 'pk')[:3],
        'failed_lesson_count': failed_count, 'processing_lesson_count': video_counts['processing'],
        'unscheduled_count': events.filter(is_active=True, sessions__isnull=True).count(),
        'empty_venues': Stadium.objects.annotate(physical_seats=Count('blocks__rows__seats')).filter(physical_seats=0).count(),
        'recent_management': LogEntry.objects.select_related('user').order_by('-action_time', '-pk')[:4],
    }
