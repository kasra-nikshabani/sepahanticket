import json
from datetime import timedelta
from sqlite3 import IntegrityError

from .forms import BlockForm, MatchForm, StadiumForm
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone

from tickets.models import Ticket
from tickets.reservation import SeatReservation
from .models import Match, Row, Seat, MatchSeat, Block, Stadium


# ============================================================
#  ویوهای عمومی (کاربران عادی)
# ============================================================

def home(request):
    """صفحه اصلی - نمایش مسابقات فعال با ظرفیت‌ها"""
    matches = Match.objects.filter(is_active=True, date_time__gte=timezone.now()).order_by('date_time')

    for match in matches:
        all_seats = Seat.objects.all()
        total_seats = all_seats.count()
        sold_seats = MatchSeat.objects.filter(match=match, is_available=False).count()
        seats_without_matchseat = all_seats.exclude(match_seats__match=match).count()
        available_seats = seats_without_matchseat + MatchSeat.objects.filter(
            match=match, is_available=True
        ).count()
        occupancy = round((sold_seats / total_seats * 100) if total_seats > 0 else 0, 1)

        match.total_capacity = total_seats
        match.sold_tickets = sold_seats
        match.available_seats = available_seats
        match.occupancy = occupancy

    return render(request, 'matches/home.html', {'matches': matches})


def match_detail(request, match_id):
    match = get_object_or_404(Match, id=match_id, is_active=True)
    return render(request, 'matches/match_detail.html', {'match': match})


# ============================================================
#  مراحل خرید بلیط (کاربران عادی)
# ============================================================

@login_required
def select_floor(request, match_id):
    """انتخاب طبقه (پایین یا بالا) قبل از نمایش بلوک‌ها"""
    match = get_object_or_404(Match, id=match_id, is_active=True)

    if request.method == 'POST':
        floor = request.POST.get('floor')
        if floor in ['ground', 'second']:
            request.session['selected_floor'] = floor
            return redirect('matches:select_block', match_id=match_id)
        else:
            messages.error(request, 'لطفاً یک طبقه را انتخاب کنید.')

    return render(request, 'matches/select_floor.html', {'match': match})


@login_required
def select_block(request, match_id):
    match = get_object_or_404(Match, id=match_id, is_active=True)
    stadium = match.stadium  # ورزشگاه مسابقه

    # ===== دریافت طبقه انتخاب‌شده از session =====
    selected_floor = request.session.get('selected_floor', 'ground')

    # ===== فیلتر بلوک‌ها بر اساس ورزشگاه و طبقه =====
    if selected_floor == 'second':
        blocks = Block.objects.filter(
            stadium=stadium,
            is_active=True,
            name__contains='طبقه دوم'
        ).order_by('order')
    else:
        blocks = Block.objects.filter(
            stadium=stadium,
            is_active=True
        ).exclude(name__contains='طبقه دوم').order_by('order')

    # ===== اگر هیچ بلوکی وجود نداشت =====
    if not blocks.exists():
        messages.warning(
            request,
            f'هیچ بلوکی برای ورزشگاه "{stadium.name}" در طبقه {"بالا" if selected_floor == "second" else "پایین"} تعریف نشده است.'
        )
        return redirect('matches:select_floor', match_id=match_id)

    # ===== نگاشت zone_type به برچسب فارسی =====
    zone_labels = {
        'home': ('home', 'میزبان'),
        'away': ('away', 'میهمان'),
        'class1': ('class1', 'کلاس ۱'),
        'women': ('women', 'بانوان'),
        'vip': ('vip', 'VIP'),
    }

    # ===== محاسبه آمار برای هر بلوک =====
    for block in blocks:
        # تعداد کل صندلی‌های این بلوک
        total_seats = Seat.objects.filter(row__block=block).count()
        block.total_seats = total_seats

        # تعداد صندلی‌های موجود (آزاد) برای این مسابقه در این بلوک
        # ۱. صندلی‌هایی که MatchSeat دارند و available هستند
        available_with_matchseat = MatchSeat.objects.filter(
            match=match,
            seat__row__block=block,
            is_available=True
        ).count()

        # ۲. صندلی‌هایی که اصلاً MatchSeat ندارند (هنوز برای این مسابقه ایجاد نشده‌اند) -> به‌طور پیش‌فرض آزاد در نظر گرفته می‌شوند
        seats_without_matchseat = Seat.objects.filter(
            row__block=block
        ).exclude(match_seats__match=match).count()

        available_seats = available_with_matchseat + seats_without_matchseat
        block.available_seats = available_seats

        # درصد اشغال
        block.occupancy = round(
            ((total_seats - available_seats) / total_seats * 100) if total_seats > 0 else 0,
            1
        )

        # ===== تعیین نوع جایگاه بر اساس zone_type =====
        zone_type = block.zone_type
        if zone_type in zone_labels:
            block.team_type, block.team_type_label = zone_labels[zone_type]
        else:
            block.team_type, block.team_type_label = ('home', 'میزبان')

    # ===== پردازش انتخاب بلوک (POST) =====
    if request.method == 'POST':
        block_id = request.POST.get('block_id')
        if block_id:
            block = get_object_or_404(Block, id=block_id)

            # بررسی وجود صندلی در بلوک
            if Seat.objects.filter(row__block=block).count() == 0:
                messages.error(
                    request,
                    f'بلوک "{block.name}" هیچ صندلی‌ای ندارد! لطفاً با مدیر تماس بگیرید.'
                )
                return redirect('matches:select_block', match_id=match_id)

            # ذخیره بلوک انتخاب‌شده در session
            request.session['selected_block_id'] = block_id
            return redirect('matches:block_map', match_id=match_id)
        else:
            messages.error(request, 'لطفاً یک بلوک را انتخاب کنید.')

    # ===== رندر صفحه =====
    context = {
        'match': match,
        'blocks': blocks,
        'selected_floor': selected_floor,
        'floor_label': 'طبقه بالا' if selected_floor == 'second' else 'طبقه پایین',
    }
    return render(request, 'matches/select_block.html', context)


