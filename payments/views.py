import logging
from django.shortcuts import redirect
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.db import transaction
from zibal_payment.client import ZibalClient

from .models import Payment
from tickets.views import get_age_from_jalali  # ایمپورت تابع محاسبه سن از tickets
from matches.models import Match
from tickets.models import Ticket
logger = logging.getLogger(__name__)


def _build_callback_url(request):
    """
    آدرس callback رو همیشه از روی همون دامنه‌ای که کاربر الان داره سایت رو
    باهاش می‌بینه می‌سازیم تا اگر دامنه عوض شد، مشکل کوکی/سشن پیش نیاد.
    """
    return request.build_absolute_uri(reverse('payments:payment_verify'))


def payment_request(request):
    """
    این ویو برای دو منظور استفاده می‌شه:
    ۱. شارژ مستقیم کیف پول
    ۲. پرداخت باقی‌مانده‌ی خرید بلیط
    """
    logger.info("===== وارد ویو payment_request شد =====")

    if request.method != 'POST':
        return redirect('matches:home')

    if not request.user.is_authenticated:
        messages.error(request, 'برای پرداخت باید وارد حساب کاربری خود شوید.')
        return redirect('accounts:choose_login')

    try:
        gateway_amount = int(request.POST.get('amount'))
    except (TypeError, ValueError):
        messages.error(request, "مبلغ نامعتبر است")
        return redirect('wallet:dashboard')

    if gateway_amount <= 0:
        messages.error(request, "مبلغ باید بزرگتر از صفر باشد")
        return redirect('wallet:dashboard')

    match_id = request.POST.get('match_id')
    next_url = request.POST.get('next_url') or reverse('tickets:user_tickets')

    if match_id:
        # ===== بررسی محدودیت خرید قبل از رفتن به درگاه بانک =====
        try:
            match_obj = Match.objects.get(id=match_id)
        except Match.DoesNotExist:
            messages.error(request, "مسابقه یافت نشد.")
            return redirect('matches:home')

        if request.user.user_type != 'vip':
            submitted_codes = []
            for key, value in request.POST.items():
                if key.startswith('national_code_') and value:
                    # ۱. جلوگیری از تکرار کد ملی در همین فرم
                    if value in submitted_codes:
                        messages.error(request,
                                       f"کد ملی {value} برای دو صندلی مختلف وارد شده است. هر فرد فقط یک بلیط می‌تواند داشته باشد.")
                        return redirect('tickets:ticket_info', match_id=match_id)
                    submitted_codes.append(value)

            # ۲. بررسی دیتابیس برای این مسابقه
            if submitted_codes:
                already_bought = Ticket.objects.filter(
                    national_code__in=submitted_codes,
                    match=match_obj,
                    status='paid'
                ).exists()

                if already_bought:
                    messages.error(request, "یکی از کد ملی‌های وارد شده قبلاً برای این مسابقه بلیط خریداری کرده است.")
                    return redirect('tickets:ticket_info', match_id=match_id)
        # ===== پایان بررسی محدودیت =====

        try:
            wallet_amount_used = int(request.POST.get('wallet_amount', 0))
        except (TypeError, ValueError):
            wallet_amount_used = 0

        # ===== ذخیره تمام اطلاعات خریدار در دیتابیس =====
        buyer_info = {}
        for key, value in request.POST.items():
            if key.startswith('full_name_') or key.startswith('national_code_') or \
                    key.startswith('tarikhe_tavallod_') or key.startswith('shomare_hamrah_') or \
                    key.startswith('match_seat_id_'):
                buyer_info[key] = value

        discount_code = request.POST.get('discount_code', '').strip()
        try:
            discount_percent = int(request.POST.get('discount_percent', 0) or 0)
        except (TypeError, ValueError):
            discount_percent = 0

        payment = Payment.objects.create(
            user=request.user,
            purpose='ticket_purchase',
            gateway_amount=gateway_amount,
            match_id=int(match_id),
            buyer_info=buyer_info,
            discount_code=discount_code,
            discount_percent=discount_percent,
            wallet_amount_used=wallet_amount_used,
            next_url=next_url,
        )
        description = "پرداخت بلیط"
    else:
        payment = Payment.objects.create(
            user=request.user,
            purpose='wallet_charge',
            gateway_amount=gateway_amount,
            next_url=next_url or reverse('wallet:dashboard'),
        )
        description = "شارژ کیف پول"

    client = ZibalClient(merchant_id=settings.ZIBAL_MERCHANT_ID, sandbox=settings.ZIBAL_SANDBOX)

    try:
        response = client.payment_request(
            amount=gateway_amount,
            callback_url=_build_callback_url(request),
            description=description,
        )

        track_id = response.get('trackId')
        if not track_id:
            payment.status = 'failed'
            payment.save(update_fields=['status', 'updated_at'])
            messages.error(request, "خطا در شروع پرداخت")
            return redirect('wallet:dashboard')

        payment.track_id = track_id
        payment.save(update_fields=['track_id', 'updated_at'])

        payment_url = client.generate_payment_url(track_id)
        return redirect(payment_url)

    except Exception as e:
        logger.error(f"خطا در درخواست پرداخت: {e}")
        payment.status = 'failed'
        payment.save(update_fields=['status', 'updated_at'])
        messages.error(request, "خطا در ارتباط با درگاه پرداخت")
        return redirect('wallet:dashboard')
