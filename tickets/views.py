# tickets/views.py
import json
import zipfile
from io import BytesIO
from datetime import timedelta
import logging
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.db import transaction
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.db.models import Count
from django.views.decorators.csrf import csrf_exempt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
import pytz

import matches
from .models import Ticket, VIPQuota, DiscountCode
from .forms import BulkTicketForm, VIPQuotaForm, DiscountCodeForm
from .reservation import SeatReservation
from matches.models import Match, Seat, Row, MatchSeat, Block
from accounts.models import User


# ============================================================
#  ویوهای عمومی (کاربران عادی و VIP)
# ============================================================

@login_required
def user_tickets(request):
    """
    نمایش بلیط‌های کاربر در بخش «بلیط‌های من» با قابلیت فیلتر بر اساس وضعیت
    """
    match_id = request.GET.get('match_id')
    status_filter = request.GET.get('status')  # new: paid, admin_assigned, vip_issued

    # کوئری پایه بر اساس نوع کاربر
    if request.user.user_type == 'vip':
        tickets_qs = Ticket.objects.filter(
            user=request.user,
            status__in=['paid', 'admin_assigned', 'vip_issued']
        ).order_by('-purchase_date')
    else:
        tickets_qs = Ticket.objects.filter(
            user=request.user,
            status='paid'
        ).order_by('-purchase_date')

    # اعمال فیلتر مسابقه
    if match_id:
        tickets_qs = tickets_qs.filter(match_id=match_id)

    # اعمال فیلتر وضعیت (فقط برای VIP)
    if status_filter and request.user.user_type == 'vip':
        if status_filter in ['paid', 'admin_assigned', 'vip_issued']:
            tickets_qs = tickets_qs.filter(status=status_filter)

    local_tz = pytz.timezone('Asia/Tehran')
    for ticket in tickets_qs:
        if ticket.used_at:
            ticket.used_at_local = ticket.used_at.astimezone(local_tz)
        else:
            ticket.used_at_local = None
    matches = Match.objects.filter(is_active=True).order_by('-date_time')

    context = {
        'tickets': tickets_qs,
        'matches': matches,
        'selected_match_id': int(match_id) if match_id else None,
        'selected_status': status_filter,
    }
    return render(request, 'tickets/user_tickets.html', context)


@login_required
def vip_tickets(request):
    if request.user.user_type != 'vip':
        messages.error(request, 'شما دسترسی به این بخش ندارید.')
        return redirect('matches:home')  # ← این redirect نباید به خودش باشه

    match_id = request.GET.get('match_id')
    tickets_qs = Ticket.objects.filter(
        user=request.user,
        is_admin_assigned=True,
        status='admin_assigned'
    ).order_by('-purchase_date')
    if match_id:
        tickets_qs = tickets_qs.filter(match_id=match_id)

    matches = Match.objects.filter(is_active=True).order_by('-date_time')
    context = {
        'tickets': tickets_qs,
        'matches': matches,
        'selected_match_id': int(match_id) if match_id else None,
    }
    return render(request, 'tickets/vip_tickets.html', context)


@login_required
def vip_dashboard(request):
    """داشبورد کاربر ویژه - نمایش ظرفیت‌ها (با فیلتر مسابقه)"""
    if request.user.user_type != 'vip':
        messages.error(request, 'شما دسترسی به این بخش ندارید.')
        return redirect('matches:home')

    match_id = request.GET.get('match_id')
    quotas_qs = VIPQuota.objects.filter(user=request.user).select_related('match')
    if match_id:
        quotas_qs = quotas_qs.filter(match_id=match_id)

    matches = Match.objects.filter(is_active=True).order_by('-date_time')
    available_matches = Match.objects.filter(
        id__in=quotas_qs.values_list('match_id', flat=True)
    ).order_by('-date_time')

    context = {
        'quotas': quotas_qs,
        'matches': available_matches,
        'all_matches': matches,
        'selected_match_id': int(match_id) if match_id else None,
    }
    return render(request, 'tickets/vip_dashboard.html', context)


@login_required
def vip_issued_tickets(request):
    """
    نمایش بلیط‌های صادرشده توسط کاربر ویژه (بخش مخصوص خودش)
    اگر پارامتر match_id در URL باشد، فقط بلیط‌های آن مسابقه نمایش داده می‌شوند.
    """
    if request.user.user_type != 'vip':
        messages.error(request, 'شما دسترسی به این بخش ندارید.')
        return redirect('matches:home')

    # دریافت فیلتر مسابقه از GET
    match_id = request.GET.get('match_id')

    # کوئری پایه: بلیط‌های صادرشده توسط این کاربر
    tickets_qs = Ticket.objects.filter(
        user=request.user,
        status='vip_issued'
    ).order_by('-purchase_date')

    # اعمال فیلتر مسابقه (در صورت وجود)
    selected_match = None
    if match_id:
        tickets_qs = tickets_qs.filter(match_id=match_id)
        selected_match = get_object_or_404(Match, id=match_id)

    # لیست مسابقات برای نمایش در فیلتر (اختیاری)
    matches = Match.objects.filter(is_active=True).order_by('-date_time')

    # ===== اگر بلیطی وجود نداشته باشد =====
    if not tickets_qs.exists() and not match_id:
        messages.info(request, 'هیچ بلیط صادرشده‌ای یافت نشد.')
    elif not tickets_qs.exists() and match_id:
        messages.info(request, f'هیچ بلیطی برای مسابقه "{selected_match}" صادر نشده است.')

    context = {
        'tickets': tickets_qs,
        'matches': matches,
        'selected_match': selected_match,
        'selected_match_id': int(match_id) if match_id else None,
    }
    return render(request, 'tickets/vip_issued_tickets.html', context)


# ============================================================
#  ویوهای مربوط به صدور بلیط توسط کاربر ویژه (VIP)
# ============================================================

