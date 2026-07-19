import logging
from django.shortcuts import redirect
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.db import transaction
from zibal_payment.client import ZibalClient

from .models import Payment

logger = logging.getLogger(__name__)


def _build_callback_url(request):
    """
    آدرس callback رو همیشه از روی همون دامنه‌ای که کاربر الان داره سایت رو
    باهاش می‌بینه می‌سازیم (نه یه مقدار هاردکد توی settings) — تا اگر دامنه
    عوض شد یا کسی از IP وارد شد، دیگه مشکل کوکی/سشن دوباره پیش نیاد.
    """
    return request.build_absolute_uri(reverse('payments:payment_verify'))


def payment_request(request):
    """
    این ویو برای دو منظور استفاده می‌شه:
    ۱. شارژ مستقیم کیف پول (از /wallet/charge/) — فقط 'amount' و 'next_url' داره.
    ۲. پرداخت باقی‌مانده‌ی خرید بلیط (از ticket_info، وقتی مبلغ نهایی > صفر بود) —
       علاوه بر amount، فیلدهای match_id/buyer_info/discount_code/wallet_amount هم داره.

    در هر دو حالت، اولین کار ساخت یک رکورد Payment در دیتابیسه، *قبل* از رفتن
    به درگاه. هیچ‌چیزی در سشن ذخیره نمی‌شه.
    """
    logger.info("===== وارد ویو payment_request شد =====")

    if request.method != 'POST':
        return redirect('matches:home')

    if not request.user.is_authenticated:
        messages.error(request, 'برای پرداخت باید وارد حساب کاربری خود شوید.')
        return redirect('accounts:choose_login')

    # ===== مبلغی که باید به درگاه فرستاده بشه (به ریال) =====
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

    # ===== تشخیص نوع پرداخت =====
    if match_id:
        # ----- خرید بلیط: باقی‌مانده بعد از تخفیف/کیف‌پول قراره به درگاه بره -----
        try:
            wallet_amount_used = int(request.POST.get('wallet_amount', 0))
        except (TypeError, ValueError):
            wallet_amount_used = 0

        buyer_info = {}
        for key, value in request.POST.items():
            if key.startswith('full_name_') or key.startswith('national_code_'):
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
        # ----- شارژ کیف پول -----
        payment = Payment.objects.create(
            user=request.user,
            purpose='wallet_charge',
            gateway_amount=gateway_amount,
            next_url=next_url or reverse('wallet:dashboard'),
        )
        description = "شارژ کیف پول"

    # ===== ارسال درخواست به زیبال =====
    client = ZibalClient(
        merchant_id=settings.ZIBAL_MERCHANT_ID,
        sandbox=settings.ZIBAL_SANDBOX
    )

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

    این ویو عمداً به request.user و request.session وابسته نیست (به‌جز پیام‌های
    نهایی که برای کاربر لاگین‌شده نمایش داده می‌شن) — چون بعد از ریدایرکت بین
    دامنه‌های مختلف ممکنه سشن در دسترس نباشه. هر کاری که لازمه، از روی خودِ
    رکورد Payment (که با track_id پیدا می‌شه) انجام می‌شه.
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

    # ===== Idempotency: اگر قبلاً پردازش شده، دوباره پردازش نکن =====
    if payment.status == 'success':
        messages.info(request, "این تراکنش قبلاً با موفقیت پردازش شده است.")
        return redirect(next_url)

    if payment.status == 'failed':
        messages.error(request, "این تراکنش قبلاً ناموفق اعلام شده است.")
        return redirect(next_url)

    client = ZibalClient(
        merchant_id=settings.ZIBAL_MERCHANT_ID,
        sandbox=settings.ZIBAL_SANDBOX
    )

    try:
        result = client.payment_verify(track_id=track_id)
        result_code = result.get('result')
    except Exception as e:
        logger.error(f"خطا در تایید پرداخت: {e}")
        messages.error(request, "❌ خطا در تایید پرداخت. لطفاً با پشتیبانی تماس بگیرید.")
        return redirect(next_url)

    if result_code != 100:
        error_messages = {
            101: "تراکنش قبلاً تایید شده است",
            102: "تراکنش ناموفق بوده است",
            103: "خطای امنیتی",
            104: "کد مرچنت نامعتبر",
            105: "مبلغ نامعتبر",
            106: "آدرس بازگشت نامعتبر",
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

    # ===== پرداخت موفق =====
    amount = result.get('amount', 0)

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)

        # چک دوباره داخل تراکنش (جلوگیری از race condition اگر verify دوبار همزمان بیاد)
        if payment.status != 'pending':
            messages.info(request, "این تراکنش قبلاً پردازش شده است.")
            return redirect(next_url)

        user = payment.user

        if payment.purpose == 'wallet_charge':
            from wallet.models import Wallet
            wallet, _ = Wallet.objects.get_or_create(user=user)
            wallet.add_balance(
                amount=amount,
                description=f'شارژ کیف پول از طریق زیبال - تراکنش {track_id}',
                reference_id=track_id,
            )
            messages.success(request, f"✅ کیف پول شما با موفقیت به مبلغ {amount:,} ریال شارژ شد.")

        else:  # ticket_purchase
            success, error_msg = _finalize_ticket_purchase(payment, amount)
            if success:
                messages.success(request, "✅ پرداخت با موفقیت انجام شد و بلیط‌های شما صادر شدند.")
            else:
                # مبلغ از کاربر کسر شده ولی صدور بلیط شکست خورده -> باید دستی رسیدگی بشه
                logger.error(f"❌ Payment {payment.id} succeeded but ticket finalize failed: {error_msg}")
                messages.error(
                    request,
                    "پرداخت شما با موفقیت انجام شد اما در صدور بلیط مشکلی پیش آمد. "
                    "لطفاً با پشتیبانی تماس بگیرید و شماره تراکنش زیر را اعلام کنید: "
                    f"{track_id}"
                )

        payment.status = 'success'
        payment.processed_at = timezone.now()
        payment.save(update_fields=['status', 'processed_at', 'updated_at'])

    return redirect(next_url)