def payment_verify(request):
    """
    تایید پرداخت پس از بازگشت از زیبال.
    """
    track_id = request.GET.get('trackId') or request.GET.get('track_id')

    if not track_id:
        messages.error(request, "اطلاعات پرداخت یافت نشد")
        return redirect('matches:home')

    try:
        payment = Payment.objects.select_related('user').get(track_id=track_id)
    except Payment.DoesNotExist:
        messages.error(request, "تراکنش یافت نشد")
        return redirect('matches:home')

    next_url = payment.next_url or reverse('matches:home')

    if payment.status == 'success':
        messages.info(request, "این تراکنش قبلاً با موفقیت پردازش شده است.")
        return redirect(next_url)

    if payment.status == 'failed':
        messages.error(request, "این تراکنش قبلاً ناموفق اعلام شده است.")
        return redirect(next_url)

    client = ZibalClient(merchant_id=settings.ZIBAL_MERCHANT_ID, sandbox=settings.ZIBAL_SANDBOX)

    try:
        result = client.payment_verify(track_id=track_id)
        result_code = result.get('result')
    except Exception as e:
        logger.error(f"خطا در تایید پرداخت: {e}")
        messages.error(request, "❌ خطا در تایید پرداخت. لطفاً با پشتیبانی تماس بگیرید.")
        return redirect(next_url)

    if result_code not in [100, 101]:
        error_messages = {
            101: "تراکنش قبلاً تایید شده است", 102: "تراکنش ناموفق بوده است",
            103: "خطای امنیتی", 104: "کد مرچنت نامعتبر", 105: "مبلغ نامعتبر", 106: "آدرس بازگشت نامعتبر",
        }
        error_msg = error_messages.get(result_code, f"کد خطای {result_code}")

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if payment.status == 'pending':
                payment.status = 'failed'
                payment.processed_at = timezone.now()
                payment.save(update_fields=['status', 'processed_at', 'updated_at'])

                if payment.purpose == 'ticket_purchase':
                    _release_payment_seats(payment)

        messages.error(request, f"❌ پرداخت ناموفق! {error_msg}")
        return redirect(next_url)

    amount = result.get('amount', payment.gateway_amount)
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)

        if payment.status != 'pending':
            messages.info(request, "این تراکنش قبلاً پردازش شده است.")
            return redirect(next_url)

        user = payment.user

        if payment.purpose == 'wallet_charge':
            from wallet.models import Wallet
            wallet, _ = Wallet.objects.get_or_create(user=user)
            wallet.add_balance(amount=amount, description=f'شارژ کیف پول از طریق زیبال - تراکنش {track_id}', reference_id=track_id)
            messages.success(request, f"✅ کیف پول شما با موفقیت به مبلغ {amount:,} ریال شارژ شد.")

        else:
            success, error_msg = _finalize_ticket_purchase(payment, amount)
            if success:
                messages.success(request, "✅ پرداخت با موفقیت انجام شد و بلیط‌های شما صادر شدند.")
            else:
                # صندلی‌ها را آزاد می‌کنیم (چه به‌خاطر عدم تطابق مبلغ، چه به هر
                # دلیل دیگری) و تراکنش را ناموفق علامت می‌زنیم -- قبلاً در این
                # حالت payment.status بدون قید و شرط 'success' ثبت می‌شد ولی
                # هیچ بلیطی صادر نشده بود و صندلی‌ها هم هیچ‌وقت آزاد نمی‌شدند.
                logger.error(f"❌ Ticket finalize failed for payment {payment.id}: {error_msg}")
                _release_payment_seats(payment)
                payment.status = 'failed'
                payment.processed_at = timezone.now()
                payment.save(update_fields=['status', 'processed_at', 'updated_at'])
                messages.error(
                    request,
                    f"❌ در صدور بلیط مشکلی پیش آمد: {error_msg} "
                    f"اگر مبلغی از حساب شما کسر شده، با پشتیبانی تماس بگیرید و شماره تراکنش {track_id} را اعلام کنید."
                )
                return redirect(next_url)

        payment.status = 'success'
        payment.processed_at = timezone.now()
        payment.save(update_fields=['status', 'processed_at', 'updated_at'])

    return redirect(next_url)