@login_required
def vip_issue_manual(request, match_id):
    """
    صدور خودکار بلیط توسط کاربر ویژه (بدون انتخاب صندلی)
    پس از صدور، به صفحه بلیط‌های صادرشده با فیلتر همان مسابقه هدایت می‌شود.
    """
    # ===== بررسی دسترسی =====
    if request.user.user_type != 'vip':
        messages.error(request, 'شما دسترسی به این بخش ندارید.')
        return redirect('matches:home')

    match = get_object_or_404(Match, id=match_id, is_active=True)
    quota = get_object_or_404(VIPQuota, user=request.user, match=match)

    if quota.remaining <= 0:
        messages.error(request, 'ظرفیت شما برای این مسابقه تکمیل شده است.')
        return redirect('tickets:vip_dashboard')

    # ===== ۱. ایجاد خودکار MatchSeat برای صندلی‌هایی که وجود ندارند =====
    all_seats = Seat.objects.filter(row__is_active=True)
    existing_match_seats = MatchSeat.objects.filter(match=match, seat__in=all_seats)
    existing_seat_ids = existing_match_seats.values_list('seat_id', flat=True)

    missing_seat_ids = all_seats.exclude(id__in=existing_seat_ids).values_list('id', flat=True)
    if missing_seat_ids:
        new_match_seats = [
            MatchSeat(match=match, seat_id=seat_id, is_available=True)
            for seat_id in missing_seat_ids
        ]
        MatchSeat.objects.bulk_create(new_match_seats)

    # ===== ۲. پیدا کردن اولین صندلی خالی =====
    available_seat = MatchSeat.objects.filter(
        match=match,
        is_available=True
    ).select_related('seat', 'seat__row').order_by(
        'seat__row__block__order',
        'seat__row__number',
        'seat__number'
    ).first()

    # ===== ۳. پردازش فرم (POST) =====
    if request.method == 'POST':
        full_name = request.POST.get('full_name')
        national_code = request.POST.get('national_code')

        if not full_name or not national_code:
            messages.error(request, 'لطفاً تمام اطلاعات را وارد کنید.')
            return redirect('tickets:vip_issue_manual', match_id=match_id)

        if len(national_code) != 10 or not national_code.isdigit():
            messages.error(request, 'کد ملی باید ۱۰ رقم باشد.')
            return redirect('tickets:vip_issue_manual', match_id=match_id)

        if not available_seat:
            messages.error(request, 'هیچ صندلی خالی برای این مسابقه موجود نیست.')
            return redirect('tickets:vip_dashboard')

        with transaction.atomic():
            # قفل کردن صندلی برای جلوگیری از race condition
            match_seat = MatchSeat.objects.select_for_update().get(id=available_seat.id)
            if not match_seat.is_available:
                messages.error(request, 'صندلی انتخاب‌شده قبلاً پر شده است. لطفاً دوباره تلاش کنید.')
                return redirect('tickets:vip_issue_manual', match_id=match_id)

            ticket = Ticket.objects.create(
                user=request.user,
                match=match,
                seat=match_seat.seat,
                match_seat=match_seat,
                full_name=full_name,
                national_code=national_code,
                status='vip_issued',
                is_admin_assigned=False,
            )

            match_seat.is_available = False
            match_seat.save()

            quota.used += 1
            quota.save()

        messages.success(
            request,
            f'✅ بلیط برای {full_name} با موفقیت صادر شد.\n'
            f'ردیف: {match_seat.seat.row.name} - صندلی: {match_seat.seat.number}'
        )

        # ===== هدایت به صفحه بلیط‌های صادرشده (بخش مخصوص کاربر ویژه) =====
        return redirect(f'{reverse("tickets:vip_issued_tickets")}?match_id={match.id}')

    # ===== ۴. نمایش فرم (GET) =====
    context = {
        'match': match,
        'quota': quota,
        'available_seat': available_seat,
    }
    return render(request, 'tickets/vip_issue_manual.html', context)


@login_required
def vip_issue_excel(request, match_id):
    """
    صدور بلیط توسط کاربر ویژه از طریق فایل اکسل (خودکار)
    پس از صدور، به صفحه بلیط‌های صادرشده با فیلتر همان مسابقه هدایت می‌شود.
    """
    if request.user.user_type != 'vip':
        messages.error(request, 'شما دسترسی به این بخش ندارید.')
        return redirect('matches:home')

    match = get_object_or_404(Match, id=match_id, is_active=True)
    quota = get_object_or_404(VIPQuota, user=request.user, match=match)

    if quota.remaining <= 0:
        messages.error(request, 'ظرفیت شما برای این مسابقه تکمیل شده است.')
        return redirect('tickets:vip_dashboard')

    # ===== پردازش فایل اکسل =====
    if request.method == 'POST' and request.FILES.get('excel_file'):
        try:
            import pandas as pd
            excel_file = request.FILES['excel_file']
            df = pd.read_excel(excel_file)

            required_columns = ['نام و نام خانوادگی', 'کد ملی']
            if not all(col in df.columns for col in required_columns):
                messages.error(
                    request,
                    'فایل باید شامل ستون‌های "نام و نام خانوادگی" و "کد ملی" باشد.'
                )
                return redirect('tickets:vip_issue_excel', match_id=match_id)

            # دریافت صندلی‌های خالی
            available_match_seats = list(
                MatchSeat.objects.filter(match=match, is_available=True)
                .select_related('seat')
                .order_by('seat__row__block__order', 'seat__row__number', 'seat__number')
            )

            if len(available_match_seats) < len(df):
                messages.error(
                    request,
                    f'تعداد صندلی‌های موجود ({len(available_match_seats)}) '
                    f'کمتر از تعداد درخواست‌ها ({len(df)}) است.'
                )
                return redirect('tickets:vip_issue_excel', match_id=match_id)

            if len(df) > quota.remaining:
                messages.error(
                    request,
                    f'ظرفیت باقی‌مانده شما ({quota.remaining}) '
                    f'کمتر از تعداد درخواست‌ها ({len(df)}) است.'
                )
                return redirect('tickets:vip_issue_excel', match_id=match_id)

            with transaction.atomic():
                created = 0
                for _, row_data in df.iterrows():
                    full_name = str(row_data['نام و نام خانوادگی']).strip()
                    national_code = str(row_data['کد ملی']).strip()

                    if not full_name or not national_code or len(national_code) != 10:
                        continue

                    match_seat = available_match_seats[created]

                    ticket = Ticket.objects.create(
                        user=request.user,
                        match=match,
                        seat=match_seat.seat,
                        match_seat=match_seat,
                        full_name=full_name,
                        national_code=national_code,
                        status='vip_issued',
                        is_admin_assigned=False,
                    )
                    ticket.save()

                    match_seat.is_available = False
                    match_seat.save()
                    created += 1

                quota.used += created
                quota.save()

            messages.success(request, f'✅ {created} بلیط با موفقیت از فایل اکسل صادر شد.')

            # ===== هدایت به صفحه بلیط‌های صادرشده (بخش مخصوص کاربر ویژه) =====
            return redirect(f'{reverse("tickets:vip_issued_tickets")}?match_id={match.id}')

        except Exception as e:
            messages.error(request, f'❌ خطا در خواندن فایل: {str(e)}')
            return redirect('tickets:vip_issue_excel', match_id=match_id)

    # ===== نمایش فرم (GET) =====
    context = {
        'match': match,
        'quota': quota,
    }
    return render(request, 'tickets/vip_issue_excel.html', context)