@login_required
def show_block_map(request, match_id):
    match = get_object_or_404(Match, id=match_id, is_active=True)
    block_id = request.session.get('selected_block_id')
    if not block_id:
        messages.error(request, 'لطفاً ابتدا یک بلوک را انتخاب کنید.')
        return redirect('matches:select_block', match_id=match_id)

    block = get_object_or_404(Block, id=block_id)
    rows = Row.objects.filter(block=block, is_active=True).order_by('number')

    map_data = []
    first_row_id = None

    for row in rows:
        seats = Seat.objects.filter(row=row).order_by('number')
        if not seats.exists():
            continue

        if first_row_id is None:
            first_row_id = row.id

        seat_list = []
        for seat in seats:
            match_seat, _ = MatchSeat.objects.get_or_create(
                match=match,
                seat=seat,
                defaults={'is_available': True}
            )
            seat_list.append({
                'number': seat.number,
                'is_available': match_seat.is_available,
                'id': match_seat.id,
            })
        map_data.append({
            'row_number': row.number,
            'seats': seat_list,
        })

    if not map_data:
        messages.warning(request, f'هیچ صندلی‌ای برای بلوک "{block.name}" یافت نشد.')
        return redirect('matches:select_block', match_id=match_id)

    context = {
        'match': match,
        'block': block,
        'map_data': map_data,
        'first_row_id': first_row_id,
    }
    return render(request, 'matches/block_map.html', context)


@login_required
def select_row(request, match_id):
    match = get_object_or_404(Match, id=match_id, is_active=True)
    block_id = request.session.get('selected_block_id')
    if not block_id:
        messages.error(request, 'لطفاً ابتدا بلوک را انتخاب کنید.')
        return redirect('matches:select_block', match_id=match_id)

    block = get_object_or_404(Block, id=block_id)
    rows = Row.objects.filter(block=block, is_active=True).order_by('number')

    if request.method == 'POST':
        row_id = request.POST.get('row_id')
        if row_id:
            request.session['selected_row_id'] = row_id
            return redirect('matches:select_seats', match_id=match_id)
        else:
            messages.error(request, 'لطفاً یک ردیف را انتخاب کنید.')

    return render(request, 'matches/select_row.html', {
        'match': match,
        'block': block,
        'rows': rows,
    })


# ============================================================
#  ویوهای مدیریتی (ادمین)
# ============================================================

@staff_member_required
def manage_rows(request):
    """مدیریت بلوک‌ها برای یک مسابقه خاص (جایگزین مدیریت ردیف‌ها)"""
    match_id = request.GET.get('match_id')
    matches = Match.objects.filter(is_active=True).order_by('-date_time')

    # دریافت همه بلوک‌های فعال به ترتیب
    blocks = Block.objects.filter(is_active=True).order_by('order')

    if not match_id and matches.exists():
        match_id = matches.first().id

    match = None
    block_status = []
    if match_id:
        match = get_object_or_404(Match, id=match_id)
        for block in blocks:
            match_seats = MatchSeat.objects.filter(match=match, seat__row__block=block)
            total = match_seats.count()
            available = match_seats.filter(is_available=True).count()
            status = 'no_seats' if total == 0 else (
                'active' if available == total else ('inactive' if available == 0 else 'partial'))
            block_status.append({
                'block': block,
                'total': total,
                'available': available,
                'status': status,
            })

    if request.method == 'POST':
        action = request.POST.get('action')
        block_id = request.POST.get('block_id')
        match_id_post = request.POST.get('match_id')

        if not block_id or not match_id_post or not action:
            messages.error(request, 'اطلاعات ناقص.')
            return redirect('matches:manage_rows')

        match = get_object_or_404(Match, id=match_id_post)
        block = get_object_or_404(Block, id=block_id)
        seats_in_block = Seat.objects.filter(row__block=block)

        with transaction.atomic():
            if action == 'activate':
                existing = MatchSeat.objects.filter(match=match, seat__in=seats_in_block)
                existing_seat_ids = existing.values_list('seat_id', flat=True)
                missing_seat_ids = seats_in_block.exclude(id__in=existing_seat_ids).values_list('id', flat=True)
                new_seats = [MatchSeat(match=match, seat_id=sid, is_available=True) for sid in missing_seat_ids]
                if new_seats:
                    MatchSeat.objects.bulk_create(new_seats)
                    messages.info(request, f'{len(new_seats)} صندلی جدید برای این مسابقه ایجاد شد.')

                activated = 0
                for ms in MatchSeat.objects.filter(match=match, seat__in=seats_in_block, is_available=False):
                    has_ticket = Ticket.objects.filter(
                        match_seat=ms,
                        status__in=['paid', 'admin_assigned', 'vip_issued']
                    ).exists()
                    if not has_ticket:
                        ms.is_available = True
                        ms.save()
                        activated += 1
                messages.success(request, f'{activated} صندلی از بلوک "{block.name}" فعال شدند.')

            elif action == 'deactivate':
                existing = MatchSeat.objects.filter(match=match, seat__in=seats_in_block)
                existing_seat_ids = existing.values_list('seat_id', flat=True)
                missing_seat_ids = seats_in_block.exclude(id__in=existing_seat_ids).values_list('id', flat=True)
                new_seats = [MatchSeat(match=match, seat_id=sid, is_available=False) for sid in missing_seat_ids]
                if new_seats:
                    MatchSeat.objects.bulk_create(new_seats)
                    messages.info(request, f'{len(new_seats)} صندلی جدید برای این مسابقه ایجاد شد.')

                MatchSeat.objects.filter(match=match, seat__in=seats_in_block).update(is_available=False)

                tickets = Ticket.objects.filter(
                    match_seat__match=match,
                    match_seat__seat__in=seats_in_block,
                    status__in=['paid', 'admin_assigned', 'vip_issued']
                )
                cancelled = tickets.count()
                if cancelled > 0:
                    tickets.update(status='cancelled')
                    messages.warning(request, f'{cancelled} بلیط موجود در بلوک "{block.name}" لغو شدند.')

                messages.success(request, f'بلوک "{block.name}" برای این مسابقه غیرفعال شد.')

        return redirect(f'{request.path}?match_id={match_id_post}')

    context = {
        'matches': matches,
        'block_status': block_status,  # تغییر نام به block_status
        'selected_match_id': int(match_id) if match_id else None,
        'selected_match': match,
    }
    return render(request, 'matches/manage_rows.html', context)


