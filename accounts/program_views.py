"""Owner-only organizer reports. Publication links are server-owned foreign keys."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from matches.models import MatchSeat, Block
from tickets.models import Ticket
from .models import EventSubmission
from .submission_views import _review
from .program_seating import annotate_seats, map_rows, map_details

ISSUED = ('paid', 'admin_assigned', 'vip_issued')


def statistics(tickets):
    return tickets.aggregate(
        sold=Count('pk', filter=Q(status='paid')),
        revenue=Sum('price', filter=Q(status='paid'), default=0),
        complimentary=Count('pk', filter=Q(status__in=('admin_assigned', 'vip_issued'))),
        used=Count('pk', filter=Q(status__in=ISSUED, is_used=True)),
        buyers=Count('user_id', filter=Q(status='paid'), distinct=True),
        cancelled=Count('pk', filter=Q(status='cancelled')),
    )


@login_required
@never_cache
@require_GET
def program_list(request):
    owned = EventSubmission.objects.filter(owner=request.user).select_related('published_event')
    event_ids = owned.exclude(published_event=None).values_list('published_event_id', flat=True)
    stats = statistics(Ticket.objects.filter(match__event_id__in=event_ids))
    totals = {row['match__event_id']: row for row in Ticket.objects.filter(
        match__event_id__in=event_ids, status='paid').values('match__event_id').annotate(
            sold=Count('pk'), revenue=Sum('price', default=0))}
    page = Paginator(owned, 12).get_page(request.GET.get('page'))
    for program in page:
        program.sales = totals.get(program.published_event_id, {'sold': 0, 'revenue': 0})
        publication = program.data.get('publication_snapshot') or program.data
        program.report_quantity = publication.get('admission_mode') == 'quantity'
    return render(request, 'accounts/program_list.html', {
        'page_obj': page, 'stats': stats, 'program_count': owned.count(),
        'published_count': owned.filter(published_event__is_active=True).count(),
    })


@login_required
@never_cache
@require_GET
def program_detail(request, submission_id, session_id=None):
    program = get_object_or_404(EventSubmission.objects.select_related('published_event'),
                                pk=submission_id, owner=request.user)
    event = program.published_event
    publication = program.data.get('publication_snapshot') or program.data
    program.report_capacity = publication.get('ticket_capacity')
    program.report_price = publication.get('ticket_price')
    sessions = list(event.sessions.select_related('stadium').order_by('date_time', 'pk')) if event else []
    selected = None
    if session_id is not None:
        selected = next((session for session in sessions if session.pk == session_id), None)
        if selected is None:
            from django.http import Http404
            raise Http404
    tickets = Ticket.objects.filter(match__event=event) if event else Ticket.objects.none()
    program_stats = statistics(tickets)
    per_session = {row['match_id']: row for row in tickets.values('match_id').annotate(
        sold=Count('pk', filter=Q(status='paid')),
        revenue=Sum('price', filter=Q(status='paid'), default=0),
        complimentary=Count('pk', filter=Q(status__in=('admin_assigned', 'vip_issued'))),
        used=Count('pk', filter=Q(status__in=ISSUED, is_used=True)),
    )}
    for session in sessions:
        session.sales = per_session.get(session.pk, dict(sold=0, revenue=0, complimentary=0, used=0))
    if selected:
        tickets = tickets.filter(match=selected)
    stats = statistics(tickets) if selected else program_stats
    status = request.GET.get('status', 'issued')
    if status not in ('issued', 'paid', 'admin_assigned', 'vip_issued', 'cancelled', 'pending'):
        status = 'issued'
    tickets = tickets.filter(status__in=ISSUED) if status == 'issued' else tickets.filter(status=status)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        tickets = tickets.filter(Q(full_name__icontains=query) | Q(user__first_name__icontains=query) |
                                 Q(user__last_name__icontains=query))
    tickets = tickets.select_related('user', 'match', 'seat__row__block', 'order').order_by('-purchase_date', '-pk')
    page = Paginator(tickets, 30).get_page(request.GET.get('page'))
    seats = None
    quantity = publication.get('admission_mode') == 'quantity'
    seat_map = None
    if selected and not quantity:
        inventory = MatchSeat.objects.filter(match=selected).select_related('seat__row__block').order_by(
            'seat__row__block__order', 'seat__row__block_id', 'seat__row__number', 'seat__number', 'pk')
        seats = Paginator(inventory, 60).get_page(request.GET.get('seat_page'))
        blocks = list(Block.objects.filter(stadium=selected.stadium, rows__seats__match_seats__match=selected).distinct().order_by('order', 'pk'))
        block_id = request.GET.get('map_block', '')
        block = next((item for item in blocks if str(item.pk) == block_id), blocks[0] if blocks else None)
        map_page = Paginator(inventory.filter(seat__row__block=block), 300).get_page(request.GET.get('map_page')) if block else None
        map_items = list(map_page) if map_page else []
        table_items = list(seats)
        snapshot = annotate_seats(selected, table_items + map_items)
        seats.object_list = [snapshot[item.pk] for item in table_items]
        map_items = [snapshot[item.pk] for item in map_items]
        plan = publication.get('seat_layout') or selected.stadium.seating_layout or {}
        section_plan = next((section for section in plan.get('sections', []) if block and section['name'] == block.name), None)
        seat_map = {'blocks': blocks, 'block': block, 'page': map_page, 'rows': map_rows(map_items, section_plan),
                    'details': map_details(map_items), 'stage': plan.get('stage', 'top'), 'direction': plan.get('direction', 'rtl')}
    params = request.GET.copy()
    params.pop('page', None)
    params.pop('seat_page', None)
    params.pop('map_page', None)
    return render(request, 'accounts/program_detail.html', {
        'program': program, 'event': event, 'sessions': sessions, 'selected_session': selected,
        'stats': stats, 'program_stats': program_stats, 'page_obj': page, 'seat_page': seats, 'seat_map': seat_map, 'query': query,
        'selected_status': status, 'filter_query': params.urlencode(), 'is_quantity': quantity,
        'review_groups': _review(program) if not event else [], 'submission': program, 'review_readonly': True,
    })