# ============================================================
#  ویوهای مربوط به خرید (کاربران عادی) – با Redis
# ============================================================

logger = logging.getLogger(__name__)


@login_required
def select_seats(request, match_id):
    """نمایش صندلی‌های یک ردیف و لغو رزروهای قبلی در صورت بازگشت"""
    match = get_object_or_404(Match, id=match_id, is_active=True)
    row_id = request.session.get('selected_row_id')
    if not row_id:
        messages.error(request, 'لطفاً ابتدا یک ردیف را انتخاب کنید.')
        return redirect('matches:select_block', match_id=match_id)
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه امکان خرید بلیط ندارند.')
        return redirect('matches:home')

    match = get_object_or_404(Match, id=match_id, is_active=True)
    section_id = request.session.get('section_id')
    if not section_id:
        messages.error(request, 'لطفاً ابتدا ردیف را انتخاب کنید.')
        return redirect('matches:block_map', match_id=match_id)

    row = get_object_or_404(Row, id=section_id, is_active=True)

    # لغو رزروهای قبلی در صورت بازگشت
    if request.session.get('selected_seats'):
        old_seats = request.session.get('selected_seats', [])
        with transaction.atomic():
            for seat_id in old_seats:
                try:
                    ms = MatchSeat.objects.get(id=seat_id, match=match)
                    ms.is_available = True
                    ms.reserved_until = None
                    ms.save()
                except MatchSeat.DoesNotExist:
                    pass
                SeatReservation.release(seat_id)
        request.session.pop('selected_seats', None)
        request.session.pop('match_id', None)
        request.session.pop('section_id', None)
        request.session.pop('reserved_at', None)
        messages.info(request, 'رزروهای قبلی شما به دلیل بازگشت به این صفحه لغو شد.')

    match_seats = MatchSeat.objects.filter(match=match, seat__row=row).select_related('seat', 'seat__row').order_by(
        'seat__number')
    if not match_seats.exists():
        messages.warning(request, 'هیچ صندلی‌ای برای این ردیف در این مسابقه تعریف نشده است.')
        return redirect('matches:block_map', match_id=match_id)

    request.session['match_id'] = match_id
    request.session['row_id'] = row.id

    return render(request, 'matches/select_seats.html', {
        'match': match,
        'row': row,
        'match_seats': match_seats,
    })


@login_required
def reserve_seats(request, match_id):
    """
    رزرو صندلی‌های انتخاب‌شده با Redis و هدایت به ticket_info
    (هماهنگ با ساختار جدید بلوک‌ها و نقشه)
    """
    # ===== ۱. جلوگیری از خرید VIP =====
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه امکان خرید بلیط ندارند.')
        return redirect('matches:home')

    # ===== ۲. دریافت مسابقه =====
    match = get_object_or_404(Match, id=match_id, is_active=True)

    # ===== ۳. دریافت row_id =====
    # اولویت با POST (از فرم نقشه)، سپس session (برای سازگاری)
    row_id = request.POST.get('row_id') or request.session.get('selected_row_id')
    if not row_id:
        messages.error(request, 'لطفاً ابتدا یک ردیف را انتخاب کنید.')
        # کاربر را به صفحه انتخاب بلوک برگردانید (چون ردیف در همان نقشه انتخاب می‌شود)
        return redirect('matches:select_block', match_id=match_id)

    # ===== ۴. فقط POST =====
    if request.method != 'POST':
        return redirect('matches:block_map', match_id=match_id)  # هدایت به نقشه

    # ===== ۵. دریافت لیست صندلی‌ها =====
    selected_seats_data = request.POST.get('selected_seats')
    if not selected_seats_data:
        messages.error(request, 'هیچ صندلی‌ای انتخاب نشده است.')
        return redirect('matches:block_map', match_id=match_id)

    try:
        selected_seats = json.loads(selected_seats_data)
        if len(selected_seats) > 5:
            messages.error(request, 'حداکثر ۵ بلیط مجاز است.')
            return redirect('matches:block_map', match_id=match_id)
    except json.JSONDecodeError:
        messages.error(request, 'خطا در اطلاعات ارسال شده.')
        return redirect('matches:block_map', match_id=match_id)

    # ===== ۶. رزرو صندلی‌ها با Redis و دیتابیس =====
    reserved_seats = []
    try:
        with transaction.atomic():
            for seat_id in selected_seats:
                # اگر قبلاً توسط خود کاربر رزرو شده، نادیده بگیر
                if SeatReservation.is_reserved_by_user(seat_id, request.user.id):
                    continue

                try:
                    match_seat = MatchSeat.objects.get(id=seat_id, match=match, is_available=True)
                except MatchSeat.DoesNotExist:
                    # رزروهای قبلی را آزاد کن
                    for rid in reserved_seats:
                        SeatReservation.release(rid)
                    messages.error(request, 'یکی از صندلی‌های انتخاب‌شده معتبر نیست یا قبلاً فروخته شده است.')
                    return redirect('matches:block_map', match_id=match_id)

                success, msg = SeatReservation.reserve(seat_id, request.user.id, match_id)
                if not success:
                    for rid in reserved_seats:
                        SeatReservation.release(rid)
                    messages.error(request, msg)
                    return redirect('matches:block_map', match_id=match_id)

                # غیرفعال کردن MatchSeat در دیتابیس
                match_seat.is_available = False
                match_seat.reserved_until = timezone.now() + timedelta(seconds=settings.SEAT_RESERVATION_TIMEOUT)
                match_seat.save()
                reserved_seats.append(seat_id)

    except Exception as e:
        for rid in reserved_seats:
            SeatReservation.release(rid)
        logger.error(f"Error in reserve_seats: {str(e)}")
        messages.error(request, f'خطا در رزرو: {str(e)}')
        return redirect('matches:block_map', match_id=match_id)

    # ===== ۷. ذخیره در session =====
    request.session['selected_seats'] = selected_seats
    request.session['match_id'] = match_id
    request.session['section_id'] = row_id
    request.session['reserved_at'] = timezone.now().isoformat()

    # ===== ۸. هدایت به صفحه اطلاعات خریدار =====
    return redirect('tickets:ticket_info', match_id=match_id)