@staff_member_required
def manage_blocks(request):
    """مدیریت بلوک‌ها برای یک مسابقه خاص"""
    match_id = request.GET.get('match_id')
    matches = Match.objects.filter(is_active=True).order_by('-date_time')
    blocks = Block.objects.filter(is_active=True).order_by('order')

    if not match_id and matches.exists():
        match_id = matches.first().id

    match = None
    block_status = []

    if match_id:
        match = get_object_or_404(Match, id=match_id)
        for block in blocks:
            match_seats = MatchSeat.objects.filter(match=match, seat__row__block=block)
            total = match_seats.count()
            available = match_seats.filter(is_available=True).count()
            occupied = total - available
            occupancy_percent = round((occupied / total * 100) if total > 0 else 0, 1)

            status = 'no_seats' if total == 0 else (
                'active' if available == total else ('inactive' if available == 0 else 'partial')
            )
            block_status.append({
                'block': block,
                'total': total,
                'available': available,
                'occupied': occupied,
                'occupancy_percent': occupancy_percent,
                'status': status,
            })

    # ===== محاسبه آمار وضعیت‌ها =====
    active_count = sum(1 for item in block_status if item['status'] == 'active')
    inactive_count = sum(1 for item in block_status if item['status'] == 'inactive')
    partial_count = sum(1 for item in block_status if item['status'] == 'partial')
    no_seats_count = sum(1 for item in block_status if item['status'] == 'no_seats')

    # ===== پردازش درخواست POST =====
    if request.method == 'POST':
        action = request.POST.get('action')
        block_id = request.POST.get('block_id')
        match_id_post = request.POST.get('match_id')

        if not block_id or not match_id_post or not action:
            messages.error(request, 'اطلاعات ناقص.')
            return redirect('matches:manage_blocks')

        match = get_object_or_404(Match, id=match_id_post)
        block = get_object_or_404(Block, id=block_id)
        seats_in_block = Seat.objects.filter(row__block=block)

        with transaction.atomic():
            if action == 'activate':
                existing = MatchSeat.objects.filter(match=match, seat__in=seats_in_block)
                existing_seat_ids = existing.values_list('seat_id', flat=True)
                missing_seat_ids = seats_in_block.exclude(id__in=existing_seat_ids).values_list('id', flat=True)
                new_seats = [MatchSeat(match=match, seat_id=sid, is_available=True) for sid in missing_seat_ids]
                if new_seats:
                    MatchSeat.objects.bulk_create(new_seats)
                    messages.info(request, f'{len(new_seats)} صندلی جدید برای این مسابقه ایجاد شد.')

                activated = 0
                for ms in MatchSeat.objects.filter(match=match, seat__in=seats_in_block, is_available=False):
                    has_ticket = Ticket.objects.filter(
                        match_seat=ms,
                        status__in=['paid', 'admin_assigned', 'vip_issued']
                    ).exists()
                    if not has_ticket:
                        ms.is_available = True
                        ms.save()
                        activated += 1
                messages.success(request, f'{activated} صندلی از بلوک "{block.name}" فعال شدند.')

            elif action == 'deactivate':
                existing = MatchSeat.objects.filter(match=match, seat__in=seats_in_block)
                existing_seat_ids = existing.values_list('seat_id', flat=True)
                missing_seat_ids = seats_in_block.exclude(id__in=existing_seat_ids).values_list('id', flat=True)
                new_seats = [MatchSeat(match=match, seat_id=sid, is_available=False) for sid in missing_seat_ids]
                if new_seats:
                    MatchSeat.objects.bulk_create(new_seats)
                    messages.info(request, f'{len(new_seats)} صندلی جدید برای این مسابقه ایجاد شد.')

                MatchSeat.objects.filter(match=match, seat__in=seats_in_block).update(is_available=False)

                tickets = Ticket.objects.filter(
                    match_seat__match=match,
                    match_seat__seat__in=seats_in_block,
                    status__in=['paid', 'admin_assigned', 'vip_issued']
                )
                cancelled = tickets.count()
                if cancelled > 0:
                    tickets.update(status='cancelled')
                    messages.warning(request, f'{cancelled} بلیط موجود در بلوک "{block.name}" لغو شدند.')

                messages.success(request, f'بلوک "{block.name}" برای این مسابقه غیرفعال شد.')

        return redirect(f'{request.path}?match_id={match_id_post}')

    # ===== کانتکست نهایی =====
    context = {
        'matches': matches,
        'block_status': block_status,
        'selected_match_id': int(match_id) if match_id else None,
        'selected_match': match,
        'active_count': active_count,
        'inactive_count': inactive_count,
        'partial_count': partial_count,
        'no_seats_count': no_seats_count,
    }
    return render(request, 'matches/manage_blocks.html', context)


