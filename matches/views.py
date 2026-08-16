import json
import os
from decimal import Decimal, InvalidOperation
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction, IntegrityError
from django.db.models import Q, Count, Prefetch, Sum
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from tickets.models import Ticket
from tickets.reservation import SeatReservation
from .forms import BlockForm, MatchForm, StadiumForm
from .models import Match, Row, Seat, MatchSeat, Block, Stadium

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db import models
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML
import tempfile
import os
from django.conf import settings
from .models import Match, MatchCost, MatchRevenue, MatchFinancialReport, MatchBlockPrice, get_block_price_map, MatchBasaDiscount
from .forms import MatchCostForm, MatchRevenueForm
from tickets.models import Ticket
from django.views.decorators.cache import cache_page
from django.views.decorators.cache import never_cache


# ============================================================
#  ویوهای عمومی (کاربران عادی)
# ============================================================
@never_cache
def home(request):
    """صفحه اصلی - نمایش مسابقات با ظرفیت‌های دقیق"""
    # ===== بررسی نمایش صفحه لودینگ =====
    if not request.session.get('splash_seen'):
        return redirect('matches:splash')
    # ===== تعریف رشته‌های ورزشی =====
    SPORT_CHOICES = (
        ('football', 'فوتبال'),
        ('volleyball', 'والیبال'),
        ('handball', 'هندبال'),
        ('basketball', 'بسکتبال'),
        ('futsal', 'فوتسال'),
        ('other', 'سایر'),
    )

    # ===== دریافت فیلترها =====
    sport_filter = request.GET.get('sport')
    stadium_filter = request.GET.get('stadium')

    # ===== کوئری پایه =====
    # نمایش/عدم‌نمایش مسابقه فقط با is_active کنترل می‌شود، نه با گذشتن زمان
    # شروع؛ ادمین خودش تصمیم می‌گیرد کِی مسابقه از سایت جمع شود.
    matches = Match.objects.filter(is_active=True).order_by('date_time')

    if sport_filter:
        matches = matches.filter(sport_type=sport_filter)
    if stadium_filter:
        matches = matches.filter(stadium_id=stadium_filter)

    # ===== محاسبه آمار برای همه مسابقات با حداقل کوئری (بدون N+1) =====
    matches_list = list(matches)
    stadium_ids = {m.stadium_id for m in matches_list}

    # ظرفیت کل هر ورزشگاه (یک کوئری)
    stadium_capacity = {
        row['row__block__stadium']: row['c']
        for row in (
            Seat.objects
            .filter(
                row__block__stadium_id__in=stadium_ids,
                row__block__is_active=True,
                row__is_active=True,
            )
            .values('row__block__stadium')
            .annotate(c=Count('id'))
        )
    }

    # تعداد صندلی‌های غیرفعال (فروخته/رزرو) per match
    sold_map = {
        row['match_id']: row['c']
        for row in (
            MatchSeat.objects
            .filter(match_id__in=[m.id for m in matches_list], is_available=False)
            .values('match_id')
            .annotate(c=Count('id'))
        )
    }

    for match in matches_list:
        total_seats = stadium_capacity.get(match.stadium_id, 0)
        sold_seats = sold_map.get(match.id, 0)
        available_seats = max(total_seats - sold_seats, 0)
        occupancy = round((sold_seats / total_seats * 100) if total_seats > 0 else 0, 1)
        match.sold_tickets = sold_seats
        match.available_seats = available_seats
        match.occupancy = occupancy

    matches = matches_list

    # ===== دریافت لیست ورزشگاه‌ها =====
    stadiums = Stadium.objects.all().order_by('name')

    context = {
        'matches': matches,
        'stadiums': stadiums,
        'sport_choices': SPORT_CHOICES,
        'selected_sport': sport_filter,
        'selected_stadium': int(stadium_filter) if stadium_filter else None,
    }
    return render(request, 'matches/home.html', context)


def splash(request):
    """صفحه لودینگ (Splash Screen)"""
    return render(request, 'matches/splash.html')


@csrf_exempt
def set_splash_seen(request):
    """تنظیم splash_seen در session برای جلوگیری از نمایش مجدد"""
    if request.method == 'POST':
        request.session['splash_seen'] = True
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)


def match_detail(request, match_id):
    """نمایش جزئیات یک مسابقه"""
    match = get_object_or_404(Match, id=match_id, is_active=True)
    return render(request, 'matches/match_detail.html', {'match': match})


# ============================================================
#  مراحل خرید بلیط (کاربران عادی)
# ============================================================
@login_required
def select_floor(request, match_id):
    """انتخاب طبقه (پایین یا بالا) و تیم (میزبان یا میهمان) قبل از نمایش بلوک‌ها"""
    match = get_object_or_404(Match, id=match_id, is_active=True)
    if not match.ticket_sales_enabled:
        messages.error(request, 'فروش بلیط برای این مسابقه غیرفعال است.')
        return redirect('matches:home')

    if request.method == 'POST':
        floor = request.POST.get('floor')
        team_type = request.POST.get('team_type')  # <--- اضافه شد

        if floor in ['ground', 'second'] and team_type in ['home', 'away']:
            request.session['selected_floor'] = floor
            request.session['selected_team_type'] = team_type  # <--- ذخیره در سشن
            return redirect('matches:select_block', match_id=match_id)
        else:
            messages.error(request, 'لطفاً طبقه و تیم (میزبان/میهمان) را به درستی انتخاب کنید.')

    return render(request, 'matches/select_floor.html', {'match': match})