def _release_payment_seats(payment):
    """وقتی پرداخت باقی‌مانده‌ی خرید بلیط ناموفق بود، صندلی‌های رزروشده رو آزاد کن."""
    from matches.models import MatchSeat
    from tickets.reservation import SeatReservation
    from django.db import transaction

    seat_ids = [
        int(v) for k, v in payment.buyer_info.items()
        if k.startswith('match_seat_id_')
    ]
    if not seat_ids:
        return

    with transaction.atomic():
        MatchSeat.objects.filter(
            id__in=seat_ids, match_id=payment.match_id
        ).update(is_available=True, reserved_until=None)

    SeatReservation.release_many(seat_ids, force=True)


def _finalize_ticket_purchase(payment, gateway_amount_paid):
    from tickets.models import Ticket, Order, DiscountCode
    from matches.models import Match, MatchSeat, get_block_price_map, get_basa_discount_percent
    from tickets.reservation import SeatReservation
    from wallet.models import Wallet
    from tickets.views import get_age_from_jalali
    from accounts.models import User

    try:
        match = Match.objects.select_for_update().get(id=payment.match_id)
    except Match.DoesNotExist:
        return False, "مسابقه یافت نشد"

    user = payment.user
    wallet, _ = Wallet.objects.get_or_create(user=user)

    # ===== قفل کد تخفیف =====
    # مبلغی که کاربر واقعاً از طریق زیبال پرداخت کرده (payment.gateway_amount)
    # از قبل بر اساس همین discount_percent محاسبه و از او دریافت شده؛ اینجا
    # دیگه نمی‌تونیم تخفیف رو رد کنیم چون پول از قبل با همون درصد گرفته شده.
    # فقط قفل می‌گیریم تا افزایش used_count زیر آن (پایین‌تر) با
    # درخواست‌های هم‌زمان دیگر تداخل نکند و به‌جای += پایتونی، شمارنده به‌درستی
    # جمع بزند.
    discount_obj = None
    if payment.discount_code:
        try:
            discount_obj = DiscountCode.objects.select_for_update().get(code=payment.discount_code)
        except DiscountCode.DoesNotExist:
            pass

    try:  # <--- این بلاک اضافه شد تا از کرش شدن Gunicorn جلوگیری کند
        actual_total_price = 0
        processed_seats_data = []

        match_seat_pks = [
            int(k.replace('match_seat_id_', ''))
            for k in payment.buyer_info
            if k.startswith('match_seat_id_')
        ]

        # قفل صندلی‌ها تا پایان تراکنش صدور بلیط
        locked_seats = {
            ms.id: ms
            for ms in (
                MatchSeat.objects
                .select_for_update()
                .select_related('seat__row__block')
                .filter(id__in=match_seat_pks, match=match)
            )
        }

        block_price_map = get_block_price_map(match)
        basa_discount_percent = get_basa_discount_percent(match)
        basa_national_codes = set()
        if basa_discount_percent > 0:
            basa_national_codes = set(User.objects.filter(is_basa_member=True).values_list('national_code', flat=True))

        for pk in match_seat_pks:
            pk_str = str(pk)
            full_name = payment.buyer_info.get(f'full_name_{pk_str}', '')
            national_code = payment.buyer_info.get(f'national_code_{pk_str}', '')
            tarikhe_tavallod = payment.buyer_info.get(f'tarikhe_tavallod_{pk_str}', '')

            match_seat = locked_seats.get(pk)
            if not match_seat:
                continue

            age = get_age_from_jalali(tarikhe_tavallod)
            block = match_seat.seat.row.block
            base_price = block_price_map.get(block.id, block.price) if block else 0
            seat_price = 0 if age < 15 else base_price
            basa_discount_amount = 0
            if seat_price and basa_discount_percent > 0 and national_code in basa_national_codes:
                discounted_price = seat_price - int(seat_price * basa_discount_percent / 100)
                basa_discount_amount = seat_price - discounted_price
                seat_price = discounted_price

            actual_total_price += seat_price
            processed_seats_data.append({
                'match_seat': match_seat,
                'full_name': full_name,
                'national_code': national_code,
                'price': seat_price,
                'age': age,
                'basa_discount_amount': basa_discount_amount,
            })

        discount_amount = int(float(actual_total_price) * (payment.discount_percent / 100))
        total_amount = actual_total_price - discount_amount

        # ===== اعتبارسنجی ضدجعل مبلغ =====
        # gateway_amount و wallet_amount هر دو موقع ثبت Payment مستقیم از یک
        # فیلد hidden فرم خوانده می‌شوند (payments/views.py: payment_request)
        # و کاملاً قابل دستکاری سمت کلاینت‌اند (مثلاً با DevTools). اینجا --
        # بعد از قفل صندلی‌ها و محاسبه‌ی قیمت واقعی از روی block_price_map
        # (قیمت اختصاصی این مسابقه در صورت وجود، در غیر این صورت قیمت پیش‌فرض بلوک) --
        # باید مطمئن شویم مجموع مبلغ واقعاً تأییدشده از درگاه
        # (gateway_amount_paid، برگرفته از پاسخ verify خودِ زیبال، نه از
        # ورودی کاربر) به‌علاوه‌ی مبلغ واقعاً قابل‌کسر از کیف پول، کمتر از
        # قیمت واقعی بلیط‌ها نباشد؛ وگرنه کاربر می‌توانست با تغییر مبلغ
        # درخواستی (مثلاً به ۱ ریال) بلیط واقعی را تقریباً رایگان بگیرد.
        wallet_amount_requested = min(payment.wallet_amount_used, wallet.balance)
        total_covered = gateway_amount_paid + wallet_amount_requested
        if total_covered < total_amount:
            logger.error(
                f"⚠️ PRICE MISMATCH on payment {payment.id} (user {user.id}): "
                f"required={total_amount}, gateway_paid={gateway_amount_paid}, "
                f"wallet_requested={wallet_amount_requested}, total_covered={total_covered}. "
                f"Possible payment amount tampering."
            )
            return False, (
                f"مبلغ پرداخت‌شده ({total_covered:,} ریال) با مبلغ واقعی بلیط‌ها "
                f"({total_amount:,} ریال) مطابقت ندارد."
            )

        wallet_amount_used = 0
        if wallet_amount_requested > 0:
            success = wallet.deduct_balance(
                amount=wallet_amount_requested,
                description=f"پرداخت بخشی از خرید بلیط از کیف پول - مسابقه {match.home_team} vs {match.away_team}",
                reference_id=f"PAY-{payment.id}",
                tx_type='ticket_purchase',
            )
            if success:
                wallet_amount_used = wallet_amount_requested

        if wallet_amount_used < wallet_amount_requested and gateway_amount_paid < total_amount:
            # کسر از کیف پول ناموفق بود (مثلاً موجودی هم‌زمان جای دیگری خرج
            # شده) و مبلغ تأییدشده‌ی درگاه به‌تنهایی کافی نیست -- نباید بلیط
            # صادر شود.
            logger.error(
                f"⚠️ Wallet deduction failed for payment {payment.id} and gateway amount alone "
                f"({gateway_amount_paid}) is less than required ({total_amount})."
            )
            return False, "کسر از کیف پول ناموفق بود و مبلغ پرداختی درگاه به‌تنهایی کافی نیست."

        payment_method = 'mixed' if wallet_amount_used > 0 else 'zibal'

        order = Order.objects.create(
            user=user, match=match, subtotal=actual_total_price,
            discount_percent=payment.discount_percent, discount_amount=discount_amount,
            total_amount=total_amount, wallet_balance_before=wallet.balance + wallet_amount_used,
            wallet_amount=wallet_amount_used, wallet_balance_after=wallet.balance,
            payment_method=payment_method, payment_status='paid',
            discount_code=discount_obj.code if discount_obj else '',
            discount_code_id=discount_obj.id if discount_obj else None,
            full_name=user.get_full_name() or user.username,
            phone_number=getattr(user, 'phone_number', ''),
            track_id=payment.track_id, paid_at=timezone.now(),
        )
        payment.order = order
        payment.save(update_fields=['order'])

        tickets_created = []
        processed_national_codes = set()

        for seat_data in processed_seats_data:
            match_seat = seat_data['match_seat']
            full_name = seat_data['full_name']
            national_code = seat_data['national_code']
            seat_price = seat_data['price']
            seat_age = seat_data['age']
            seat_basa_discount = seat_data['basa_discount_amount']

            if user.user_type != 'vip':
                if national_code in processed_national_codes:
                    logger.error(f"Duplicate national code {national_code} in same order {order.id}. Skipping.")
                    match_seat.is_available = True; match_seat.reserved_until = None; match_seat.save()
                    SeatReservation.release(match_seat.id, force=True)
                    continue

                if Ticket.objects.filter(national_code=national_code, match=match, status='paid').exists():
                    logger.error(f"User {user.username} tried to buy second ticket for {national_code} in match {match.id}. Skipping.")
                    match_seat.is_available = True; match_seat.reserved_until = None; match_seat.save()
                    SeatReservation.release(match_seat.id, force=True)
                    continue

            processed_national_codes.add(national_code)

            ticket = Ticket.objects.create(
                user=user, match=match, seat=match_seat.seat, match_seat=match_seat,
                full_name=full_name, national_code=national_code, status='paid',
                is_admin_assigned=False, order=order, price=seat_price, age=seat_age,
                basa_discount_amount=seat_basa_discount,
            )
            tickets_created.append(ticket)

            match_seat.is_available = False; match_seat.reserved_until = None
            match_seat.save(); SeatReservation.release(match_seat.id, force=True)

        if discount_obj and tickets_created:
            discount_obj.used_count += 1
            discount_obj.save(update_fields=['used_count'])

        if not tickets_created:
            return False, "هیچ بلیطی صادر نشد (صندلی‌ها یافت نشدند یا محدودیت خرید)"

        return True, None

    except Exception as e:
        # اگر هر خطایی در صدور بلیط رخ دهد، آن را لاگ می‌کنیم تا 502 ندهد
        logger.error(f"❌ CRITICAL ERROR in _finalize_ticket_purchase: {str(e)}", exc_info=True)
        return False, str(e)