@staff_member_required
def manage_seats(request, row_id):
    """مدیریت صندلی‌های یک ردیف برای یک مسابقه خاص"""
    match_id = request.GET.get('match_id')
    if not match_id:
        messages.error(request, 'لطفاً یک مسابقه را انتخاب کنید.')
        return redirect('matches:manage_rows')

    match = get_object_or_404(Match, id=match_id)
    row = get_object_or_404(Row, id=row_id)

    all_seats = Seat.objects.filter(row=row).order_by('number')
    match_seats = MatchSeat.objects.filter(match=match, seat__in=all_seats).select_related('seat')
    match_seat_dict = {ms.seat_id: ms for ms in match_seats}

    seats_data = []
    for seat in all_seats:
        ms = match_seat_dict.get(seat.id)
        if ms:
            has_ticket = Ticket.objects.filter(
                match_seat=ms,
                status__in=['paid', 'admin_assigned', 'vip_issued']
            ).exists()
            seats_data.append({
                'seat': seat,
                'match_seat': ms,
                'is_available': ms.is_available,
                'has_ticket': has_ticket,
            })
        else:
            seats_data.append({
                'seat': seat,
                'match_seat': None,
                'is_available': False,
                'has_ticket': False,
            })

    total = len(seats_data)
    available = sum(1 for s in seats_data if s['is_available'])
    unavailable = total - available

    if request.method == 'POST':
        action = request.POST.get('action')
        selected_seats_data = request.POST.get('selected_seats')

        if action == 'activate_selected' and selected_seats_data:
            try:
                seat_ids = json.loads(selected_seats_data)
            except json.JSONDecodeError:
                messages.error(request, 'خطا در اطلاعات ارسال شده.')
                return redirect(f'{request.path}?match_id={match_id}')

            if not seat_ids:
                messages.warning(request, 'هیچ صندلی انتخاب نشده است.')
                return redirect(f'{request.path}?match_id={match_id}')

            with transaction.atomic():
                activated = 0
                for seat_id in seat_ids:
                    ms = match_seat_dict.get(seat_id)
                    if ms and not ms.is_available:
                        has_ticket = Ticket.objects.filter(
                            match_seat=ms,
                            status__in=['paid', 'admin_assigned', 'vip_issued']
                        ).exists()
                        if not has_ticket:
                            ms.is_available = True
                            ms.save()
                            activated += 1
                messages.success(request, f'{activated} صندلی با موفقیت فعال شدند.')
            return redirect(f'{request.path}?match_id={match_id}')

        elif action == 'deactivate_selected' and selected_seats_data:
            try:
                seat_ids = json.loads(selected_seats_data)
            except json.JSONDecodeError:
                messages.error(request, 'خطا در اطلاعات ارسال شده.')
                return redirect(f'{request.path}?match_id={match_id}')

            if not seat_ids:
                messages.warning(request, 'هیچ صندلی انتخاب نشده است.')
                return redirect(f'{request.path}?match_id={match_id}')

            with transaction.atomic():
                deactivated = 0
                cancelled = 0
                for seat_id in seat_ids:
                    ms = match_seat_dict.get(seat_id)
                    if ms and ms.is_available:
                        ms.is_available = False
                        ms.save()
                        deactivated += 1
                        tickets = Ticket.objects.filter(
                            match_seat=ms,
                            status__in=['paid', 'admin_assigned', 'vip_issued']
                        )
                        if tickets.exists():
                            cancelled += tickets.count()
                            tickets.update(status='cancelled')
                messages.success(request, f'{deactivated} صندلی غیرفعال شدند و {cancelled} بلیط لغو شدند.')
            return redirect(f'{request.path}?match_id={match_id}')

        elif action == 'activate_gradual':
            count = int(request.POST.get('count', 10))
            if count <= 0:
                messages.error(request, 'تعداد باید بزرگتر از صفر باشد.')
                return redirect(f'{request.path}?match_id={match_id}')

            inactive_seat_ids = [
                s['seat'].id for s in seats_data
                if not s['is_available'] and not s['has_ticket']
            ]
            ids_to_activate = inactive_seat_ids[:count]
            if ids_to_activate:
                MatchSeat.objects.filter(id__in=ids_to_activate).update(is_available=True)
                messages.success(request, f'{len(ids_to_activate)} صندلی با موفقیت فعال شدند.')
            else:
                messages.info(request, 'هیچ صندلی غیرفعالی برای فعال‌سازی وجود ندارد.')
            return redirect(f'{request.path}?match_id={match_id}')

        elif action == 'activate_all':
            with transaction.atomic():
                inactive_seat_ids = [
                    s['seat'].id for s in seats_data
                    if not s['is_available'] and not s['has_ticket']
                ]
                if inactive_seat_ids:
                    MatchSeat.objects.filter(id__in=inactive_seat_ids).update(is_available=True)
                    messages.success(request, f'{len(inactive_seat_ids)} صندلی با موفقیت فعال شدند.')
                else:
                    messages.info(request, 'هیچ صندلی قابل فعال‌سازی وجود ندارد.')
            return redirect(f'{request.path}?match_id={match_id}')

        elif action == 'deactivate_all':
            with transaction.atomic():
                active_seat_ids = [
                    s['seat'].id for s in seats_data
                    if s['is_available']
                ]
                if active_seat_ids:
                    cancelled = 0
                    for seat_id in active_seat_ids:
                        ms = match_seat_dict.get(seat_id)
                        if ms:
                            ms.is_available = False
                            ms.save()
                            tickets = Ticket.objects.filter(
                                match_seat=ms,
                                status__in=['paid', 'admin_assigned', 'vip_issued']
                            )
                            if tickets.exists():
                                cancelled += tickets.count()
                                tickets.update(status='cancelled')
                    messages.success(request, f'{len(active_seat_ids)} صندلی غیرفعال شدند و {cancelled} بلیط لغو شدند.')
                else:
                    messages.info(request, 'هیچ صندلی فعالی برای غیرفعال‌سازی وجود ندارد.')
            return redirect(f'{request.path}?match_id={match_id}')

    context = {
        'row': row,
        'match': match,
        'seats_data': seats_data,
        'total': total,
        'available': available,
        'unavailable': unavailable,
    }
    return render(request, 'matches/manage_seats.html', context)