@login_required
def ticket_info(request, match_id):
    if request.user.user_type == 'vip':
        messages.error(request, 'کاربران ویژه امکان خرید بلیط ندارند.')
        return redirect('matches:home')

    match = get_object_or_404(Match, id=match_id, is_active=True)
    selected_seats = request.session.get('selected_seats', [])

    if not selected_seats:
        messages.error(request, 'ابتدا صندلی‌ها را انتخاب کنید.')
        return redirect('matches:block_map', match_id=match_id)

    # ===== بررسی رزرو =====
    for seat_id in selected_seats:
        redis_ok = SeatReservation.is_reserved(seat_id)
        if not redis_ok:
            try:
                ms = MatchSeat.objects.get(id=seat_id, match=match)
                db_ok = (not ms.is_available) and (
                        ms.reserved_until is None or ms.reserved_until > timezone.now()
                )
            except MatchSeat.DoesNotExist:
                db_ok = False

            if not db_ok:
                with transaction.atomic():
                    for sid in selected_seats:
                        try:
                            ms2 = MatchSeat.objects.get(id=sid, match=match)
                            ms2.is_available = True
                            ms2.reserved_until = None
                            ms2.save()
                        except MatchSeat.DoesNotExist:
                            pass
                request.session.pop('selected_seats', None)
                request.session.pop('reserved_at', None)
                messages.error(request, 'رزرو یکی از صندلی‌ها منقضی شده است. لطفاً دوباره انتخاب کنید.')
                return redirect('matches:block_map', match_id=match_id)

    # ===== محاسبه زمان باقی‌مانده =====
    reserved_at = request.session.get('reserved_at')
    remaining_time = 0
    if reserved_at:
        from datetime import datetime
        reserved_time = datetime.fromisoformat(reserved_at)
        elapsed = (timezone.now() - reserved_time).total_seconds()
        remaining_time = max(0, int(settings.SEAT_RESERVATION_TIMEOUT - elapsed))

    if remaining_time <= 0 and reserved_at:
        return redirect('tickets:cancel_reservation', match_id=match_id)

    # ===== دریافت اطلاعات صندلی‌ها با قیمت =====
    seats_data = []
    total_price = 0
    for seat_id in selected_seats:
        try:
            match_seat = MatchSeat.objects.select_related('seat__row__block').get(id=seat_id, match=match)

            # قیمت هر صندلی از بلوک مربوطه
            block = match_seat.seat.row.block
            price = int(block.price) if block.price else 0

            seats_data.append({
                'id': match_seat.id,
                'number': match_seat.seat.number,
                'row_name': match_seat.seat.row.name,
                'is_home': match_seat.seat.row.is_home,
                'price': price,  # ← قیمت هر صندلی
                'zone_label': match_seat.seat.row.zone_label,
            })
            total_price += price
        except MatchSeat.DoesNotExist:
            messages.error(request, 'یکی از صندلی‌های انتخاب‌شده معتبر نیست.')
            return redirect('matches:block_map', match_id=match_id)

    # ===== پردازش فرم (POST) =====
    if request.method == 'POST':
        with transaction.atomic():
            tickets = []
            for seat_data in seats_data:
                match_seat_id = seat_data['id']
                full_name = request.POST.get(f'full_name_{match_seat_id}')
                national_code = request.POST.get(f'national_code_{match_seat_id}')

                if not full_name or not national_code:
                    messages.error(request, 'لطفاً تمام اطلاعات را وارد کنید.')
                    return render(request, 'tickets/ticket_info.html', {
                        'match': match,
                        'seats_data': seats_data,
                        'total_price': total_price,
                        'remaining_time': remaining_time,
                    })
                if len(national_code) != 10:
                    messages.error(request, 'کد ملی باید ۱۰ رقم باشد.')
                    return render(request, 'tickets/ticket_info.html', {
                        'match': match,
                        'seats_data': seats_data,
                        'total_price': total_price,
                        'remaining_time': remaining_time,
                    })

                try:
                    match_seat = MatchSeat.objects.get(id=match_seat_id, match=match)
                except MatchSeat.DoesNotExist:
                    messages.error(request, 'صندلی مورد نظر معتبر نیست یا قبلاً فروخته شده است.')
                    return redirect('matches:block_map', match_id=match_id)

                if match_seat.reserved_until and match_seat.reserved_until < timezone.now():
                    match_seat.is_available = True
                    match_seat.reserved_until = None
                    match_seat.save()
                    SeatReservation.release(match_seat_id)
                    messages.error(request, f'مدت زمان رزرو صندلی {match_seat.seat.number} به پایان رسیده است.')
                    return redirect('matches:block_map', match_id=match_id)

                ticket = Ticket.objects.create(
                    user=request.user,
                    match=match,
                    seat=match_seat.seat,
                    match_seat=match_seat,
                    full_name=full_name,
                    national_code=national_code,
                    status='paid',
                    is_admin_assigned=False,
                )
                ticket.save()
                tickets.append(ticket)

                match_seat.is_available = False
                match_seat.reserved_until = None
                match_seat.save()
                SeatReservation.release(match_seat_id)

            request.session.pop('selected_seats', None)
            request.session.pop('match_id', None)
            request.session.pop('section_id', None)
            request.session.pop('reserved_at', None)

            messages.success(request, f'{len(tickets)} بلیط با موفقیت صادر شد.')
            return redirect('tickets:user_tickets')

    return render(request, 'tickets/ticket_info.html', {
        'match': match,
        'seats_data': seats_data,
        'total_price': total_price,  # ← مجموع قیمت
        'remaining_time': remaining_time,
    })


# ============================================================
#  لغو خرید و آزادسازی رزرو
# ============================================================

@login_required
def cancel_reservation(request, match_id):
    """لغو خرید و آزادسازی رزروها (بدون تراکنش اتمی)"""
    match = get_object_or_404(Match, id=match_id, is_active=True)
    selected_seats = request.session.get('selected_seats', [])

    if selected_seats:
        for seat_id in selected_seats:
            # آزادسازی در دیتابیس (بدون تراکنش اتمی)
            try:
                match_seat = MatchSeat.objects.get(id=seat_id, match=match)
                match_seat.is_available = True
                match_seat.reserved_until = None
                match_seat.save(update_fields=['is_available', 'reserved_until'])
            except MatchSeat.DoesNotExist:
                pass
            # آزادسازی در Redis
            SeatReservation.release(seat_id)

        # پاک کردن session
        request.session.pop('selected_seats', None)
        request.session.pop('match_id', None)
        request.session.pop('section_id', None)
        request.session.pop('reserved_at', None)

        messages.info(request, 'عملیات خرید لغو شد و صندلی‌ها آزاد شدند.')

    return redirect('matches:select_block', match_id=match_id)


