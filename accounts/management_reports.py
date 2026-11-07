"""Shared read-only report filters, seat maps, and spreadsheet-safe exports."""
import csv
from datetime import datetime, time, timedelta
from decimal import Decimal
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import StreamingHttpResponse
from django.utils import timezone
from matches.models import MatchSeat, Block, get_active_block_ids, get_active_row_ids
from .management_forms import SalesFilterForm
from .program_seating import annotate_seats, map_rows, map_details


def enabled_inventory(session):
    return MatchSeat.objects.filter(match=session, is_enabled=True, seat__is_available=True,
        seat__row_id__in=get_active_row_ids(session), seat__row__block_id__in=get_active_block_ids(session))


def filter_sales(request, tickets, session=None):
    params = request.GET.copy()
    params.setdefault('status', 'all' if session else 'paid')
    form = SalesFilterForm(params)
    if session:
        form.fields.pop('event')
    if not form.is_valid():
        return form, tickets.none(), tickets.none()
    data = form.cleaned_data
    if data.get('event'):
        tickets = tickets.filter(match__event=data['event'])
    if data.get('start'):
        start = timezone.make_aware(datetime.combine(data['start'], time.min))
        tickets = tickets.filter(purchase_date__gte=start)
    if data.get('end'):
        end = timezone.make_aware(datetime.combine(data['end'] + timedelta(days=1), time.min))
        tickets = tickets.filter(purchase_date__lt=end)
    query = data.get('q', '').strip()
    if query:
        tickets = tickets.filter(Q(full_name__icontains=query) | Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) | Q(user__phone_number__icontains=query) |
            Q(ticket_number__icontains=query) | Q(match__event__title__icontains=query))
    # The paid total for the selected date/program remains meaningful when browsing pending tickets.
    summary = tickets
    if data.get('status') and data['status'] != 'all':
        tickets = tickets.filter(status=data['status'])
    return form, tickets, summary


def session_map(request, session, plan=None):
    inventory = MatchSeat.objects.filter(match=session).select_related('seat__row__block').order_by(
        'seat__row__block__order', 'seat__row__block_id', 'seat__row__number', 'seat__number', 'pk')
    blocks = list(Block.objects.filter(stadium=session.stadium, rows__seats__match_seats__match=session)
                  .distinct().order_by('order', 'pk'))
    block = next((item for item in blocks if str(item.pk) == request.GET.get('map_block')), blocks[0] if blocks else None)
    if not block:
        return None
    page = Paginator(inventory.filter(seat__row__block=block), 300).get_page(request.GET.get('map_page'))
    items = list(page)
    annotate_seats(session, items)
    plan = plan or session.stadium.seating_layout or {}
    section = next((item for item in plan.get('sections', []) if item['name'] == block.name), None)
    return {'blocks': blocks, 'block': block, 'page': page, 'rows': map_rows(items, section),
            'details': map_details(items), 'stage': plan.get('stage', 'top'), 'direction': plan.get('direction', 'rtl')}


def safe_cell(value):
    text = str(value if value is not None else '')
    # Neutralize spreadsheet formulas, including a leading whitespace disguise.
    if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


class CsvBuffer:
    def write(self, value):
        return value


def export_tickets(tickets):
    writer = csv.writer(CsvBuffer())

    def rows():
        yield '\ufeff'
        yield writer.writerow(['شماره بلیط', 'صاحب بلیط', 'خریدار', 'موبایل خریدار', 'برنامه', 'سالن',
            'تاریخ و ساعت سانس (میلادی)', 'بخش', 'ردیف', 'صندلی', 'مبلغ (تومان)', 'وضعیت',
            'ورود ثبت شده', 'تاریخ و ساعت خرید (میلادی)'])
        for ticket in tickets.iterator(chunk_size=500):
            seat = ticket.seat
            yield writer.writerow([safe_cell(value) for value in [ticket.ticket_number, ticket.full_name,
                ticket.user.get_full_name() or ticket.user.username, ticket.user.phone_number,
                ticket.match.display_title, ticket.match.stadium.name,
                timezone.localtime(ticket.match.date_time).strftime('%Y-%m-%d %H:%M'),
                seat.row.block.name if seat else '', seat.row.number if seat else '', seat.number if seat else '',
                format(ticket.price / Decimal(10), 'f') if ticket.price is not None else '',
                'تخصیص مدیریت (قدیمی)' if ticket.status == 'vip_issued' else ticket.get_status_display(), 'بله' if ticket.is_used else 'خیر',
                timezone.localtime(ticket.purchase_date).strftime('%Y-%m-%d %H:%M')]])

    response = StreamingHttpResponse(rows(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="didavar-sales.csv"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