# ============================================================
#  ویوهای API
# ============================================================
@staff_member_required
def manage_block_seats(request, block_id):
    """مدیریت تمام صندلی‌های یک بلوک (همه ردیف‌ها) برای یک مسابقه خاص"""
    match_id = request.GET.get('match_id')
    if not match_id:
        messages.error(request, 'لطفاً یک مسابقه را انتخاب کنید.')
        return redirect('matches:manage_rows')

    match = get_object_or_404(Match, id=match_id)
    block = get_object_or_404(Block, id=block_id)

    # دریافت همه صندلی‌های بلوک
    all_seats = Seat.objects.filter(row__block=block).order_by('row__number', 'number')
    match_seats = MatchSeat.objects.filter(match=match, seat__in=all_seats).select_related('seat')
    match_seat_dict = {ms.seat_id: ms for ms in match_seats}

    seats_data = []
    for seat in all_seats:
        ms = match_seat_dict.get(seat.id)
        if ms:
            has_ticket = Ticket.objects.filter(
                match_seat=ms,
                status__in=['paid', 'admin_assigned', 'vip_issued']
            ).exists()
            seats_data.append({
                'seat': seat,
                'match_seat': ms,
                'is_available': ms.is_available,
                'has_ticket': has_ticket,
                'row_number': seat.row.number,
            })
        else:
            seats_data.append({
                'seat': seat,
                'match_seat': None,
                'is_available': False,
                'has_ticket': False,
                'row_number': seat.row.number,
            })

    total = len(seats_data)
    available = sum(1 for s in seats_data if s['is_available'])
    unavailable = total - available

    if request.method == 'POST':
        action = request.POST.get('action')
        selected_seats_data = request.POST.get('selected_seats')

        # فعال‌سازی انتخاب‌شده‌ها
        if action == 'activate_selected' and selected_seats_data:
            try:
                seat_ids = json.loads(selected_seats_data)
            except json.JSONDecodeError:
                messages.error(request, 'خطا در اطلاعات ارسال شده.')
                return redirect(f'{request.path}?match_id={match_id}')

            if not seat_ids:
                messages.warning(request, 'هیچ صندلی انتخاب نشده است.')
                return redirect(f'{request.path}?match_id={match_id}')

            with transaction.atomic():
                activated = 0
                for seat_id in seat_ids:
                    ms = match_seat_dict.get(seat_id)
                    if ms:
                        if not ms.is_available:
                            has_ticket = Ticket.objects.filter(
                                match_seat=ms,
                                status__in=['paid', 'admin_assigned', 'vip_issued']
                            ).exists()
                            if not has_ticket:
                                ms.is_available = True
                                ms.save()
                                activated += 1
                    else:
                        seat = get_object_or_404(Seat, id=seat_id)
                        MatchSeat.objects.create(match=match, seat=seat, is_available=True)
                        activated += 1
                        match_seat_dict[seat_id] = MatchSeat.objects.get(match=match, seat=seat)
                messages.success(request, f'{activated} صندلی با موفقیت فعال شدند.')
            return redirect(f'{request.path}?match_id={match_id}')

        # غیرفعال‌سازی انتخاب‌شده‌ها
        elif action == 'deactivate_selected' and selected_seats_data:
            try:
                seat_ids = json.loads(selected_seats_data)
            except json.JSONDecodeError:
                messages.error(request, 'خطا در اطلاعات ارسال شده.')
                return redirect(f'{request.path}?match_id={match_id}')

            if not seat_ids:
                messages.warning(request, 'هیچ صندلی انتخاب نشده است.')
                return redirect(f'{request.path}?match_id={match_id}')

            with transaction.atomic():
                deactivated = 0
                cancelled = 0
                for seat_id in seat_ids:
                    ms = match_seat_dict.get(seat_id)
                    if ms:
                        if ms.is_available:
                            ms.is_available = False
                            ms.save()
                            deactivated += 1
                            tickets = Ticket.objects.filter(
                                match_seat=ms,
                                status__in=['paid', 'admin_assigned', 'vip_issued']
                            )
                            if tickets.exists():
                                cancelled += tickets.count()
                                tickets.update(status='cancelled')
                    else:
                        seat = get_object_or_404(Seat, id=seat_id)
                        MatchSeat.objects.create(match=match, seat=seat, is_available=False)
                        deactivated += 1
                        match_seat_dict[seat_id] = MatchSeat.objects.get(match=match, seat=seat)
                messages.success(request, f'{deactivated} صندلی غیرفعال شدند و {cancelled} بلیط لغو شدند.')
            return redirect(f'{request.path}?match_id={match_id}')

        # فعال‌سازی همه
        elif action == 'activate_all':
            with transaction.atomic():
                to_activate = []
                for seat_data in seats_data:
                    if not seat_data['has_ticket'] and not seat_data['is_available']:
                        to_activate.append(seat_data['seat'])
                activated = 0
                for seat in to_activate:
                    ms = match_seat_dict.get(seat.id)
                    if ms:
                        has_ticket = Ticket.objects.filter(
                            match_seat=ms,
                            status__in=['paid', 'admin_assigned', 'vip_issued']
                        ).exists()
                        if not has_ticket:
                            ms.is_available = True
                            ms.save()
                            activated += 1
                    else:
                        MatchSeat.objects.create(match=match, seat=seat, is_available=True)
                        activated += 1
                messages.success(request, f'{activated} صندلی با موفقیت فعال شدند.')
            return redirect(f'{request.path}?match_id={match_id}')

        # غیرفعال‌سازی همه
        elif action == 'deactivate_all':
            with transaction.atomic():
                deactivated = 0
                cancelled = 0
                for seat_data in seats_data:
                    seat = seat_data['seat']
                    ms = match_seat_dict.get(seat.id)
                    if ms:
                        if ms.is_available:
                            ms.is_available = False
                            ms.save()
                            deactivated += 1
                            tickets = Ticket.objects.filter(
                                match_seat=ms,
                                status__in=['paid', 'admin_assigned', 'vip_issued']
                            )
                            if tickets.exists():
                                cancelled += tickets.count()
                                tickets.update(status='cancelled')
                    else:
                        MatchSeat.objects.create(match=match, seat=seat, is_available=False)
                        deactivated += 1
                messages.success(request, f'{deactivated} صندلی غیرفعال شدند و {cancelled} بلیط لغو شدند.')
            return redirect(f'{request.path}?match_id={match_id}')

    context = {
        'block': block,
        'match': match,
        'seats_data': seats_data,
        'total': total,
        'available': available,
        'unavailable': unavailable,
    }
    return render(request, 'matches/manage_seats.html', context)


# ============================================================
#  ویوهای API
# ============================================================

def get_seats_status(request, match_id):
    """دریافت وضعیت لحظه‌ای صندلی‌های یک مسابقه با وضعیت رزرو"""
    match = get_object_or_404(Match, id=match_id, is_active=True)
    row_id = request.GET.get('row_id')
    if not row_id:
        return JsonResponse({'error': 'row_id required'}, status=400)

    match_seats = MatchSeat.objects.filter(
        match=match,
        seat__row_id=row_id
    ).select_related('seat').order_by('seat__number')

    data = {'seats': []}

    for ms in match_seats:
        seat_info = {
            'id': ms.id,
            'number': ms.seat.number,
            'is_available': ms.is_available,
            'is_reserved': False,
            'reserved_by_me': False,
        }

        reservation = SeatReservation.get_reservation(ms.id)
        if reservation:
            seat_info['is_reserved'] = True
            if request.user.is_authenticated and reservation.get('user_id') == request.user.id:
                seat_info['reserved_by_me'] = True

        data['seats'].append(seat_info)

    return JsonResponse(data)