def _release_payment_seats(payment):
    """وقتی پرداخت باقی‌مانده‌ی خرید بلیط ناموفق بود، صندلی‌های رزروشده رو آزاد کن."""
    from matches.models import MatchSeat
    from tickets.reservation import SeatReservation

    for match_seat_id in payment.seat_ids:
        try:
            ms = MatchSeat.objects.get(id=match_seat_id, match_id=payment.match_id)
            ms.is_available = True
            ms.reserved_until = None
            ms.save(update_fields=['is_available', 'reserved_until'])
        except MatchSeat.DoesNotExist:
            pass
        SeatReservation.release(match_seat_id)


def _finalize_ticket_purchase(payment, gateway_amount_paid):
    """
    بعد از تایید موفق زیبال: کیف پول (اگه لازم بود) کسر می‌شه، سفارش و بلیط‌ها
    ساخته می‌شن. فرض بر اینه که این تابع همیشه داخل transaction.atomic() صدا
    زده می‌شه (توسط payment_verify).
    """
    from tickets.models import Ticket, Order, DiscountCode
    from matches.models import Match, MatchSeat
    from tickets.reservation import SeatReservation
    from wallet.models import Wallet

    try:
        match = Match.objects.get(id=payment.match_id)
    except Match.DoesNotExist:
        return False, "مسابقه یافت نشد"

    user = payment.user
    wallet, _ = Wallet.objects.get_or_create(user=user)

    discount_obj = None
    if payment.discount_code:
        try:
            discount_obj = DiscountCode.objects.get(code=payment.discount_code)
        except DiscountCode.DoesNotExist:
            pass

    # ===== کسر کیف پول (اینجا، فقط بعد از موفقیت درگاه) =====
    wallet_amount_used = payment.wallet_amount_used
    if wallet_amount_used > 0:
        if wallet.balance < wallet_amount_used:
            # موجودی کافی نیست (مثلاً بین ساخت Payment و الان جای دیگه خرج شده)
            # با احتیاط: کل مبلغ رو از گیت‌وی حساب می‌کنیم و کیف‌پول رو دست نمی‌زنیم
            wallet_amount_used = 0
        else:
            success = wallet.deduct_balance(
                amount=wallet_amount_used,
                description=f"پرداخت بخشی از خرید بلیط از کیف پول - مسابقه {match.home_team} vs {match.away_team}",
                reference_id=f"PAY-{payment.id}",
                tx_type='ticket_purchase',
            )
            if not success:
                wallet_amount_used = 0

    total_amount = payment.subtotal - payment.discount_amount
    payment_method = 'mixed' if wallet_amount_used > 0 else 'zibal'

    order = Order.objects.create(
        user=user,
        match=match,
        subtotal=payment.subtotal,
        discount_percent=payment.discount_percent,
        discount_amount=payment.discount_amount,
        total_amount=total_amount,
        wallet_balance_before=wallet.balance + wallet_amount_used,
        wallet_amount=wallet_amount_used,
        wallet_balance_after=wallet.balance,
        payment_method=payment_method,
        payment_status='paid',
        discount_code=discount_obj.code if discount_obj else '',
        discount_code_id=discount_obj.id if discount_obj else None,
        full_name=user.get_full_name() or user.username,
        phone_number=getattr(user, 'phone_number', ''),
        track_id=payment.track_id,
        paid_at=timezone.now(),
    )
    payment.order = order
    payment.save(update_fields=['order'])

    tickets_created = []
    for key, full_name in payment.buyer_info.items():
        if not key.startswith('full_name_'):
            continue
        match_seat_pk = key.replace('full_name_', '')
        national_code = payment.buyer_info.get(f'national_code_{match_seat_pk}', '')

        try:
            match_seat = MatchSeat.objects.select_related('seat__row__block').get(
                id=int(match_seat_pk), match=match
            )
        except MatchSeat.DoesNotExist:
            continue

        ticket = Ticket.objects.create(
            user=user,
            match=match,
            seat=match_seat.seat,
            match_seat=match_seat,
            full_name=full_name,
            national_code=national_code,
            status='paid',
            is_admin_assigned=False,
            order=order,
            price=match_seat.seat.row.block.price if match_seat.seat.row.block else 0,
        )
        tickets_created.append(ticket)

        match_seat.is_available = False
        match_seat.reserved_until = None
        match_seat.save()
        SeatReservation.release(match_seat.id)

    if discount_obj and tickets_created:
        discount_obj.used_count += 1
        discount_obj.save(update_fields=['used_count'])

    if not tickets_created:
        return False, "هیچ بلیطی صادر نشد (صندلی‌ها یافت نشدند)"

    return True, None