"""Organizer-owned ticket check-in for a single published event session."""
import json
import re

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from matches.models import Match, MatchSeat
from tickets.models import Ticket
from .models import EventSubmission
from .program_seating import annotate_seats, map_rows

VALID_TICKET_STATUSES = ('paid', 'admin_assigned', 'vip_issued')
_DIGIT_TRANSLATION = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def _owned_session(user, submission_id, session_id):
    program = get_object_or_404(
        EventSubmission.objects.select_related('published_event'),
        pk=submission_id, owner=user, published_event__isnull=False,
    )
    session = get_object_or_404(
        Match.objects.select_related('event', 'stadium'),
        pk=session_id, event_id=program.published_event_id,
    )
    return program, session


def _parse_ticket_code(raw):
    """Accept a typed number or the full QR payload printed on Didavar tickets."""
    value = (raw or '').strip().translate(_DIGIT_TRANSLATION)
    if not value or len(value) > 500:
        return None
    if re.fullmatch(r'[A-Za-z0-9-]{4,20}', value):
        return {'ticket_number': value}
    parts = {}
    for item in value.split('|'):
        key, sep, val = item.partition(':')
        if sep:
            parts[key.strip()] = val.strip().translate(_DIGIT_TRANSLATION)
    number = parts.get('Ticket', '')
    if not re.fullmatch(r'[A-Za-z0-9-]{4,20}', number):
        return None
    return {
        'ticket_number': number,
        'match_id': parts.get('Match'),
        'seat_id': parts.get('Seat'),
        'username': parts.get('User'),
    }


def _ticket_result(ticket, status, message, http_status=200):
    result = {'status': status, 'message': message}
    if ticket:
        result.update({
            'ticket_number': ticket.ticket_number,
            'holder': ticket.full_name,
            'used_at': timezone.localtime(ticket.used_at).strftime('%H:%M') if ticket.used_at else '',
            'seat': f'{ticket.seat.row.block.name} · ردیف {ticket.seat.row.number} · صندلی {ticket.seat.number}',
        })
        result['map_seat_id'] = MatchSeat.objects.filter(match=ticket.match, seat_id=ticket.seat_id).values_list('pk', flat=True).first() if ticket.seat_id else None
    return JsonResponse(result, status=http_status)


@login_required
@never_cache
@require_GET
def program_checkin(request, submission_id, session_id):
    program, session = _owned_session(request.user, submission_id, session_id)
    sessions = program.published_event.sessions.select_related('stadium').order_by('date_time', 'pk')
    inventory = list(session.match_seats.select_related('seat__row__block').order_by(
        'seat__row__block__order', 'seat__row__block_id', 'seat__row__number', 'seat__number', 'pk'))
    snapshot = annotate_seats(session, inventory)
    publication = program.data.get('publication_snapshot') or program.data
    plan = publication.get('seat_layout') or session.stadium.seating_layout or {}
    blocks = list(session.stadium.blocks.filter(rows__seats__match_seats__match=session)
                  .distinct().order_by('order', 'pk'))
    sections = []
    for block in blocks:
        items = [snapshot[item.pk] for item in inventory if item.seat.row.block_id == block.pk]
        section_plan = next((item for item in plan.get('sections', []) if item.get('name') == block.name), None)
        sections.append({'block': block, 'rows': map_rows(items, section_plan)})
    return render(request, 'accounts/program_checkin.html', {
        'program': program, 'event': program.published_event, 'session': session, 'sessions': sessions,
        'checkin_sections': sections, 'seat_count': len(inventory), 'map_stage': plan.get('stage', 'top'),
        'map_direction': plan.get('direction', 'rtl'),
        'scan_url': request.build_absolute_uri(reverse(
            'accounts:program_checkin_action', args=[program.pk, session.pk],
        )),
    })


@login_required
@never_cache
@require_POST
def program_checkin_action(request, submission_id, session_id):
    program, session = _owned_session(request.user, submission_id, session_id)
    try:
        if request.content_type == 'application/json':
            data = json.loads(request.body or '{}')
        else:
            data = request.POST
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'status': 'invalid', 'message': 'درخواست نامعتبر است.'}, status=400)

    if not hasattr(data, 'get'):
        return JsonResponse({'status': 'invalid', 'message': 'درخواست نامعتبر است.'}, status=400)
    code = _parse_ticket_code(data.get('ticket_code', ''))
    action = data.get('action', 'verify')
    if not code or action not in ('verify', 'check_in'):
        return JsonResponse({'status': 'invalid', 'message': 'شماره یا QR بلیط را بررسی کن.'}, status=400)
    if not program.published_event.is_active or not session.is_active or session.is_cancelled:
        return JsonResponse({'status': 'invalid', 'message': 'این برنامه یا سانس فعال نیست.'}, status=409)

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().select_related(
            'match__event', 'seat__row__block', 'user'
        ).filter(ticket_number=code['ticket_number'], match=session).first()
        if ticket is None:
            return _ticket_result(None, 'invalid', 'این بلیط برای سانس انتخاب‌شده معتبر نیست.', 404)
        if (code.get('match_id') and str(ticket.match_id) != code['match_id']
                or code.get('seat_id') and str(ticket.seat_id) != code['seat_id']
                or code.get('username') and ticket.user.username != code['username']):
            return _ticket_result(None, 'invalid', 'اطلاعات QR با بلیط این سانس مطابقت ندارد.', 400)
        if ticket.status not in VALID_TICKET_STATUSES:
            return _ticket_result(ticket, 'invalid', f'این بلیط قابل ورود نیست؛ وضعیت: {ticket.get_status_display()}.', 409)
        if ticket.is_used:
            return _ticket_result(ticket, 'used', 'ورود این بلیط قبلاً ثبت شده است.', 409)
        if action == 'verify':
            return _ticket_result(ticket, 'valid', 'بلیط معتبر است؛ برای ثبت ورود تأیید کن.')

        now = timezone.now()
        # The conditional update is atomic even on databases that do not support row locks.
        updated = Ticket.objects.filter(pk=ticket.pk, is_used=False, status__in=VALID_TICKET_STATUSES).update(
            is_used=True, used_at=now,
        )
        if not updated:
            ticket.refresh_from_db(fields=('is_used', 'used_at'))
            return _ticket_result(ticket, 'used', 'ورود این بلیط قبلاً ثبت شده است.', 409)
        ticket.is_used = True
        ticket.used_at = now
        return _ticket_result(ticket, 'checked_in', 'ورود با موفقیت ثبت شد.')