@staff_member_required
def admin_match_list(request):
    """صفحه مدیریت مسابقات برای ادمین"""
    match_id = request.GET.get('match_id')
    page = request.GET.get('page', 1)

    # دریافت مسابقات
    matches = Match.objects.all().order_by('-date_time')

    # فیلتر بر اساس match_id (اگر انتخاب شده باشد)
    if match_id:
        matches = matches.filter(id=match_id)

    # محاسبه آمار
    match_data = []
    for match in matches:
        sold_tickets = Ticket.objects.filter(match=match, status='paid')
        vip_tickets = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued'])

        sold_revenue = sum(
            t.seat.row.block.price for t in sold_tickets
            if t.seat and t.seat.row and t.seat.row.block
        )
        vip_revenue = sum(
            t.seat.row.block.price for t in vip_tickets
            if t.seat and t.seat.row and t.seat.row.block
        )
        occupied_seats = MatchSeat.objects.filter(match=match, is_available=False).count()
        total_seats = Seat.objects.count()

        match_data.append({
            'match': match,
            'sold_count': sold_tickets.count(),
            'vip_count': vip_tickets.count(),
            'total_revenue': sold_revenue + vip_revenue,
            'occupied_seats': occupied_seats,
            'total_seats': total_seats,
            'occupancy_percent': round((occupied_seats / total_seats * 100) if total_seats > 0 else 0, 1),
        })

    # صفحه‌بندی
    paginator = Paginator(match_data, 10)
    try:
        page_obj = paginator.page(page)
    except:
        page_obj = paginator.page(1)

    # لیست همه مسابقات برای dropdown
    all_matches = Match.objects.all().order_by('-date_time')

    context = {
        'page_obj': page_obj,
        'selected_match_id': int(match_id) if match_id else None,
        'all_matches': all_matches,
        'total_matches': matches.count(),
        'total_revenue_all': sum(item['total_revenue'] for item in match_data),
        'total_sold_all': sum(item['sold_count'] for item in match_data),
        'total_vip_all': sum(item['vip_count'] for item in match_data),
    }
    return render(request, 'matches/admin_match_list.html', context)


@staff_member_required
def admin_match_detail(request, match_id):
    """صفحه جزئیات مسابقه برای ادمین (مشابه پنل ادمین)"""
    match = get_object_or_404(Match, id=match_id)

    # دریافت بلیط‌ها بر اساس وضعیت
    sold_tickets_qs = Ticket.objects.filter(match=match, status='paid').order_by('-purchase_date')
    vip_tickets_qs = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued']).order_by(
        '-purchase_date')

    # محاسبه درآمد
    sold_total = sum(
        t.seat.row.block.price for t in sold_tickets_qs
        if t.seat and t.seat.row and t.seat.row.block
    )
    vip_total = sum(
        t.seat.row.block.price for t in vip_tickets_qs
        if t.seat and t.seat.row and t.seat.row.block
    )

    # صفحه‌بندی برای بلیط‌های فروخته‌شده
    per_page = 10
    sold_page_num = request.GET.get('sold_page', 1)
    vip_page_num = request.GET.get('vip_page', 1)

    sold_paginator = Paginator(sold_tickets_qs, per_page)
    sold_page = sold_paginator.get_page(sold_page_num)
    used_tickets = Ticket.objects.filter(match=match, is_used=True).count()
    not_used_tickets = Ticket.objects.filter(match=match, is_used=False,
                                             status__in=['paid', 'admin_assigned', 'vip_issued']).count()

    vip_paginator = Paginator(vip_tickets_qs, per_page)
    vip_page = vip_paginator.get_page(vip_page_num)

    # آمار صندلی‌ها
    match_seats = MatchSeat.objects.filter(match=match)
    total_match_seats = match_seats.count()
    occupied = match_seats.filter(is_available=False).count()
    available = match_seats.filter(is_available=True).count()

    # آمار بلوک‌ها
    blocks = Block.objects.filter(is_active=True).order_by('order')
    block_stats = []
    for block in blocks:
        block_seats = MatchSeat.objects.filter(match=match, seat__row__block=block)
        block_total = block_seats.count()
        block_occupied = block_seats.filter(is_available=False).count()
        block_available = block_total - block_occupied
        block_stats.append({
            'block': block,
            'total': block_total,
            'occupied': block_occupied,
            'available': block_available,
            'occupancy': round((block_occupied / block_total * 100) if block_total > 0 else 0, 1),
        })

    context = {
        'match': match,
        'sold_page': sold_page,
        'vip_page': vip_page,
        'sold_total': sold_total,
        'vip_total': vip_total,
        'total_revenue': sold_total + vip_total,
        'sold_count': sold_tickets_qs.count(),
        'vip_count': vip_tickets_qs.count(),
        'total_tickets': sold_tickets_qs.count() + vip_tickets_qs.count(),
        'total_match_seats': total_match_seats,
        'occupied': occupied,
        'available': available,
        'occupancy_percent': round((occupied / total_match_seats * 100) if total_match_seats > 0 else 0, 1),
        'block_stats': block_stats,
        'current_sold_page': sold_page.number,
        'current_vip_page': vip_page.number,
        'sold_page_range': sold_paginator.page_range,
        'vip_page_range': vip_paginator.page_range,
        'used_tickets': used_tickets,
        'not_used_tickets': not_used_tickets,
    }
    return render(request, 'matches/admin_match_detail.html', context)


# ============================================================
#  مدیریت بلوک‌ها (فقط ادمین)
# ============================================================

@staff_member_required
def admin_block_list(request):
    """مدیریت بلوک‌ها با قابلیت انتخاب ورزشگاه"""
    stadium_id = request.GET.get('stadium_id')
    selected_stadium = None
    blocks = Block.objects.filter(is_active=True).order_by('order')

    if stadium_id:
        selected_stadium = get_object_or_404(Stadium, id=stadium_id)
        blocks = blocks.filter(stadium=selected_stadium)

    stadiums = Stadium.objects.all().order_by('name')

    context = {
        'blocks': blocks,
        'stadiums': stadiums,
        'selected_stadium': selected_stadium,
    }
    return render(request, 'matches/admin_block_list.html', context)


