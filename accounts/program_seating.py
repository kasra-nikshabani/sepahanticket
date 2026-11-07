"""Read-only organizer seat status; both tables and maps share the same snapshot."""
from collections import defaultdict
from .venue_layout import curve_point, curve_padding
from django.utils import timezone
from matches.models import get_active_block_ids, get_active_row_ids
from tickets.models import Ticket
from tickets.reservation import SeatReservation
from .models import User

ISSUED = ('paid', 'admin_assigned', 'vip_issued')
LABELS = {'sold': 'پرداخت‌شده', 'complimentary': 'مهمان / تخصیصی', 'reserved': 'رزرو موقت',
          'disabled': 'غیرفعال', 'unavailable': 'خارج از دسترس', 'available': 'خالی'}


def annotate_seats(session, seats):
    items = list({item.pk: item for item in seats}.values())
    issued = defaultdict(list)
    for ticket in Ticket.objects.filter(match=session, seat_id__in=[item.seat_id for item in items],
                                        status__in=ISSUED).select_related('user').order_by('purchase_date', 'pk'):
        issued[ticket.seat_id].append(ticket)
    reservations = SeatReservation.get_reserved_map([item.pk for item in items])
    valid = {key: value for key, value in reservations.items() if isinstance(value, dict)
             and value.get('match_id') == session.pk and type(value.get('user_id')) is int}
    users = User.objects.in_bulk({value['user_id'] for value in valid.values()})
    active_blocks, active_rows = set(get_active_block_ids(session)), set(get_active_row_ids(session))
    now = timezone.now()
    for item in items:
        holders = issued[item.seat_id]
        item.holder = holders[-1] if holders else None
        reservation = valid.get(item.pk)
        item.reserver = users.get(reservation['user_id']) if reservation else None
        if holders:
            item.report_state = 'sold' if any(ticket.status == 'paid' for ticket in holders) else 'complimentary'
        elif not item.is_enabled or not item.seat.is_available or item.seat.row_id not in active_rows or item.seat.row.block_id not in active_blocks:
            item.report_state = 'disabled'
        elif (item.reserved_until and item.reserved_until > now) or reservation:
            item.report_state = 'reserved'
        elif not item.is_available:
            item.report_state = 'unavailable'
        else:
            item.report_state = 'available'
        item.report_label = LABELS[item.report_state]
        item.report_holder_name = '، '.join(ticket.full_name for ticket in holders)
        item.report_buyer_name = '، '.join(dict.fromkeys(ticket.user.get_full_name() or 'نام ثبت نشده' for ticket in holders))
        item.report_reserver_name = (item.reserver.get_full_name() or 'نام ثبت نشده') if item.reserver and item.report_state == 'reserved' else ''
        paid = [ticket for ticket in holders if ticket.status == 'paid']
        item.report_paid_amount = (sum(ticket.price for ticket in paid)
                                   if holders and all(ticket.price is not None for ticket in paid) else None)
        item.report_used = any(ticket.is_used for ticket in holders)
    return {item.pk: item for item in items}


def map_rows(items, section_plan=None):
    grouped = defaultdict(list)
    for item in items:
        grouped[item.seat.row.number].append(item)
    saved = {row['number']: row for row in (section_plan or {}).get('rows', [])}
    result = []
    for number, row_items in grouped.items():
        row_plan = saved.get(number, {})
        by_number = {item.seat.number: item for item in row_items}
        # A paginated row shows only the physical seats on this page, preserving internal aisles.
        positions = row_plan.get('seats') or list(by_number)
        curvature = row_plan.get('curvature', 0)
        original_positions = {position: index for index, position in enumerate(positions) if position is not None}
        count = len(positions)
        visible = [index for index, position in enumerate(positions) if position in by_number]
        if not all(position is None or position in by_number for position in positions):
            positions = positions[min(visible):max(visible) + 1] if visible else []
        cells, seen = [], set()
        for position in positions:
            item = by_number.get(position)
            if item:
                point = curve_point(curvature, original_positions[position], count)
                item.curve_y, item.curve_angle = point['y'], point['angle']
                cells.append(item); seen.add(item.seat.number)
            elif position is None:
                cells.append(None)
        for item in row_items:
            if item.seat.number not in seen:
                item.curve_y = item.curve_angle = 0
                cells.append(item)
        padding = curve_padding(curvature, count)
        result.append({'number': number, 'cells': cells, 'alignment': row_plan.get('alignment', 'center'),
                       'curve_top': padding['top'], 'curve_bottom': padding['bottom'],
                       'offset_pixels': row_plan.get('offset', 0) * 36})
    return result


def map_details(items):
    return {str(item.pk): {'number': item.seat.number, 'row': item.seat.row.number,
        'section': item.seat.row.block.name, 'state': item.report_state, 'label': item.report_label,
        'holder': item.report_holder_name, 'buyer': item.report_buyer_name,
        'reserver': item.report_reserver_name, 'amount': item.report_paid_amount, 'used': item.report_used,
        'expires': item.reserved_until.isoformat() if item.report_state == 'reserved' and item.reserved_until else None}
        for item in items}