@login_required
def select_block(request, match_id):
    match = get_object_or_404(Match, id=match_id, is_active=True)
    if not match.ticket_sales_enabled:
        messages.error(request, 'فروش بلیط برای این مسابقه غیرفعال است.')
        return redirect('matches:home')
    stadium = match.stadium

    selected_floor = request.session.get('selected_floor', 'ground')
    selected_team_type = request.session.get('selected_team_type', 'home')  # <--- دریافت انتخاب کاربر از سشن

    # فیلتر بر اساس طبقه -- selected_floor مقادیر 'ground'/'second' دارد که
    # دقیقاً با choices فیلد Block.floor یکی است
    blocks = Block.objects.filter(
        stadium=stadium,
        is_active=True,
        floor=selected_floor,
    ).order_by('order')

    # ===== فیلتر بر اساس میزبان یا میهمان بودن =====
    if selected_team_type == 'away':
        # اگر کاربر میهمان را انتخاب کرده باشد، فقط بلوک‌های میهمان نشان داده شود
        blocks = blocks.filter(zone_type='away')
    else:
        # اگر کاربر میزبان را انتخاب کرده باشد، بلوک‌های میهمان نشان داده نشود (تا VIP، بانوان و کلاس ۱ هم برای میزبان باشد)
        blocks = blocks.exclude(zone_type='away')

    if not blocks.exists():
        messages.warning(
            request,
            f'هیچ بلوکی برای تیم "{"میهمان" if selected_team_type == "away" else "میزبان"}" در طبقه {"بالا" if selected_floor == "second" else "پایین"} تعریف نشده است.'
        )
        return redirect('matches:select_floor', match_id=match_id)

    zone_labels = {
        'home': ('home', 'میزبان'),
        'away': ('away', 'میهمان'),
        'class1': ('class1', 'کلاس ۱'),
        'women': ('women', 'بانوان'),
        'vip': ('vip', 'VIP'),
    }

    # آمار بلوک‌ها با ۲–۳ کوئری به‌جای N+1
    blocks = list(blocks)
    block_ids = [b.id for b in blocks]

    total_map = {
        row['row__block']: row['c']
        for row in (
            Seat.objects
            .filter(row__block_id__in=block_ids, is_available=True)
            .values('row__block')
            .annotate(c=Count('id'))
        )
    }

    # تعداد MatchSeat موجود و کل MatchSeat per block برای این مسابقه
    ms_stats = {
        row['seat__row__block']: row
        for row in (
            MatchSeat.objects
            .filter(match=match, seat__row__block_id__in=block_ids)
            .values('seat__row__block')
            .annotate(
                total_ms=Count('id'),
                available_ms=Count('id', filter=Q(is_available=True)),
            )
        )
    }

    block_price_map = get_block_price_map(match)

    for block in blocks:
        total_seats = total_map.get(block.id, 0)
        stats = ms_stats.get(block.id, {})
        available_ms = stats.get('available_ms', 0)
        total_ms = stats.get('total_ms', 0)
        # صندلی‌هایی که هنوز MatchSeat ندارند = در دسترس فرض می‌شوند
        seats_without_ms = max(total_seats - total_ms, 0)
        available_seats = available_ms + seats_without_ms

        block.total_seats = total_seats
        block.available_seats = available_seats
        # قیمت اختصاصی این مسابقه در صورت وجود، در غیر این صورت قیمت پیش‌فرض بلوک
        block.price = block_price_map.get(block.id, block.price)
        block.occupancy = round(
            ((total_seats - available_seats) / total_seats * 100) if total_seats > 0 else 0,
            1
        )

        zone_type = block.zone_type
        if zone_type in zone_labels:
            block.team_type, block.team_type_label = zone_labels[zone_type]
        else:
            block.team_type, block.team_type_label = ('home', 'میزبان')

    if request.method == 'POST':
        block_id = request.POST.get('block_id')
        if block_id:
            block = get_object_or_404(Block, id=block_id)
            if Seat.objects.filter(row__block=block).count() == 0:
                messages.error(
                    request,
                    f'بلوک "{block.name}" هیچ صندلی‌ای ندارد! لطفاً با مدیر تماس بگیرید.'
                )
                return redirect('matches:select_block', match_id=match_id)
            request.session['selected_block_id'] = block_id
            return redirect('matches:block_map', match_id=match_id)
        else:
            messages.error(request, 'لطفاً یک بلوک را انتخاب کنید.')

    context = {
        'match': match,
        'blocks': blocks,
        'selected_floor': selected_floor,
        'selected_team_type': selected_team_type,  # <--- ارسال به قالب
        'floor_label': 'طبقه بالا' if selected_floor == 'second' else 'طبقه پایین',
        'stadium_image': stadium.image.url if stadium.image else None,
    }
    return render(request, 'matches/select_block.html', context)