@staff_member_required
def admin_block_edit(request, block_id=None):
    """ایجاد یا ویرایش بلوک"""
    block = None
    if block_id:
        block = get_object_or_404(Block, id=block_id)

    if request.method == 'POST':
        form = BlockForm(request.POST, instance=block)
        if form.is_valid():
            form.save()
            messages.success(request, f'بلوک "{form.instance.name}" با موفقیت ذخیره شد.')
            return redirect('matches:admin_block_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = BlockForm(instance=block)

    return render(request, 'matches/admin_block_form.html', {'form': form, 'block': block})


@staff_member_required
def admin_block_delete(request, block_id):
    """حذف بلوک"""
    block = get_object_or_404(Block, id=block_id)
    if request.method == 'POST':
        block_name = block.name
        block.delete()
        messages.success(request, f'بلوک "{block_name}" با موفقیت حذف شد.')
        return redirect('matches:admin_block_list')
    return render(request, 'matches/admin_block_confirm_delete.html', {'block': block})


# ============================================================
#  مدیریت مسابقات (فقط ادمین)
# ============================================================

@staff_member_required
def admin_match_create(request):
    """ایجاد مسابقه جدید"""
    if request.method == 'POST':
        form = MatchForm(request.POST, request.FILES)
        if form.is_valid():
            match = form.save(commit=False)
            match.created_by = request.user
            match.save()
            messages.success(request, f'مسابقه "{match.home_team} vs {match.away_team}" با موفقیت ایجاد شد.')
            return redirect('matches:admin_match_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = MatchForm()

    return render(request, 'matches/admin_match_form.html', {'form': form, 'is_edit': False})


@staff_member_required
def admin_match_edit(request, match_id):
    """ویرایش مسابقه"""
    match = get_object_or_404(Match, id=match_id)

    if request.method == 'POST':
        form = MatchForm(request.POST, request.FILES, instance=match)
        if form.is_valid():
            form.save()
            messages.success(request, f'مسابقه "{match.home_team} vs {match.away_team}" با موفقیت ویرایش شد.')
            return redirect('matches:admin_match_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = MatchForm(instance=match)

    return render(request, 'matches/admin_match_form.html', {'form': form, 'match': match, 'is_edit': True})


@staff_member_required
def admin_match_delete(request, match_id):
    """حذف مسابقه"""
    match = get_object_or_404(Match, id=match_id)
    if request.method == 'POST':
        match_name = f"{match.home_team} vs {match.away_team}"
        match.delete()
        messages.success(request, f'مسابقه "{match_name}" با موفقیت حذف شد.')
        return redirect('matches:admin_match_list')
    return render(request, 'matches/admin_match_confirm_delete.html', {'match': match})


# ============================================================
#  مدیریت ورزشگاه‌ها (فقط ادمین)
# ============================================================
@staff_member_required
def admin_stadium_list(request):
    stadiums = Stadium.objects.all().order_by('name')

    # آمار کلی
    total_blocks = Block.objects.filter(is_active=True).count()
    total_seats = Seat.objects.filter(is_available=True).count()
    total_matches = Match.objects.filter(is_active=True).count()

    context = {
        'stadiums': stadiums,  # ← کلید اصلی
        'total_blocks': total_blocks,
        'total_seats': total_seats,
        'total_matches': total_matches,
    }
    return render(request, 'matches/admin_stadium_list.html', context)


@staff_member_required
def admin_stadium_create(request):
    """ایجاد ورزشگاه جدید"""
    if request.method == 'POST':
        form = StadiumForm(request.POST)
        if form.is_valid():
            stadium = form.save()
            messages.success(request, f'ورزشگاه "{stadium.name}" با موفقیت ایجاد شد.')
            return redirect('matches:admin_stadium_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = StadiumForm()

    return render(request, 'matches/admin_stadium_form.html', {'form': form, 'is_edit': False})


@staff_member_required
def admin_stadium_edit(request, stadium_id):
    """ویرایش ورزشگاه"""
    stadium = get_object_or_404(Stadium, id=stadium_id)

    if request.method == 'POST':
        form = StadiumForm(request.POST, instance=stadium)
        if form.is_valid():
            form.save()
            messages.success(request, f'ورزشگاه "{stadium.name}" با موفقیت ویرایش شد.')
            return redirect('matches:admin_stadium_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = StadiumForm(instance=stadium)

    return render(request, 'matches/admin_stadium_form.html', {'form': form, 'stadium': stadium, 'is_edit': True})


@staff_member_required
def admin_stadium_delete(request, stadium_id):
    """حذف ورزشگاه"""
    stadium = get_object_or_404(Stadium, id=stadium_id)
    if request.method == 'POST':
        stadium_name = stadium.name
        stadium.delete()
        messages.success(request, f'ورزشگاه "{stadium_name}" با موفقیت حذف شد.')
        return redirect('matches:admin_stadium_list')

    return render(request, 'matches/admin_stadium_confirm_delete.html', {'stadium': stadium})


@staff_member_required
def admin_stadium_configure(request, stadium_id=None):
    """
    صفحه پیکربندی ورزشگاه:
    - ایجاد ورزشگاه جدید با ساختار کامل (بلوک‌ها، ردیف‌ها، صندلی‌ها)
    - ویرایش ساختار ورزشگاه موجود
    """
    stadium = None
    blocks_data = []

    # ===== دریافت داده‌های ورزشگاه برای نمایش در فرم (GET) =====
    if stadium_id:
        stadium = get_object_or_404(Stadium, id=stadium_id)
        blocks = Block.objects.filter(stadium=stadium, is_active=True).order_by('order')

        for block in blocks:
            rows = Row.objects.filter(block=block, is_active=True).order_by('number')
            patterns = []

            if rows.exists():
                # استخراج محدوده ردیف‌های پیوسته
                row_numbers = list(rows.values_list('number', flat=True))
                ranges = []
                start = row_numbers[0]
                end = row_numbers[0]

                for num in row_numbers[1:]:
                    if num == end + 1:
                        end = num
                    else:
                        ranges.append(f"{start}-{end}" if start != end else str(start))
                        start = end = num
                ranges.append(f"{start}-{end}" if start != end else str(start))

                # دریافت بازه صندلی‌ها از یک ردیف نمونه
                sample_row = rows.first()
                seats = Seat.objects.filter(row=sample_row).order_by('number')
                if seats.exists():
                    seat_start = seats.first().number
                    seat_end = seats.last().number
                    for r in ranges:
                        patterns.append({
                            'rows': r,
                            'start': seat_start,
                            'end': seat_end,
                        })
                else:
                    patterns.append({'rows': '1-25', 'start': 1, 'end': 30})
            else:
                patterns.append({'rows': '1-25', 'start': 1, 'end': 30})

            blocks_data.append({
                'block': {
                    'id': block.id,
                    'name': block.name,
                    'zone_type': block.zone_type,
                    'price': int(block.price),
                    'is_vip': block.is_vip,
                    'is_class1': block.is_class1,
                },
                'patterns': patterns,
            })

    # ===== پردازش درخواست POST (ایجاد/ویرایش) =====
    if request.method == 'POST':
        stadium_name = request.POST.get('stadium_name', '').strip()
        stadium_capacity = request.POST.get('stadium_capacity', 0)
        block_count = request.POST.get('block_count', 0)

        # اعتبارسنجی نام ورزشگاه
        if not stadium_name:
            messages.error(request, 'لطفاً نام ورزشگاه را وارد کنید.')
            return render(request, 'matches/admin_stadium_configure.html', {
                'stadium': stadium,
                'blocks_data': blocks_data,
            })

        # اعتبارسنجی ظرفیت
        try:
            stadium_capacity = int(stadium_capacity) if stadium_capacity else 0
        except ValueError:
            stadium_capacity = 0

        # اعتبارسنجی تعداد بلوک‌ها
        try:
            block_count = int(block_count) if block_count else 0
        except ValueError:
            block_count = 0

        if block_count == 0:
            messages.error(request, 'حداقل یک بلوک باید تعریف شود.')
            return render(request, 'matches/admin_stadium_configure.html', {
                'stadium': stadium,
                'blocks_data': blocks_data,
            })

        # ===== شروع تراکنش =====
        with transaction.atomic():
            try:
                # ایجاد یا به‌روزرسانی ورزشگاه
                if stadium:
                    stadium.name = stadium_name
                    stadium.capacity = stadium_capacity
                    stadium.save()
                    # حذف بلوک‌های قدیمی (برای بازسازی کامل)
                    Block.objects.filter(stadium=stadium).delete()
                    messages.info(request, f'بلوک‌های قدیمی ورزشگاه "{stadium.name}" حذف شدند.')
                else:
                    stadium = Stadium.objects.create(
                        name=stadium_name,
                        capacity=stadium_capacity
                    )

                # ===== ایجاد بلوک‌های جدید =====
                for i in range(1, block_count + 1):
                    block_name = request.POST.get(f'block_name_{i}', '').strip()
                    if not block_name:
                        messages.warning(request, f'بلوک شماره {i} نام ندارد، رد شد.')
                        continue

                    zone_type = request.POST.get(f'block_zone_{i}', 'home')
                    price = request.POST.get(f'block_price_{i}', 0)

                    try:
                        price = int(price) if price else 0
                    except ValueError:
                        price = 0

                    is_vip = request.POST.get(f'block_is_vip_{i}') == 'on'
                    is_class1 = request.POST.get(f'block_is_class1_{i}') == 'on'

                    # ایجاد بلوک
                    block = Block.objects.create(
                        stadium=stadium,
                        name=block_name,
                        zone_type=zone_type,
                        price=price,
                        is_vip=is_vip,
                        is_class1=is_class1,
                        is_active=True,
                        order=i,
                    )

                    # ===== ایجاد ردیف‌ها بر اساس الگوها =====
                    pattern_count = request.POST.get(f'row_pattern_count_{i}', 0)
                    try:
                        pattern_count = int(pattern_count) if pattern_count else 0
                    except ValueError:
                        pattern_count = 0

                    if pattern_count == 0:
                        messages.warning(request, f'بلوک "{block_name}" بدون الگوی ردیف ایجاد شد.')
                        continue

                    for j in range(1, pattern_count + 1):
                        rows_range = request.POST.get(f'row_range_{i}_{j}', '').strip()
                        seat_start = request.POST.get(f'seat_start_{i}_{j}', 1)
                        seat_end = request.POST.get(f'seat_end_{i}_{j}', 0)

                        try:
                            seat_start = int(seat_start) if seat_start else 1
                            seat_end = int(seat_end) if seat_end else 0
                        except ValueError:
                            seat_start = 1
                            seat_end = 0

                        if not rows_range or seat_end == 0:
                            messages.warning(
                                request,
                                f'الگوی {j} در بلوک "{block_name}" ناقص است، رد شد.'
                            )
                            continue

                        # پردازش محدوده ردیف‌ها
                        if '-' in rows_range:
                            try:
                                start_row, end_row = map(int, rows_range.split('-'))
                            except ValueError:
                                messages.warning(
                                    request,
                                    f'محدوده ردیف‌ها در الگوی {j} نامعتبر است: {rows_range}'
                                )
                                continue
                        else:
                            try:
                                start_row = end_row = int(rows_range)
                            except ValueError:
                                messages.warning(
                                    request,
                                    f'شماره ردیف در الگوی {j} نامعتبر است: {rows_range}'
                                )
                                continue

                        # ایجاد ردیف‌ها و صندلی‌ها
                        for row_num in range(start_row, end_row + 1):
                            row = Row.objects.create(
                                block=block,
                                number=row_num,
                                is_active=True
                            )
                            seats = [
                                Seat(row=row, number=num, is_available=True)
                                for num in range(seat_start, seat_end + 1)
                            ]
                            Seat.objects.bulk_create(seats)

                messages.success(
                    request,
                    f'ورزشگاه "{stadium.name}" با {block_count} بلوک و ساختار کامل ذخیره شد.'
                )
                return redirect('matches:admin_stadium_list')

            except IntegrityError as e:
                messages.error(request, f'خطا در ذخیره‌سازی: {str(e)}. احتمالاً نام بلوک تکراری است.')
                return render(request, 'matches/admin_stadium_configure.html', {
                    'stadium': stadium,
                    'blocks_data': blocks_data,
                })
            except Exception as e:
                messages.error(request, f'خطای غیرمنتظره: {str(e)}')
                return render(request, 'matches/admin_stadium_configure.html', {
                    'stadium': stadium,
                    'blocks_data': blocks_data,
                })

    # ===== رندر صفحه (GET) =====
    context = {
        'stadium': stadium,
        'blocks_data': blocks_data,
    }
    return render(request, 'matches/admin_stadium_configure.html', context)