@login_required
@csrf_exempt
def release_reservation(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

    match_id = request.POST.get('match_id')
    if not match_id:
        return JsonResponse({'status': 'error', 'message': 'match_id required'}, status=400)

    try:
        match = Match.objects.get(id=match_id)
    except Match.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Match not found'}, status=404)

    selected_seats = request.session.get('selected_seats', [])
    if not selected_seats:
        return JsonResponse({'status': 'ok', 'message': 'No active reservation'})

    with transaction.atomic():
        for seat_id in selected_seats:
            try:
                match_seat = MatchSeat.objects.get(id=seat_id, match=match)
                # ← اگر بلیط پرداخت‌شده دارد، آزاد نکن
                has_paid_ticket = Ticket.objects.filter(
                    match_seat=match_seat,
                    status='paid'
                ).exists()
                if not has_paid_ticket:
                    match_seat.is_available = True
                    match_seat.reserved_until = None
                    match_seat.save()
                    SeatReservation.release(seat_id)
            except MatchSeat.DoesNotExist:
                pass

    request.session.pop('selected_seats', None)
    request.session.pop('match_id', None)
    request.session.pop('section_id', None)
    request.session.pop('reserved_at', None)

    return JsonResponse({'status': 'ok', 'message': 'Reservation released'})


# ============================================================
#  ویوهای مخصوص ادمین (مدیریت و گزارشات)
# ============================================================

@staff_member_required
def sales_report(request):
    """گزارش فروش بلیط‌ها با نمودار - درآمد فقط از بلیط‌های فروخته‌شده (paid)"""

    # دریافت فیلترها
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    match_id = request.GET.get('match_id')

    # دریافت مسابقات با فیلتر
    matches_qs = Match.objects.all().order_by('-date_time')
    if match_id:
        matches_qs = matches_qs.filter(id=match_id)
    if start_date:
        matches_qs = matches_qs.filter(date_time__date__gte=start_date)
    if end_date:
        matches_qs = matches_qs.filter(date_time__date__lte=end_date)

    # محاسبه داده‌های فروش
    sales_data = []
    total_sold = 0
    total_vip = 0
    total_tickets = 0
    total_revenue = 0  # فقط از بلیط‌های فروخته‌شده (paid)

    for match in matches_qs:
        sold_tickets = Ticket.objects.filter(match=match, status='paid')
        vip_tickets = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued'])

        sold_count = sold_tickets.count()
        vip_count = vip_tickets.count()

        # ===== درآمد فقط از بلیط‌های فروخته‌شده (paid) =====
        revenue = sum(
            t.seat.row.block.price for t in sold_tickets
            if t.seat and t.seat.row and t.seat.row.block
        )
        vip_revenue = sum(
            t.seat.row.block.price for t in vip_tickets
            if t.seat and t.seat.row and t.seat.row.block
        )

        occupied = MatchSeat.objects.filter(match=match, is_available=False).count()
        total = MatchSeat.objects.filter(match=match).count()

        sales_data.append({
            'match': match,
            'sold_count': sold_count,
            'vip_count': vip_count,
            'total_tickets': sold_count + vip_count,
            'revenue': revenue,  # ← فقط درآمد فروش
            'vip_revenue': vip_revenue,  # ← درآمد VIP (برای نمایش جداگانه)
            'occupancy_percent': round((occupied / total * 100) if total > 0 else 0, 1),
        })

        total_sold += sold_count
        total_vip += vip_count
        total_tickets += sold_count + vip_count
        total_revenue += revenue  # ← فقط فروش (paid)

    # صفحه‌بندی
    paginator = Paginator(sales_data, 10)
    page = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    context = {
        'sales_data': page_obj,
        'page_obj': page_obj,
        'total_sold': total_sold,
        'total_vip': total_vip,
        'total_tickets': total_tickets,
        'total_revenue': total_revenue,  # ← فقط درآمد فروش
        'average_price': total_revenue / total_sold if total_sold > 0 else 0,
        'period_days': (timezone.now().date() - timezone.datetime.strptime(start_date,
                                                                           '%Y-%m-%d').date()).days if start_date else 30,
        'matches': Match.objects.all().order_by('-date_time'),
        'selected_match_id': int(match_id) if match_id else None,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'tickets/sales_report.html', context)


@login_required
@staff_member_required
def bulk_issue_tickets(request):
    """صدور گروهی بلیط برای کاربران ویژه توسط ادمین (با انتخاب بلوک)"""
    if request.method == 'POST':
        form = BulkTicketForm(request.POST)
        if form.is_valid():
            match = form.cleaned_data['match']
            users = form.cleaned_data['users']
            block = form.cleaned_data['block']
            count_per_user = form.cleaned_data['seat_count_per_user']

            # ===== دریافت MatchSeatهای موجود در کل بلوک =====
            available_match_seats = MatchSeat.objects.filter(
                match=match,
                seat__row__block=block,
                is_available=True
            ).select_related('seat').order_by('seat__row__number', 'seat__number')

            total_needed = users.count() * count_per_user
            if available_match_seats.count() < total_needed:
                messages.error(
                    request,
                    f'تعداد صندلی‌های موجود در بلوک "{block.name}" ({available_match_seats.count()}) کافی نیست. '
                    f'به {total_needed} صندلی نیاز است.'
                )
                return render(request, 'tickets/bulk_issue.html', {'form': form})

            # ===== صدور بلیط‌ها =====
            with transaction.atomic():
                ticket_index = 0
                created_count = 0
                match_seats_list = list(available_match_seats)

                for user in users:
                    for _ in range(count_per_user):
                        if ticket_index >= len(match_seats_list):
                            break
                        match_seat = match_seats_list[ticket_index]
                        ticket_index += 1

                        # ایجاد بلیط
                        ticket = Ticket.objects.create(
                            user=user,
                            match=match,
                            seat=match_seat.seat,
                            match_seat=match_seat,
                            full_name=user.get_full_name() or user.username,
                            national_code=user.national_code,
                            status='admin_assigned',
                            is_admin_assigned=True,
                        )
                        ticket.save()

                        # غیرفعال کردن MatchSeat
                        match_seat.is_available = False
                        match_seat.save()

                        created_count += 1

                messages.success(
                    request,
                    f'{created_count} بلیط برای {users.count()} کاربر ویژه از بلوک "{block.name}" صادر شد.'
                )
                return redirect('tickets:bulk_issue')

        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{error}')
    else:
        form = BulkTicketForm()

    return render(request, 'tickets/bulk_issue.html', {'form': form})


@login_required
@staff_member_required
def manage_vip_users(request):
    """مدیریت کاربران ویژه - نمایش تعداد بلیط‌های تخصیص‌یافته به تفکیک مسابقه"""
    match_id = request.GET.get('match_id')
    matches = Match.objects.filter(is_active=True).order_by('-date_time')
    vip_users = User.objects.filter(user_type='vip').order_by('username')

    user_data = []
    for user in vip_users:
        tickets_qs = Ticket.objects.filter(
            user=user,
            is_admin_assigned=True,
            status='admin_assigned'
        )
        if match_id:
            tickets_qs = tickets_qs.filter(match_id=match_id)
        count = tickets_qs.count()
        user_data.append({'user': user, 'ticket_count': count})

    context = {
        'user_data': user_data,
        'matches': matches,
        'selected_match_id': int(match_id) if match_id else None,
    }
    return render(request, 'tickets/manage_vip_users.html', context)


@login_required
@staff_member_required
def manage_user_tickets(request, user_id):
    """مدیریت بلیط‌های یک کاربر ویژه"""
    user = get_object_or_404(User, id=user_id, user_type='vip')
    tickets = Ticket.objects.filter(
        user=user,
        is_admin_assigned=True,
        status='admin_assigned'
    ).order_by('-purchase_date')

    if request.method == 'POST':
        ticket_id = request.POST.get('ticket_id')
        if ticket_id:
            ticket = get_object_or_404(Ticket, id=ticket_id, user=user)
            with transaction.atomic():
                seat = ticket.seat
                seat.is_available = True
                seat.save()
                ticket.delete()
                messages.success(request, f'بلیط {ticket.ticket_number} حذف شد.')
            return redirect('tickets:manage_user_tickets', user_id=user.id)

    return render(request, 'tickets/manage_user_tickets.html', {
        'target_user': user,
        'tickets': tickets,
    })


@login_required
@staff_member_required
def row_occupancy_report(request):
    """گزارش اشغال صندلی‌ها به تفکیک بلوک برای یک مسابقه خاص"""
    from matches.models import Match, MatchSeat, Block, Seat  # ایمپورت Seat

    matches = Match.objects.all().order_by('-date_time')
    match_id = request.GET.get('match_id')

    if not match_id and matches.exists():
        match_id = matches.first().id
    elif match_id:
        try:
            match_id = int(match_id)
        except (ValueError, TypeError):
            match_id = None

    report_data = []
    if match_id:
        match = get_object_or_404(Match, id=match_id)

        # دریافت همه بلوک‌های فعال
        blocks = Block.objects.filter(is_active=True).order_by('order')

        for block in blocks:
            # ✅ تعداد کل صندلی‌های این بلوک (از مدل Seat)
            total_seats = Seat.objects.filter(row__block=block).count()

            # ✅ تعداد صندلی‌های اشغال‌شده در این مسابقه برای این بلوک
            occupied = MatchSeat.objects.filter(
                match=match,
                seat__row__block=block,
                is_available=False
            ).count()

            # ✅ تعداد خالی = کل صندلی‌ها - اشغال‌شده
            available = total_seats - occupied

            report_data.append({
                'row': block,  # برای تطابق با قالب
                'total': total_seats,
                'occupied': occupied,
                'available': available,
                'occupancy_percent': round((occupied / total_seats * 100) if total_seats > 0 else 0, 1)
            })

    context = {
        'report_data': report_data,
        'matches': matches,
        'selected_match_id': match_id,
    }
    return render(request, 'tickets/row_occupancy.html', context)


# ============================================================
#  ویوهای مربوط به دانلود گروهی
# ============================================================

@login_required
def bulk_download_tickets(request):
    if request.user.user_type != 'vip':
        messages.error(request, 'شما دسترسی به این بخش ندارید.')
        return redirect('matches:home')
    if request.method == 'POST':
        ticket_ids = request.POST.getlist('ticket_ids')
        if not ticket_ids:
            messages.error(request, 'هیچ بلیطی انتخاب نشده است.')
            return redirect('tickets:vip_issued_tickets')
        tickets = Ticket.objects.filter(id__in=ticket_ids, user=request.user, status='vip_issued')
        if not tickets:
            messages.error(request, 'بلیط‌های انتخاب‌شده معتبر نیستند.')
            return redirect('tickets:vip_issued_tickets')
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            for ticket in tickets:
                if ticket.pdf_file and ticket.pdf_file.path:
                    try:
                        zip_file.write(ticket.pdf_file.path, arcname=f"ticket_{ticket.ticket_number}.pdf")
                    except FileNotFoundError:
                        messages.warning(request, f'فایل PDF برای بلیط {ticket.ticket_number} یافت نشد.')
                        continue
        if zip_buffer.getbuffer().nbytes == 0:
            messages.error(request, 'هیچ فایل PDF معتبری برای دانلود وجود ندارد.')
            return redirect('tickets:vip_issued_tickets')
        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="tickets.zip"'
        return response
    return redirect('tickets:vip_issued_tickets')


@login_required
def bulk_download_received_tickets(request):
    if request.user.user_type != 'vip':
        messages.error(request, 'شما دسترسی به این بخش ندارید.')
        return redirect('matches:home')
    if request.method == 'POST':
        ticket_ids = request.POST.getlist('ticket_ids')
        if not ticket_ids:
            messages.error(request, 'هیچ بلیطی انتخاب نشده است.')
            return redirect('tickets:vip_tickets')
        tickets = Ticket.objects.filter(id__in=ticket_ids, user=request.user, status='admin_assigned')
        if not tickets:
            messages.error(request, 'بلیط‌های انتخاب‌شده معتبر نیستند.')
            return redirect('tickets:vip_tickets')
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
            for ticket in tickets:
                if ticket.pdf_file and ticket.pdf_file.path:
                    try:
                        zip_file.write(ticket.pdf_file.path, arcname=f"ticket_{ticket.ticket_number}.pdf")
                    except FileNotFoundError:
                        messages.warning(request, f'فایل PDF برای بلیط {ticket.ticket_number} یافت نشد.')
                        continue
        if zip_buffer.getbuffer().nbytes == 0:
            messages.error(request, 'هیچ فایل PDF معتبری برای دانلود وجود ندارد.')
            return redirect('tickets:vip_tickets')
        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="received_tickets.zip"'
        return response
    return redirect('tickets:vip_tickets')


def check_discount(request):
    if request.method != 'POST':
        return JsonResponse({'valid': False})

    code = request.POST.get('code', '').strip()
    block_id = request.session.get('selected_block_id')

    try:
        discount = DiscountCode.objects.get(code=code)
        block = None
        if block_id:
            from matches.models import Block
            block = Block.objects.get(id=block_id)
        valid, msg = discount.is_valid(block=block)
        if valid:
            return JsonResponse({
                'valid': True,
                'percent': discount.discount_percent,
                'message': f'کد تخفیف {discount.discount_percent}٪ اعمال شد'
            })
        return JsonResponse({'valid': False, 'message': msg})
    except DiscountCode.DoesNotExist:
        return JsonResponse({'valid': False, 'message': 'کد تخفیف یافت نشد'})


# ============================================================
#  مدیریت تخصیص ظرفیت VIP (فقط ادمین)
# ============================================================

@staff_member_required
def admin_vip_quota_list(request):
    """لیست تخصیص‌های ظرفیت VIP"""
    quotas = VIPQuota.objects.select_related('user', 'match').all().order_by('-match__date_time', 'user__username')

    context = {
        'quotas': quotas,
    }
    return render(request, 'tickets/admin_vip_quota_list.html', context)


@staff_member_required
def admin_vip_quota_create(request):
    """ایجاد تخصیص ظرفیت جدید"""
    if request.method == 'POST':
        form = VIPQuotaForm(request.POST)
        if form.is_valid():
            # بررسی تکراری نبودن
            user = form.cleaned_data['user']
            match = form.cleaned_data['match']
            if VIPQuota.objects.filter(user=user, match=match).exists():
                messages.error(request, f'کاربر "{user.username}" قبلاً برای این مسابقه ظرفیت دارد.')
                return render(request, 'tickets/admin_vip_quota_form.html', {'form': form, 'is_edit': False})

            form.save()
            messages.success(request, f'ظرفیت برای کاربر "{user.username}" در مسابقه "{match}" با موفقیت ایجاد شد.')
            return redirect('tickets:admin_vip_quota_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = VIPQuotaForm()

    return render(request, 'tickets/admin_vip_quota_form.html', {'form': form, 'is_edit': False})


@staff_member_required
def admin_vip_quota_edit(request, quota_id):
    """ویرایش تخصیص ظرفیت"""
    quota = get_object_or_404(VIPQuota, id=quota_id)

    if request.method == 'POST':
        form = VIPQuotaForm(request.POST, instance=quota)
        if form.is_valid():
            form.save()
            messages.success(request, f'ظرفیت کاربر "{quota.user.username}" با موفقیت ویرایش شد.')
            return redirect('tickets:admin_vip_quota_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = VIPQuotaForm(instance=quota)

    return render(request, 'tickets/admin_vip_quota_form.html', {'form': form, 'quota': quota, 'is_edit': True})


@staff_member_required
def admin_vip_quota_delete(request, quota_id):
    """حذف تخصیص ظرفیت"""
    quota = get_object_or_404(VIPQuota, id=quota_id)
    if request.method == 'POST':
        user_name = quota.user.username
        match_name = str(quota.match)
        quota.delete()
        messages.success(request, f'تخصیص ظرفیت کاربر "{user_name}" برای مسابقه "{match_name}" با موفقیت حذف شد.')
        return redirect('tickets:admin_vip_quota_list')

    return render(request, 'tickets/admin_vip_quota_confirm_delete.html', {'quota': quota})


# ============================================================
#  مدیریت کدهای تخفیف (فقط ادمین)
# ============================================================

@staff_member_required
def admin_discount_list(request):
    """لیست کدهای تخفیف"""
    discounts = DiscountCode.objects.all().order_by('-created_at')
    return render(request, 'tickets/admin_discount_list.html', {'discounts': discounts})


@staff_member_required
def admin_discount_create(request):
    """ایجاد کد تخفیف جدید"""
    if request.method == 'POST':
        form = DiscountCodeForm(request.POST)
        if form.is_valid():
            # بررسی تکراری نبودن کد
            code = form.cleaned_data['code']
            if DiscountCode.objects.filter(code=code).exists():
                messages.error(request, f'کد تخفیف "{code}" قبلاً وجود دارد.')
                return render(request, 'tickets/admin_discount_form.html', {'form': form, 'is_edit': False})

            discount = form.save()
            messages.success(request, f'کد تخفیف "{discount.code}" با موفقیت ایجاد شد.')
            return redirect('tickets:admin_discount_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = DiscountCodeForm()

    return render(request, 'tickets/admin_discount_form.html', {'form': form, 'is_edit': False})


@staff_member_required
def admin_discount_edit(request, discount_id):
    """ویرایش کد تخفیف"""
    discount = get_object_or_404(DiscountCode, id=discount_id)

    if request.method == 'POST':
        form = DiscountCodeForm(request.POST, instance=discount)
        if form.is_valid():
            form.save()
            messages.success(request, f'کد تخفیف "{discount.code}" با موفقیت ویرایش شد.')
            return redirect('tickets:admin_discount_list')
        else:
            messages.error(request, 'خطا در فرم. لطفاً دوباره تلاش کنید.')
    else:
        form = DiscountCodeForm(instance=discount)

    return render(request, 'tickets/admin_discount_form.html', {'form': form, 'discount': discount, 'is_edit': True})


@staff_member_required
def admin_discount_delete(request, discount_id):
    """حذف کد تخفیف"""
    discount = get_object_or_404(DiscountCode, id=discount_id)
    if request.method == 'POST':
        code = discount.code
        discount.delete()
        messages.success(request, f'کد تخفیف "{code}" با موفقیت حذف شد.')
        return redirect('tickets:admin_discount_list')

    return render(request, 'tickets/admin_discount_confirm_delete.html', {'discount': discount})


@staff_member_required
def admin_discount_toggle(request, discount_id):
    """فعال/غیرفعال کردن کد تخفیف"""
    discount = get_object_or_404(DiscountCode, id=discount_id)
    discount.is_active = not discount.is_active
    discount.save()
    status = 'فعال' if discount.is_active else 'غیرفعال'
    messages.success(request, f'کد تخفیف "{discount.code}" {status} شد.')
    return redirect('tickets:admin_discount_list')


@staff_member_required
def export_sales_report_excel(request):
    """خروجی اکسل از گزارش فروش چند مسابقه"""
    if request.method != 'POST':
        messages.error(request, 'درخواست نامعتبر.')
        return redirect('tickets:sales_report')

    match_ids = request.POST.getlist('match_ids')
    if not match_ids:
        messages.warning(request, 'هیچ مسابقه‌ای انتخاب نشده است.')
        return redirect('tickets:sales_report')

    matches = Match.objects.filter(id__in=match_ids).order_by('-date_time')
    if not matches:
        messages.error(request, 'مسابقه‌های انتخاب‌شده یافت نشدند.')
        return redirect('tickets:sales_report')

    wb = Workbook()
    # حذف sheet پیش‌فرض (بعداً دوباره می‌سازیم)
    wb.remove(wb.active)

    # ===== Sheet خلاصه =====
    summary_ws = wb.create_sheet("خلاصه کل", 0)
    summary_ws.append(['گزارش فروش چند مسابقه'])
    summary_ws.merge_cells('A1:F1')
    summary_ws['A1'].font = Font(bold=True, size=14)
    summary_ws['A1'].alignment = Alignment(horizontal='center')
    summary_ws.append([])

    # هدر جدول خلاصه
    summary_headers = ['ردیف', 'مسابقه', 'رشته', 'تاریخ', 'تعداد فروش', 'درآمد کل (تومان)', 'درصد اشغال']
    summary_ws.append(summary_headers)
    for cell in summary_ws[summary_ws.max_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')
        cell.fill = PatternFill(start_color="D4AF37", end_color="D4AF37", fill_type="solid")

    total_all = 0
    revenue_all = 0
    row_num = 1

    # ===== برای هر مسابقه یک Sheet جداگانه =====
    for match in matches:
        # محاسبه آمار
        sold_tickets = Ticket.objects.filter(match=match, status='paid')
        vip_tickets = Ticket.objects.filter(match=match, status__in=['admin_assigned', 'vip_issued'])
        sold_count = sold_tickets.count()
        vip_count = vip_tickets.count()
        total_tickets = sold_count + vip_count

        revenue = sum(t.seat.row.block.price for t in sold_tickets if t.seat and t.seat.row and t.seat.row.block)
        vip_revenue = sum(t.seat.row.block.price for t in vip_tickets if t.seat and t.seat.row and t.seat.row.block)
        total_revenue = revenue + vip_revenue

        total_seats = Seat.objects.filter(
            row__block__stadium=match.stadium,
            row__block__is_active=True,
            row__is_active=True
        ).count()
        sold_seats = MatchSeat.objects.filter(match=match, is_available=False).count()
        occupancy = round((sold_seats / total_seats * 100) if total_seats > 0 else 0, 1)

        # اضافه کردن به خلاصه
        summary_ws.append([
            row_num,
            f"{match.home_team} vs {match.away_team}",
            match.get_sport_type_display(),
            match.date_time.strftime('%Y/%m/%d'),
            total_tickets,
            total_revenue,
            f"{occupancy}%"
        ])
        total_all += total_tickets
        revenue_all += total_revenue
        row_num += 1

        # ===== Sheet اختصاصی هر مسابقه =====
        sheet_name = f"{match.home_team} - {match.away_team}"[:31]  # حداکثر ۳۱ کاراکتر
        ws = wb.create_sheet(sheet_name)

        # عنوان
        ws.append([f"گزارش فروش: {match.home_team} vs {match.away_team}"])
        ws.merge_cells('A1:F1')
        ws['A1'].font = Font(bold=True, size=14)
        ws['A1'].alignment = Alignment(horizontal='center')
        ws.append([])

        # اطلاعات کلی
        ws.append(['تاریخ مسابقه:', match.date_time.strftime('%Y/%m/%d %H:%M')])
        ws.append(['ورزشگاه:', match.stadium.name])
        ws.append(['ظرفیت کل:', total_seats])
        ws.append(['تعداد فروش:', total_tickets])
        ws.append(['درآمد کل:', total_revenue])
        ws.append(['درصد اشغال:', f"{occupancy}%"])
        ws.append([])

        # لیست بلیط‌ها (نمونه)
        headers = ['شماره بلیط', 'کاربر', 'نام خریدار', 'کد ملی', 'قیمت (تومان)', 'وضعیت']
        ws.append(headers)
        for cell in ws[ws.max_row]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
            cell.fill = PatternFill(start_color="D4AF37", end_color="D4AF37", fill_type="solid")

        all_tickets = list(sold_tickets) + list(vip_tickets)
        for t in all_tickets[:100]:  # نمایش حداکثر ۱۰۰ بلیط
            ws.append([
                t.ticket_number,
                t.user.username,
                t.full_name,
                t.national_code,
                t.seat.row.block.price if t.seat and t.seat.row and t.seat.row.block else 0,
                t.get_status_display(),
            ])

        # تنظیم عرض ستون‌ها
        for col in ['A', 'B', 'C', 'D', 'E', 'F']:
            ws.column_dimensions[col].width = 18

    # اضافه کردن ردیف جمع کل در خلاصه
    summary_ws.append([])
    summary_ws.append(['جمع کل', '', '', '', total_all, revenue_all, ''])
    for cell in summary_ws[summary_ws.max_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="28a745", end_color="28a745", fill_type="solid")
        cell.alignment = Alignment(horizontal='center')

    for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
        summary_ws.column_dimensions[col].width = 18

    # ===== پاسخ HTTP =====
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="گزارش_فروش_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    wb.save(response)
    return response


def get_blocks_for_match(request):
    """دریافت بلوک‌های یک مسابقه (بر اساس ورزشگاه)"""
    match_id = request.GET.get('match_id')
    if not match_id:
        return JsonResponse({'blocks': []})

    try:
        match = Match.objects.get(id=match_id)
        blocks = Block.objects.filter(
            stadium=match.stadium,
            is_active=True
        ).order_by('order')

        blocks_data = [{'id': block.id, 'name': block.name} for block in blocks]
        return JsonResponse({'blocks': blocks_data})
    except Match.DoesNotExist:
        return JsonResponse({'blocks': []})


@login_required
def bulk_download_user_tickets(request):
    """
    دانلود گروهی بلیط‌های انتخاب‌شده از صفحه «بلیط‌های من»
    """
    if request.method != 'POST':
        messages.error(request, 'درخواست نامعتبر.')
        return redirect('tickets:user_tickets')

    ticket_ids = request.POST.getlist('ticket_ids')
    if not ticket_ids:
        messages.warning(request, 'هیچ بلیطی انتخاب نشده است.')
        return redirect('tickets:user_tickets')

    # دریافت بلیط‌های متعلق به کاربر فعلی
    tickets = Ticket.objects.filter(
        id__in=ticket_ids,
        user=request.user,
        status__in=['paid', 'admin_assigned', 'vip_issued']
    )

    if not tickets:
        messages.error(request, 'بلیط‌های انتخاب‌شده معتبر نیستند.')
        return redirect('tickets:user_tickets')

    # ایجاد فایل ZIP
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
        for ticket in tickets:
            if ticket.pdf_file and ticket.pdf_file.path:
                try:
                    # نام فایل: ticket_شماره.pdf
                    zip_file.write(
                        ticket.pdf_file.path,
                        arcname=f"ticket_{ticket.ticket_number}.pdf"
                    )
                except FileNotFoundError:
                    messages.warning(request, f'فایل PDF برای بلیط {ticket.ticket_number} یافت نشد.')
                    continue

    if zip_buffer.getbuffer().nbytes == 0:
        messages.error(request, 'هیچ فایل PDF معتبری برای دانلود وجود ندارد.')
        return redirect('tickets:user_tickets')

    zip_buffer.seek(0)
    response = HttpResponse(zip_buffer, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="tickets_{timezone.now().strftime("%Y%m%d")}.zip"'
    return response