@login_required
def show_block_map(request, match_id):
    match = get_object_or_404(Match, id=match_id, is_active=True)
    if not match.ticket_sales_enabled:
        messages.error(request, 'فروش بلیط برای این مسابقه غیرفعال است.')
        return redirect('matches:home')
    block_id = request.session.get('selected_block_id')
    if not block_id:
        messages.error(request, 'لطفاً ابتدا یک بلوک را انتخاب کنید.')
        return redirect('matches:select_block', match_id=match_id)

    block = get_object_or_404(Block, id=block_id)
    rows = Row.objects.filter(block=block, is_active=True).order_by('number')

    # بارگذاری یک‌جا: همه صندلی‌ها + MatchSeatهای موجود (بدون get_or_create در حلقه)
    rows = list(rows)
    all_seats = list(
        Seat.objects
        .filter(row__block=block, row__is_active=True)
        .select_related('row')
        .order_by('row__number', 'number')
    )
    seat_ids = [s.id for s in all_seats]

    existing_ms = {
        ms.seat_id: ms
        for ms in MatchSeat.objects.filter(match=match, seat_id__in=seat_ids)
    }

    # ساخت MatchSeatهای گم‌شده به‌صورت bulk (یک‌بار، نه per-request در حالت ایده‌آل)
    missing = [
        MatchSeat(match=match, seat_id=s.id, is_available=True)
        for s in all_seats if s.id not in existing_ms
    ]
    if missing:
        MatchSeat.objects.bulk_create(missing, ignore_conflicts=True)
        # بارگذاری مجدد برای گرفتن idها
        existing_ms = {
            ms.seat_id: ms
            for ms in MatchSeat.objects.filter(match=match, seat_id__in=seat_ids)
        }

    # وضعیت رزرو Redis برای نمایش دقیق‌تر (اختیاری ولی سبک با get_many)
    ms_ids = [ms.id for ms in existing_ms.values()]
    reserved_map = SeatReservation.get_reserved_map(ms_ids)

    map_data = []
    first_row_id = None
    seats_by_row = {}
    for seat in all_seats:
        seats_by_row.setdefault(seat.row_id, []).append(seat)

    for row in rows:
        row_seats = seats_by_row.get(row.id, [])
        if not row_seats:
            continue
        if first_row_id is None:
            first_row_id = row.id

        seat_list = []
        for seat in row_seats:
            ms = existing_ms.get(seat.id)
            if not ms:
                continue
            # صندلی‌ای که خودش (نه فقط برای این مسابقه) غیرفعال شده هیچ‌وقت
            # سبز نشان داده نمی‌شود -- مستقل از وضعیت رزرو/فروش این مسابقه
            if not seat.is_available:
                seat_list.append({
                    'number': seat.number,
                    'is_available': False,
                    'id': ms.id,
                })
                continue
            # اگر در Redis رزرو شده و هنوز is_available در DB True مانده، غیرفعال نشان بده
            is_avail = ms.is_available and not reserved_map.get(ms.id)
            # رزرو منقضی‌شده در DB را در دسترس نشان بده
            if (
                not ms.is_available
                and ms.reserved_until
                and ms.reserved_until < timezone.now()
                and not reserved_map.get(ms.id)
            ):
                is_avail = True
            seat_list.append({
                'number': seat.number,
                'is_available': is_avail,
                'id': ms.id,
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
    if not match.ticket_sales_enabled:
        messages.error(request, 'فروش بلیط برای این مسابقه غیرفعال است.')
        return redirect('matches:home')
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
        'block_status': block_status,
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

    active_count = sum(1 for item in block_status if item['status'] == 'active')
    inactive_count = sum(1 for item in block_status if item['status'] == 'inactive')
    partial_count = sum(1 for item in block_status if item['status'] == 'partial')
    no_seats_count = sum(1 for item in block_status if item['status'] == 'no_seats')

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

def _reactivate_block_if_needed(block):
    """اگر بلوک غیرفعال است ولی الان حداقل یک صندلی فعال دارد، خودِ بلوک را
    هم فعال می‌کند -- چون فعال‌کردن دستی یک صندلی داخل بلوک غیرفعال یعنی
    ادمین می‌خواهد آن بخش دوباره در دسترس باشد (وگرنه توی «مدیریت بلوک‌ها»
    همچنان به‌عنوان غیرفعال دیده می‌شد با اینکه صندلی فعال دارد)."""
    if not block.is_active and Seat.objects.filter(row__block=block, is_available=True).exists():
        block.is_active = True
        block.save(update_fields=['is_active'])
        return True
    return False


@staff_member_required
def manage_block_seats(request, block_id=None):
    """
    مدیریت صندلی‌های یک بلوک با نمایش وضعیت بلیط‌ها و قابلیت:
    - غیرفعال/فعال/تغییر وضعیت انتخاب‌شده‌ها
    - فعال‌سازی/غیرفعال‌سازی کل ردیف
    - فعال‌سازی/غیرفعال‌سازی کل بلوک
    """

    # اگر block_id از URL دریافت نشد، از GET بگیر
    if not block_id:
        block_id = request.GET.get('block_id')

    selected_block = None
    seats = []
    total_seats = 0
    active_seats = 0
    inactive_seats = 0
    sold_seats = 0

    # لیست همه بلوک‌ها برای dropdown انتخاب بلوک
    all_blocks = Block.objects.filter(is_active=True).order_by('order')

    # اگر بلوکی انتخاب شده باشد، اطلاعات آن را بگیر
    if block_id:
        selected_block = get_object_or_404(Block, id=block_id)
        seats = Seat.objects.filter(row__block=selected_block).order_by('row__number', 'number')

        # برچسب‌گذاری صندلی‌های دارای بلیط
        for seat in seats:
            has_ticket = Ticket.objects.filter(
                seat=seat,
                status__in=['paid', 'admin_assigned', 'vip_issued']
            ).exists()
            seat.has_ticket = has_ticket

        total_seats = seats.count()
        active_seats = seats.filter(is_available=True).count()
        inactive_seats = total_seats - active_seats
        sold_seats = sum(1 for s in seats if s.has_ticket)

    # ===== پردازش درخواست POST =====
    if request.method == 'POST' and selected_block:
        action = request.POST.get('action')

        # ===== بررسی وجود action =====
        if not action:
            messages.error(request, 'خطا: عملیات مشخص نشده است. لطفاً دوباره تلاش کنید.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ===== دیباگ =====
        print(f">>>> ACTION RECEIVED: {action}")

        selected_seats = request.POST.getlist('selected_seats')

        # ---------- ۱. غیرفعال‌سازی انتخاب‌شده‌ها ----------
        if action == 'deactivate':
            if not selected_seats:
                messages.warning(request, 'هیچ صندلی‌ای انتخاب نشده است.')
            else:
                # تفکیک صندلی‌های دارای بلیط
                seats_with_ticket = Seat.objects.filter(
                    id__in=selected_seats,
                    ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
                ).distinct()
                seats_without_ticket = Seat.objects.filter(
                    id__in=selected_seats
                ).exclude(id__in=seats_with_ticket.values_list('id', flat=True))

                if seats_with_ticket.exists():
                    messages.warning(
                        request,
                        f'صندلی‌های {", ".join(str(s.number) for s in seats_with_ticket)} دارای بلیط هستند و غیرفعال نشدند.'
                    )
                if seats_without_ticket.exists():
                    count = seats_without_ticket.update(is_available=False)
                    messages.success(request, f'{count} صندلی غیرفعال شدند.')
                if not seats_with_ticket.exists() and not seats_without_ticket.exists():
                    messages.info(request, 'همه صندلی‌های انتخاب‌شده قبلاً غیرفعال هستند.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ---------- ۲. فعال‌سازی انتخاب‌شده‌ها ----------
        elif action == 'activate':
            if not selected_seats:
                messages.warning(request, 'هیچ صندلی‌ای انتخاب نشده است.')
            else:
                # فقط صندلی‌های بدون بلیط را فعال کن
                seats_without_ticket = Seat.objects.filter(
                    id__in=selected_seats
                ).exclude(
                    ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
                )
                count = seats_without_ticket.update(is_available=True)
                if count > 0:
                    reactivated = _reactivate_block_if_needed(selected_block)
                    msg = f'{count} صندلی فعال شدند.'
                    if reactivated:
                        msg += ' بلوک هم به‌صورت خودکار فعال شد.'
                    messages.success(request, msg)
                else:
                    messages.info(request, 'صندلی‌های انتخاب‌شده دارای بلیط هستند یا قبلاً فعال هستند.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ---------- ۳. تغییر وضعیت انتخاب‌شده‌ها ----------
        elif action == 'toggle':
            if not selected_seats:
                messages.warning(request, 'هیچ صندلی‌ای انتخاب نشده است.')
            else:
                seats_with_ticket = Seat.objects.filter(
                    id__in=selected_seats,
                    ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
                ).distinct()
                seats_without_ticket = Seat.objects.filter(
                    id__in=selected_seats
                ).exclude(id__in=seats_with_ticket.values_list('id', flat=True))

                if seats_with_ticket.exists():
                    messages.warning(
                        request,
                        f'صندلی‌های {", ".join(str(s.number) for s in seats_with_ticket)} دارای بلیط هستند و تغییر نکردند.'
                    )
                if seats_without_ticket.exists():
                    count = seats_without_ticket.count()
                    for seat in seats_without_ticket:
                        seat.is_available = not seat.is_available
                        seat.save()
                    reactivated = _reactivate_block_if_needed(selected_block)
                    msg = f'{count} صندلی تغییر وضعیت یافتند.'
                    if reactivated:
                        msg += ' بلوک هم به‌صورت خودکار فعال شد.'
                    messages.success(request, msg)
                if not seats_with_ticket.exists() and not seats_without_ticket.exists():
                    messages.info(request, 'هیچ صندلی قابل تغییری انتخاب نشده است.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ---------- ۴. فعال‌سازی کل ردیف (جدید) ----------
        elif action == 'activate_row':
            row_number = request.POST.get('row_number')
            print(f">>>> Activating row: {row_number}")

            if not row_number:
                messages.error(request, 'شماره ردیف مشخص نشده است.')
                return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

            try:
                row_num = int(row_number)
                row = selected_block.rows.filter(number=row_num).first()
                if row:
                    # فقط صندلی‌های بدون بلیط را فعال کن
                    seats_without_ticket = Seat.objects.filter(
                        row=row
                    ).exclude(
                        ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
                    )
                    count = seats_without_ticket.update(is_available=True)
                    if count > 0:
                        reactivated = _reactivate_block_if_needed(selected_block)
                        msg = f'{count} صندلی در ردیف {row_num} فعال شدند.'
                        if reactivated:
                            msg += ' بلوک هم به‌صورت خودکار فعال شد.'
                        messages.success(request, msg)
                    else:
                        messages.info(request, f'همه صندلی‌های ردیف {row_num} قبلاً فعال یا دارای بلیط هستند.')
                else:
                    messages.error(request, f'ردیف {row_num} یافت نشد.')
            except ValueError:
                messages.error(request, 'شماره ردیف نامعتبر است.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ---------- ۵. غیرفعال‌سازی کل ردیف ----------
        elif action == 'deactivate_row':
            row_number = request.POST.get('row_number')
            print(f">>>> Deactivating row: {row_number}")

            if not row_number:
                messages.error(request, 'شماره ردیف مشخص نشده است.')
                return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

            try:
                row_num = int(row_number)
                row = selected_block.rows.filter(number=row_num).first()
                if row:
                    # فقط صندلی‌های بدون بلیط را غیرفعال کن
                    seats_without_ticket = Seat.objects.filter(
                        row=row
                    ).exclude(
                        ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
                    )
                    count = seats_without_ticket.update(is_available=False)
                    if count > 0:
                        messages.success(request, f'{count} صندلی در ردیف {row_num} غیرفعال شدند.')
                    else:
                        messages.info(request, f'همه صندلی‌های ردیف {row_num} قبلاً غیرفعال یا دارای بلیط هستند.')
                else:
                    messages.error(request, f'ردیف {row_num} یافت نشد.')
            except ValueError:
                messages.error(request, 'شماره ردیف نامعتبر است.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ---------- ۶. فعال‌سازی کل بلوک (جدید) ----------
        elif action == 'activate_block':
            print(f">>>> Activating entire block: {selected_block.name}")

            # فقط صندلی‌های بدون بلیط را فعال کن
            seats_without_ticket = Seat.objects.filter(
                row__block=selected_block
            ).exclude(
                ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
            )
            count = seats_without_ticket.update(is_available=True)
            if count > 0:
                reactivated = _reactivate_block_if_needed(selected_block)
                msg = f'{count} صندلی از کل بلوک فعال شدند.'
                if reactivated:
                    msg += ' بلوک هم به‌صورت خودکار فعال شد.'
                messages.success(request, msg)
            else:
                messages.info(request, 'همه صندلی‌های این بلوک قبلاً فعال یا دارای بلیط هستند.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ---------- ۷. غیرفعال‌سازی کل بلوک ----------
        elif action == 'deactivate_block':
            print(f">>>> Deactivating entire block: {selected_block.name}")

            # فقط صندلی‌های بدون بلیط را غیرفعال کن
            seats_without_ticket = Seat.objects.filter(
                row__block=selected_block
            ).exclude(
                ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
            )
            count = seats_without_ticket.update(is_available=False)
            if count > 0:
                messages.success(request, f'{count} صندلی از کل بلوک غیرفعال شدند.')
            else:
                messages.info(request, 'همه صندلی‌های این بلوک قبلاً غیرفعال یا دارای بلیط هستند.')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

        # ---------- ۸. در صورت دریافت action ناشناخته ----------
        else:
            messages.error(request, f'عملیات نامعتبر: {action}')
            return redirect(f'{reverse("matches:manage_block_seats")}?block_id={selected_block.id}')

    # ===== نمایش صفحه (GET) =====
    context = {
        'all_blocks': all_blocks,
        'selected_block': selected_block,
        'seats': seats,
        'total_seats': total_seats,
        'active_seats': active_seats,
        'inactive_seats': inactive_seats,
        'sold_seats': sold_seats,
    }
    return render(request, 'matches/manage_block_seats.html', context)


# ============================================================
#  ادامه ویوهای API و مدیریت
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


# ============================================================
#  ویوهای لیست و جزئیات مسابقه (اصلاح شده)
# ============================================================

@staff_member_required
def admin_match_list(request):
    """لیست مسابقات برای ادمین با آمار دقیق اشغال صندلی‌ها و درآمد و تفکیک سکوها"""
    sport_filter = request.GET.get('sport')
    stadium_filter = request.GET.get('stadium')
    match_filter = request.GET.get('match_id')

    matches_qs = Match.objects.all().order_by('-date_time')
    if sport_filter: matches_qs = matches_qs.filter(sport_type=sport_filter)
    if stadium_filter: matches_qs = matches_qs.filter(stadium_id=stadium_filter)
    if match_filter: matches_qs = matches_qs.filter(id=match_filter)

    match_data = []
    total_sold = 0;
    total_vip = 0;
    total_revenue = 0

    for match in matches_qs:
        total_seats = Seat.objects.filter(row__block__stadium=match.stadium, row__block__is_active=True,
                                          row__is_active=True).count()
        sold_tickets = Ticket.objects.filter(match=match, status='paid')
        vip_tickets = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued'])

        # ===== تمام بلیط‌های صادر شده (برای تفکیک سکوها) =====
        all_issued_tickets = sold_tickets | vip_tickets
        home_sold = all_issued_tickets.filter(seat__row__block__zone_type='home').count()
        away_sold = all_issued_tickets.filter(seat__row__block__zone_type='away').count()
        women_sold = all_issued_tickets.filter(seat__row__block__zone_type='women').count()
        class1_sold = all_issued_tickets.filter(
            Q(seat__row__block__zone_type='class1') | Q(seat__row__block__is_class1=True)).count()
        vip_sold = all_issued_tickets.filter(
            Q(seat__row__block__zone_type='vip') | Q(seat__row__block__is_vip=True)).count()

        sold_count = sold_tickets.count()
        vip_count = vip_tickets.count()
        revenue = sum(t.price or 0 for t in sold_tickets)
        vip_revenue = sum(t.price or 0 for t in vip_tickets)
        total_revenue_match = revenue

        sold_seats = MatchSeat.objects.filter(match=match, is_available=False).count()
        occupancy = round((sold_seats / total_seats * 100) if total_seats > 0 else 0, 1)

        match_data.append({
            'match': match, 'sold_count': sold_count, 'vip_count': vip_count,
            'total_tickets': sold_count + vip_count, 'total_revenue': total_revenue_match,
            'sold_revenue': revenue, 'vip_revenue': vip_revenue,
            'occupied_seats': sold_seats, 'total_seats': total_seats, 'occupancy_percent': occupancy,
            'home_sold': home_sold, 'away_sold': away_sold, 'women_sold': women_sold,
            'class1_sold': class1_sold, 'vip_sold': vip_sold,
        })
        total_sold += sold_count;
        total_vip += vip_count;
        total_revenue += total_revenue_match

    paginator = Paginator(match_data, 10)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    all_matches = Match.objects.all().order_by('-date_time')
    stadiums = Stadium.objects.all().order_by('name')
    sport_choices = getattr(Match, 'SPORT_CHOICES', [])

    context = {
        'page_obj': page_obj, 'all_matches': all_matches, 'stadiums': stadiums, 'sport_choices': sport_choices,
        'selected_sport': sport_filter, 'selected_stadium': int(stadium_filter) if stadium_filter else None,
        'selected_match_id': int(match_filter) if match_filter else None, 'total_matches': matches_qs.count(),
        'total_sold_all': total_sold, 'total_vip_all': total_vip, 'total_revenue_all': total_revenue,
    }
    return render(request, 'matches/admin_match_list.html', context)


@staff_member_required
def admin_match_detail(request, match_id):
    """صفحه جزئیات مسابقه برای ادمین با نمایش بلوک‌های ورزشگاه و آمار تفکیکی سکوها"""
    match = get_object_or_404(Match, id=match_id)

    sold_tickets_qs = Ticket.objects.filter(match=match, status='paid').order_by('-purchase_date')
    vip_tickets_qs = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued']).order_by(
        '-purchase_date')

    sold_total = sum(t.price or 0 for t in sold_tickets_qs)
    vip_total = sum(t.price or 0 for t in vip_tickets_qs)

    # ===== تفکیک بلیط‌های فروخته‌شده: رایگان (زیر ۱۵ سال) / تخفیف باسا / قیمت کامل =====
    # عمداً بر اساس price/basa_discount_amount دسته‌بندی می‌شود، نه فیلد age --
    # چون age امروز اضافه شد و بلیط‌های قدیمی‌تر (قبل از امروز) مقدار age
    # ندارند؛ اگر بر اساس age فیلتر می‌کردیم، آن بلیط‌های قدیمی در هیچ‌کدام
    # از سه دسته نمی‌افتادند در حالی که هنوز در «درآمد کل» حساب می‌شوند --
    # یعنی جمع سه دسته با درآمد کل نمی‌خواند. price=0 در این پروژه فقط به
    # یک دلیل ممکن است (سن زیر ۱۵)، پس معادل قابل‌اعتماد همان قانون است.
    category_stats = sold_tickets_qs.aggregate(
        free_age_count=Count('id', filter=Q(price=0)),
        basa_discount_count=Count('id', filter=Q(basa_discount_amount__gt=0)),
        basa_discount_total=Sum('basa_discount_amount', filter=Q(basa_discount_amount__gt=0)),
        full_price_count=Count('id', filter=~Q(price=0) & Q(basa_discount_amount=0)),
    )

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

    total_match_seats = Seat.objects.filter(row__block__stadium=match.stadium, row__block__is_active=True,
                                            row__is_active=True).count()
    occupied = MatchSeat.objects.filter(match=match, is_available=False).count()
    available = total_match_seats - occupied
    occupancy_percent = round((occupied / total_match_seats * 100) if total_match_seats > 0 else 0, 1)

    blocks = Block.objects.filter(stadium=match.stadium, is_active=True).order_by('order')
    blocks_data = []
    block_price_map = get_block_price_map(match)
    for block in blocks:
        total_seats = Seat.objects.filter(row__block=block, row__is_active=True).count()
        occupied_seats = MatchSeat.objects.filter(match=match, seat__row__block=block, is_available=False).count()
        available_seats = total_seats - occupied_seats
        occupancy = round((occupied_seats / total_seats * 100) if total_seats > 0 else 0, 1)
        block.price = block_price_map.get(block.id, block.price)
        blocks_data.append({
            'block': block, 'total_seats': total_seats, 'occupied_seats': occupied_seats,
            'available_seats': available_seats, 'occupancy': occupancy,
            'row_count': Row.objects.filter(block=block, is_active=True).count(),
        })

    # ===== محاسبه آمار تفکیکی سکوها =====
    all_issued_tickets = sold_tickets_qs | vip_tickets_qs
    home_sold = all_issued_tickets.filter(seat__row__block__zone_type='home').count()
    away_sold = all_issued_tickets.filter(seat__row__block__zone_type='away').count()
    women_sold = all_issued_tickets.filter(seat__row__block__zone_type='women').count()
    class1_sold = all_issued_tickets.filter(
        Q(seat__row__block__zone_type='class1') | Q(seat__row__block__is_class1=True)).count()
    vip_sold = all_issued_tickets.filter(
        Q(seat__row__block__zone_type='vip') | Q(seat__row__block__is_vip=True)).count()

    context = {
        'match': match, 'sold_page': sold_page, 'vip_page': vip_page,
        'sold_total': sold_total, 'vip_total': vip_total, 'total_revenue': sold_total,
        'sold_count': sold_tickets_qs.count(), 'vip_count': vip_tickets_qs.count(),
        'total_tickets': sold_tickets_qs.count() + vip_tickets_qs.count(),
        'total_match_seats': total_match_seats, 'occupied': occupied, 'available': available,
        'occupancy_percent': occupancy_percent, 'blocks_data': blocks_data,
        'current_sold_page': sold_page.number, 'current_vip_page': vip_page.number,
        'sold_page_range': sold_paginator.page_range, 'vip_page_range': vip_paginator.page_range,
        'used_tickets': used_tickets, 'not_used_tickets': not_used_tickets,
        # ===== متغیرهای جدید تفکیکی =====
        'home_sold': home_sold, 'away_sold': away_sold, 'women_sold': women_sold,
        'class1_sold': class1_sold, 'vip_sold': vip_sold,
        # ===== تفکیک درآمد: رایگان/تخفیف باسا/قیمت کامل =====
        'free_age_count': category_stats['free_age_count'],
        'basa_discount_count': category_stats['basa_discount_count'],
        'basa_discount_total': category_stats['basa_discount_total'] or 0,
        'full_price_count': category_stats['full_price_count'],
    }
    return render(request, 'matches/admin_match_detail.html', context)


# ============================================================
#  مدیریت بلوک‌ها (فقط ادمین)
# ============================================================

@staff_member_required
def admin_block_list(request):
    match_id = request.GET.get('match_id')
    stadium_id = request.GET.get('stadium_id')

    selected_match = None
    selected_stadium = None
    # عمداً is_active فیلتر نمی‌شود -- این لیست خودِ صفحه‌ی مدیریت بلوک‌هاست
    # (نه صفحه‌ی عمومی انتخاب سکو)، پس باید بلوک‌های غیرفعال را هم نشان
    # بدهد، وگرنه بعد از غیرفعال کردن یک بلوک، ادمین دیگر هیچ راهی برای
    # پیدا کردن و دوباره فعال کردنش از همین صفحه نداشت (قالب همین حالا هم
    # badge وضعیت و دکمه‌ی فعال/غیرفعال برای هر دو حالت را نمایش می‌دهد).
    blocks = Block.objects.all().order_by('order')

    if match_id:
        selected_match = get_object_or_404(Match, id=match_id)
        selected_stadium = selected_match.stadium
        blocks = blocks.filter(stadium=selected_stadium)
    elif stadium_id:
        selected_stadium = get_object_or_404(Stadium, id=stadium_id)
        blocks = blocks.filter(stadium=selected_stadium)

    matches = Match.objects.filter(is_active=True).order_by('-date_time')
    stadiums = Stadium.objects.all().order_by('name')

    context = {
        'blocks': blocks,
        'matches': matches,
        'stadiums': stadiums,
        'selected_match': selected_match,
        'selected_stadium': selected_stadium,
        'floor_choices': Block.FLOOR_CHOICES,
    }
    return render(request, 'matches/admin_block_list.html', context)


@staff_member_required
def admin_block_edit(request, block_id=None):
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
    block = get_object_or_404(Block, id=block_id)
    if request.method == 'POST':
        block_name = block.name
        block.delete()
        messages.success(request, f'بلوک "{block_name}" با موفقیت حذف شد.')
        return redirect('matches:admin_block_list')
    return render(request, 'matches/admin_block_confirm_delete.html', {'block': block})


def _sync_seats_to_blocks_status(block_ids, is_active):
    """وقتی یک بلوک فعال/غیرفعال می‌شود، صندلی‌های خودش (Seat.is_available)
    را هم هماهنگ می‌کند -- وگرنه صفحه‌ی «مدیریت صندلی‌ها» با وضعیت بلوک
    ناهماهنگ می‌ماند (بلوک غیرفعال ولی صندلی‌هایش هنوز «فعال» نشان داده
    می‌شوند). صندلی‌های دارای بلیط واقعی دست‌نخورده می‌مانند."""
    Seat.objects.filter(row__block_id__in=block_ids).exclude(
        ticket__status__in=['paid', 'admin_assigned', 'vip_issued']
    ).update(is_available=is_active)


@staff_member_required
def toggle_block_status(request, block_id):
    block = get_object_or_404(Block, id=block_id)
    block.is_active = not block.is_active
    block.save()
    _sync_seats_to_blocks_status([block.id], block.is_active)
    status = 'فعال' if block.is_active else 'غیرفعال'
    messages.success(request, f'بلوک "{block.name}" {status} شد.')
    return redirect('matches:admin_block_list')


@staff_member_required
def admin_bulk_toggle_floor(request, stadium_id, floor):
    """فعال/غیرفعال کردن یک‌جای تمام سکوهای یک طبقه در یک ورزشگاه"""
    if request.method != 'POST':
        return redirect('matches:admin_block_list')

    stadium = get_object_or_404(Stadium, id=stadium_id)
    if floor not in dict(Block.FLOOR_CHOICES):
        messages.error(request, 'طبقه نامعتبر است.')
        return redirect('matches:admin_block_list')

    new_state = request.POST.get('action') == 'activate'
    floor_block_ids = list(Block.objects.filter(stadium=stadium, floor=floor).values_list('id', flat=True))
    updated = Block.objects.filter(id__in=floor_block_ids).update(is_active=new_state)
    _sync_seats_to_blocks_status(floor_block_ids, new_state)

    floor_label = dict(Block.FLOOR_CHOICES)[floor]
    status_label = 'فعال' if new_state else 'غیرفعال'
    messages.success(request, f'{updated} سکوی «{floor_label}» در ورزشگاه «{stadium.name}» {status_label} شد.')
    return redirect(f"{reverse('matches:admin_block_list')}?stadium_id={stadium.id}")


@staff_member_required
def toggle_seat_status(request, seat_id):
    seat = get_object_or_404(Seat, id=seat_id)
    seat.is_available = not seat.is_available
    seat.save()
    msg = f'وضعیت صندلی {seat.number} در ردیف {seat.row.number} تغییر کرد.'
    if seat.is_available and _reactivate_block_if_needed(seat.row.block):
        msg += ' بلوک هم به‌صورت خودکار فعال شد.'
    messages.success(request, msg)
    return redirect('matches:manage_block_seats', block_id=seat.row.block.id)


# ============================================================
#  مدیریت مسابقات (فقط ادمین)
# ============================================================

@staff_member_required
def admin_match_create(request):
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

    price_blocks = Block.objects.filter(stadium=match.stadium).order_by('order')
    price_overrides = dict(MatchBlockPrice.objects.filter(match=match).values_list('block_id', 'price'))
    for block in price_blocks:
        block.override_price = price_overrides.get(block.id)

    basa_discount = MatchBasaDiscount.objects.filter(match=match).first()

    return render(request, 'matches/admin_match_form.html', {
        'form': form, 'match': match, 'is_edit': True, 'price_blocks': price_blocks,
        'basa_discount': basa_discount,
    })


@staff_member_required
def admin_match_block_prices(request, match_id):
    """ذخیره‌ی قیمت اختصاصی هر بلوک برای این مسابقه -- خالی گذاشتن فیلد یعنی
    برگشت به قیمت پیش‌فرض بلوک. وارد کردن قیمت، هم override این مسابقه را
    ثبت می‌کند و هم قیمت پایه‌ی خود بلوک (Block.price) را همان مقدار
    می‌کند -- طبق درخواست ادمین، تا صفحه‌ی «مدیریت سکوها» هم قیمت تازه را
    نشان بدهد. نکته: چون Block.price بین همه‌ی مسابقات یک ورزشگاه مشترک
    است، این کار قیمت پیش‌فرض مسابقات دیگر آن ورزشگاه را هم عوض می‌کند
    مگر برای آن‌ها هم جداگانه قیمت اختصاصی تعیین شده باشد."""
    match = get_object_or_404(Match, id=match_id)
    if request.method != 'POST':
        return redirect('matches:admin_match_edit', match_id=match.id)

    blocks = Block.objects.filter(stadium=match.stadium)
    changed = 0
    for block in blocks:
        raw = request.POST.get(f'price_{block.id}', '').strip()
        if raw == '':
            deleted, _ = MatchBlockPrice.objects.filter(match=match, block=block).delete()
            if deleted:
                changed += 1
            continue
        try:
            price = Decimal(raw)
        except (InvalidOperation, ValueError):
            messages.error(request, f'قیمت وارد‌شده برای بلوک «{block.name}» معتبر نیست.')
            continue
        if price < 0:
            messages.error(request, f'قیمت بلوک «{block.name}» نمی‌تواند منفی باشد.')
            continue
        MatchBlockPrice.objects.update_or_create(match=match, block=block, defaults={'price': price})
        if block.price != price:
            block.price = price
            block.save(update_fields=['price'])
        changed += 1

    if changed:
        messages.success(request, 'قیمت بلیط‌های اختصاصی این مسابقه ذخیره شد.')
    return redirect('matches:admin_match_edit', match_id=match.id)


@staff_member_required
def admin_match_basa_discount(request, match_id):
    """ذخیره‌ی درصد تخفیف اعضای باسا برای این مسابقه -- خالی گذاشتن یعنی
    غیرفعال کردن تخفیف باسا برای این مسابقه."""
    match = get_object_or_404(Match, id=match_id)
    if request.method != 'POST':
        return redirect('matches:admin_match_edit', match_id=match.id)

    raw = request.POST.get('basa_discount_percent', '').strip()
    if raw == '':
        MatchBasaDiscount.objects.filter(match=match).delete()
        messages.success(request, 'تخفیف باسا برای این مسابقه غیرفعال شد.')
        return redirect('matches:admin_match_edit', match_id=match.id)

    try:
        percent = int(raw)
    except ValueError:
        messages.error(request, 'درصد تخفیف باسا باید عدد باشد.')
        return redirect('matches:admin_match_edit', match_id=match.id)

    if not (0 <= percent <= 100):
        messages.error(request, 'درصد تخفیف باسا باید بین ۰ تا ۱۰۰ باشد.')
        return redirect('matches:admin_match_edit', match_id=match.id)

    MatchBasaDiscount.objects.update_or_create(match=match, defaults={'discount_percent': percent})
    messages.success(request, f'تخفیف {percent}٪ برای اعضای باسا در این مسابقه فعال شد.')
    return redirect('matches:admin_match_edit', match_id=match.id)


@staff_member_required
def admin_match_delete(request, match_id):
    match = get_object_or_404(Match, id=match_id)
    if request.method == 'POST':
        match_name = f"{match.home_team} vs {match.away_team}"
        match.delete()
        messages.success(request, f'مسابقه "{match_name}" با موفقیت حذف شد.')
        return redirect('matches:admin_match_list')
    return render(request, 'matches/admin_match_confirm_delete.html', {'match': match})


@staff_member_required
def admin_match_cancel(request, match_id):
    """
    لغو کامل یک مسابقه: تمام بلیط‌های آن (فروخته‌شده و ویژه) باطل می‌شوند و
    مبلغ واقعی پرداختی هر خرید (Order.total_amount -- یعنی مبلغ نهایی پس از
    تخفیف، نه Ticket.price که پیش از تخفیف است) به کیف پول همان خریدار
    بازگردانده می‌شود. بلیط‌های ویژه (admin_assigned/vip_issued) چون از طریق
    سهمیه صادر شده‌اند نه خرید واقعی، بدون بازگشت وجه فقط باطل می‌شوند.
    """
    from tickets.models import Order
    from wallet.models import Wallet

    match = get_object_or_404(Match, id=match_id)

    if match.is_cancelled:
        messages.info(request, 'این مسابقه قبلاً لغو شده است.')
        return redirect('matches:admin_match_detail', match_id=match.id)

    if request.method == 'POST':
        with transaction.atomic():
            # قفل مسابقه تا از لغو دوباره/هم‌زمان (و بازگشت وجه دوباره) جلوگیری شود
            match = Match.objects.select_for_update().get(id=match_id)
            if match.is_cancelled:
                messages.info(request, 'این مسابقه قبلاً لغو شده است.')
                return redirect('matches:admin_match_detail', match_id=match.id)

            tickets = Ticket.objects.filter(
                match=match, status__in=['paid', 'admin_assigned', 'vip_issued']
            ).select_related('order', 'user')

            orders_refunded = set()
            affected_users = set()
            total_refunded = 0

            for ticket in tickets:
                if ticket.status != 'paid':
                    continue  # بلیط ویژه -- بدون بازگشت وجه

                if ticket.order_id:
                    if ticket.order_id in orders_refunded:
                        continue  # این سفارش (با چند بلیط) قبلاً برگشت داده شده
                    orders_refunded.add(ticket.order_id)
                    order = ticket.order
                    # اگر total_amount به هر دلیلی ثبت نشده باشد (مثلاً سفارش‌های قدیمی
                    # از مسیر خرید کاملاً با کیف پول که پیش‌تر total_amount را ۰ ثبت
                    # می‌کرد)، از روی subtotal/discount_amount که همیشه درست ثبت
                    # می‌شوند دوباره محاسبه می‌شود -- تا مبلغ بازگشتی مستقل از اینکه
                    # خرید با درگاه بوده یا کیف پول یا ترکیبی، همیشه کامل و درست باشد.
                    refund_amount = order.total_amount or (order.subtotal - order.discount_amount)
                    refund_user = order.user
                else:
                    # بلیط‌های قدیمی بدون سفارش ثبت‌شده -- برگشت بر اساس قیمت خودِ بلیط
                    refund_amount = ticket.price or 0
                    refund_user = ticket.user

                if refund_amount <= 0:
                    continue

                wallet, _ = Wallet.objects.get_or_create(user=refund_user)
                wallet.add_balance(
                    amount=refund_amount,
                    description=f"بازگشت وجه به دلیل لغو مسابقه {match.home_team} vs {match.away_team}",
                    reference_id=f"CANCEL-MATCH-{match.id}",
                    tx_type='refund',
                )
                affected_users.add(refund_user.id)
                total_refunded += refund_amount

            cancelled_count = tickets.update(status='cancelled')

            match.is_cancelled = True
            match.is_active = False
            match.ticket_sales_enabled = False
            match.cancelled_at = timezone.now()
            match.save(update_fields=['is_cancelled', 'is_active', 'ticket_sales_enabled', 'cancelled_at'])

        messages.success(
            request,
            f'مسابقه لغو شد. {cancelled_count} بلیط باطل شد و مجموعاً {total_refunded:,} ریال '
            f'به کیف پول {len(affected_users)} کاربر بازگشت داده شد.'
        )
        return redirect('matches:admin_match_detail', match_id=match.id)

    # ===== GET: صفحه‌ی تأیید همراه با پیش‌نمایش مبلغ بازگشتی =====
    paid_tickets_qs = Ticket.objects.filter(match=match, status='paid').select_related('order')
    order_ids = paid_tickets_qs.exclude(order__isnull=True).values_list('order_id', flat=True).distinct()
    estimated_refund = Order.objects.filter(id__in=order_ids).aggregate(total=Sum('total_amount'))['total'] or 0
    no_order_total = sum(t.price or 0 for t in paid_tickets_qs.filter(order__isnull=True))
    estimated_refund += no_order_total

    vip_count = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued']).count()

    context = {
        'match': match,
        'paid_count': paid_tickets_qs.count(),
        'vip_count': vip_count,
        'estimated_refund': estimated_refund,
    }
    return render(request, 'matches/admin_match_confirm_cancel.html', context)


# ============================================================
#  مدیریت ورزشگاه‌ها (فقط ادمین)
# ============================================================

@staff_member_required
def admin_stadium_list(request):
    stadiums = Stadium.objects.all().order_by('name')
    total_blocks = Block.objects.filter(is_active=True).count()
    total_seats = Seat.objects.filter(is_available=True).count()
    total_matches = Match.objects.filter(is_active=True).count()

    context = {
        'stadiums': stadiums,
        'total_blocks': total_blocks,
        'total_seats': total_seats,
        'total_matches': total_matches,
    }
    return render(request, 'matches/admin_stadium_list.html', context)


@staff_member_required
def admin_stadium_create(request):
    if request.method == 'POST':
        form = StadiumForm(request.POST, request.FILES)  # ← FILES اضافه شد
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
    stadium = get_object_or_404(Stadium, id=stadium_id)

    if request.method == 'POST':
        print("=" * 50)
        print("POST data:", request.POST)
        print("FILES data:", request.FILES)  # ← باید شامل تصویر باشد
        print("=" * 50)

        form = StadiumForm(request.POST, request.FILES, instance=stadium)  # ← FILES مهم است
        if form.is_valid():
            stadium = form.save()
            messages.success(request, f'ورزشگاه "{stadium.name}" با موفقیت ویرایش شد.')
            return redirect('matches:admin_stadium_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
            print("Form errors:", form.errors)
    else:
        form = StadiumForm(instance=stadium)

    return render(request, 'matches/admin_stadium_form.html', {
        'form': form,
        'stadium': stadium,
        'is_edit': True
    })


@staff_member_required
def admin_stadium_delete(request, stadium_id):
    stadium = get_object_or_404(Stadium, id=stadium_id)
    if request.method == 'POST':
        stadium_name = stadium.name
        stadium.delete()
        messages.success(request, f'ورزشگاه "{stadium_name}" با موفقیت حذف شد.')
        return redirect('matches:admin_stadium_list')

    return render(request, 'matches/admin_stadium_confirm_delete.html', {'stadium': stadium})


@staff_member_required
def admin_stadium_configure(request, stadium_id=None):
    stadium = None
    blocks_data = []

    if stadium_id:
        stadium = get_object_or_404(Stadium, id=stadium_id)
        blocks = Block.objects.filter(stadium=stadium, is_active=True).order_by('order')

        for block in blocks:
            rows = Row.objects.filter(block=block, is_active=True).order_by('number')
            patterns = []

            if rows.exists():
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

    if request.method == 'POST':
        stadium_name = request.POST.get('stadium_name', '').strip()
        stadium_capacity = request.POST.get('stadium_capacity', 0)
        block_count = request.POST.get('block_count', 0)
        stadium_image = request.FILES.get('stadium_image')

        if not stadium_name:
            messages.error(request, 'لطفاً نام ورزشگاه را وارد کنید.')
            return render(request, 'matches/admin_stadium_configure.html', {
                'stadium': stadium,
                'blocks_data': blocks_data,
            })

        try:
            stadium_capacity = int(stadium_capacity) if stadium_capacity else 0
        except ValueError:
            stadium_capacity = 0

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

        with transaction.atomic():
            try:
                if stadium:
                    stadium.name = stadium_name
                    stadium.capacity = stadium_capacity
                    if stadium_image:
                        stadium.image = stadium_image
                    stadium.save()
                    Block.objects.filter(stadium=stadium).delete()
                    messages.info(request, f'بلوک‌های قدیمی ورزشگاه "{stadium.name}" حذف شدند.')
                else:
                    stadium = Stadium.objects.create(
                        name=stadium_name,
                        capacity=stadium_capacity,
                        image=stadium_image
                    )

                # ===== ایجاد بلوک‌ها =====
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

                        for row_num in range(start_row, end_row + 1):
                            row = Row.objects.create(block=block, number=row_num, is_active=True)
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

    context = {
        'stadium': stadium,
        'blocks_data': blocks_data,
    }
    return render(request, 'matches/admin_stadium_configure.html', context)


@staff_member_required
def match_financial_report(request, match_id):
    """گزارش مالی یک مسابقه"""
    match = get_object_or_404(Match, id=match_id)

    report, created = MatchFinancialReport.objects.get_or_create(match=match)
    report.calculate()

    costs = MatchCost.objects.filter(match=match).order_by('-created_at')
    revenues = MatchRevenue.objects.filter(match=match).order_by('-created_at')

    tickets = Ticket.objects.filter(match=match, status='paid')
    vip_tickets = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued'])
    used_tickets = Ticket.objects.filter(match=match, is_used=True)

    context = {
        'match': match,
        'report': report,
        'costs': costs,
        'revenues': revenues,
        'tickets': tickets,
        'vip_tickets': vip_tickets,
        'used_tickets': used_tickets,
        'total_tickets': tickets.count() + vip_tickets.count(),
    }
    return render(request, 'matches/financial_report.html', context)


@staff_member_required
def match_financial_list(request):
    """لیست گزارش‌های مالی همه مسابقات"""
    matches = Match.objects.filter(is_active=True).order_by('-date_time')

    reports = []
    for match in matches:
        report, created = MatchFinancialReport.objects.get_or_create(match=match)
        report.calculate()
        reports.append({
            'match': match,
            'report': report,
        })

    context = {
        'reports': reports,
        'total_matches': matches.count(),
    }
    return render(request, 'matches/financial_report_list.html', context)


# ============================================================
#  مدیریت هزینه‌ها
# ============================================================

@staff_member_required
def add_match_cost(request, match_id):
    """افزودن هزینه به مسابقه"""
    match = get_object_or_404(Match, id=match_id)

    if request.method == 'POST':
        form = MatchCostForm(request.POST)
        if form.is_valid():
            cost = form.save(commit=False)
            cost.match = match
            cost.save()
            messages.success(request, f'هزینه "{cost.description}" با موفقیت اضافه شد.')
            return redirect('matches:financial_report', match_id=match.id)
    else:
        form = MatchCostForm()

    return render(request, 'matches/add_cost.html', {
        'form': form,
        'match': match,
        'type': 'cost'
    })


@staff_member_required
def edit_match_cost(request, cost_id):
    """ویرایش هزینه"""
    cost = get_object_or_404(MatchCost, id=cost_id)
    match = cost.match

    if request.method == 'POST':
        form = MatchCostForm(request.POST, instance=cost)
        if form.is_valid():
            form.save()
            messages.success(request, f'هزینه با موفقیت ویرایش شد.')
            return redirect('matches:financial_report', match_id=match.id)
    else:
        form = MatchCostForm(instance=cost)

    return render(request, 'matches/edit_cost.html', {
        'form': form,
        'match': match,
        'cost': cost
    })


@staff_member_required
def delete_match_cost(request, cost_id):
    """حذف هزینه"""
    cost = get_object_or_404(MatchCost, id=cost_id)
    match_id = cost.match.id

    if request.method == 'POST':
        cost.delete()
        messages.success(request, 'هزینه با موفقیت حذف شد.')
        return redirect('matches:financial_report', match_id=match_id)

    return render(request, 'matches/delete_confirm.html', {
        'object': cost,
        'type': 'هزینه'
    })


# ============================================================
#  مدیریت درآمدها
# ============================================================

@staff_member_required
def add_match_revenue(request, match_id):
    """افزودن درآمد به مسابقه"""
    match = get_object_or_404(Match, id=match_id)

    if request.method == 'POST':
        form = MatchRevenueForm(request.POST)
        if form.is_valid():
            revenue = form.save(commit=False)
            revenue.match = match
            revenue.save()
            messages.success(request, f'درآمد "{revenue.description}" با موفقیت اضافه شد.')
            return redirect('matches:financial_report', match_id=match.id)
    else:
        form = MatchRevenueForm()

    return render(request, 'matches/add_revenue.html', {
        'form': form,
        'match': match,
        'type': 'revenue'
    })


@staff_member_required
def edit_match_revenue(request, revenue_id):
    """ویرایش درآمد"""
    revenue = get_object_or_404(MatchRevenue, id=revenue_id)
    match = revenue.match

    if request.method == 'POST':
        form = MatchRevenueForm(request.POST, instance=revenue)
        if form.is_valid():
            form.save()
            messages.success(request, f'درآمد با موفقیت ویرایش شد.')
            return redirect('matches:financial_report', match_id=match.id)
    else:
        form = MatchRevenueForm(instance=revenue)

    return render(request, 'matches/edit_revenue.html', {
        'form': form,
        'match': match,
        'revenue': revenue
    })


@staff_member_required
def delete_match_revenue(request, revenue_id):
    """حذف درآمد"""
    revenue = get_object_or_404(MatchRevenue, id=revenue_id)
    match_id = revenue.match.id

    if request.method == 'POST':
        revenue.delete()
        messages.success(request, 'درآمد با موفقیت حذف شد.')
        return redirect('matches:financial_report', match_id=match_id)

    return render(request, 'matches/delete_confirm.html', {
        'object': revenue,
        'type': 'درآمد'
    })


# ============================================================
#  خروجی PDF
# ============================================================

@staff_member_required
def export_financial_report_pdf(request, match_id):
    """خروجی PDF گزارش مالی مسابقه"""
    match = get_object_or_404(Match, id=match_id)
    report, created = MatchFinancialReport.objects.get_or_create(match=match)
    report.calculate()

    tickets = Ticket.objects.filter(match=match, status='paid')
    vip_tickets = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued'])
    used_tickets = Ticket.objects.filter(match=match, is_used=True)
    costs = MatchCost.objects.filter(match=match)
    revenues = MatchRevenue.objects.filter(match=match)

    context = {
        'match': match,
        'report': report,
        'tickets': tickets,
        'vip_tickets': vip_tickets,
        'used_tickets': used_tickets,
        'costs': costs,
        'revenues': revenues,
        'total_tickets': tickets.count() + vip_tickets.count(),
        'today': timezone.now(),
        'vazirmatn_dir': os.path.join(settings.BASE_DIR, 'static', 'vendor', 'vazirmatn', 'webfonts'),
    }

    # ===== تنظیم base_url برای دسترسی به تصاویر =====
    html_string = render_to_string('matches/financial_report_pdf.html', context)
    html = HTML(string=html_string, base_url=settings.MEDIA_ROOT)  # ← تغییر به MEDIA_ROOT

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="گزارش_مالی_{match.home_team}_vs_{match.away_team}.pdf"'

    html.write_pdf(target=response)
    return response
