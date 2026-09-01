import logging
from django.shortcuts import redirect
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.db import transaction
from zibal_payment.client import ZibalClient

from .models import Payment
from tickets.views import get_age_from_jalali, get_verified_age  # ایمپورت تابع محاسبه سن از tickets
from matches.models import Match
from tickets.models import Ticket, is_free_for_age
from wallet.models import (is_wallet_enabled, is_wallet_charge_enabled,
                           WALLET_DISABLED_MESSAGE, WALLET_CHARGE_DISABLED_MESSAGE)
logger = logging.getLogger(__name__)


def _safe_next_url(candidate, fallback):
    """
    فقط مسیرهای داخلیِ همین سایت را برمی‌گرداند؛ هر چیز دیگری (آدرس مطلق،
    //evil.com، javascript: و ...) با مقدار پیش‌فرض جایگزین می‌شود.
    """
    candidate = (candidate or '').strip()
    if not candidate:
        return fallback
    # باید مسیر نسبی باشد و با // شروع نشود (که مرورگر آن را دامنه‌ی دیگر می‌فهمد)
    if not candidate.startswith('/') or candidate.startswith('//') or '\\' in candidate:
        logger.warning("next_url غیرمجاز رد شد: %r", candidate[:120])
        return fallback
    return candidate


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

    # ===== next_url فقط می‌تواند یک مسیر داخلی باشد =====
    # این مقدار از فرم می‌آید، روی Payment ذخیره می‌شود و بعد از بازگشت از
    # درگاه مستقیم به redirect() داده می‌شود. بدون این اعتبارسنجی، یک لینک
    # دستکاری‌شده کاربر را بعد از پرداخت به سایت مهاجم می‌برد -- جای بسیار
    # مناسبی برای فیشینگ («پرداخت ناموفق بود، دوباره کارت را وارد کنید»).
    next_url = _safe_next_url(request.POST.get('next_url'), reverse('tickets:user_tickets'))

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

        # ===== اگر کیف پول غیرفعال است، سهم کیف پول نادیده گرفته می‌شود =====
        # فرم می‌تواند wallet_amount را با DevTools هم بفرستد؛ اینجا سمت سرور
        # صفر می‌شود. مبلغ درگاه دست‌نخورده می‌ماند، پس کاربر کمتر از قیمت
        # واقعی پرداخت نمی‌کند و _finalize_ticket_purchase هم مابه‌التفاوت
        # احتمالی را به کیف پول برمی‌گرداند.
        if wallet_amount_used and not is_wallet_enabled():
            logger.warning(
                "wallet_amount=%s ignored for user %s: wallet is disabled site-wide",
                wallet_amount_used, request.user.id,
            )
            wallet_amount_used = 0

        # ===== ذخیره تمام اطلاعات خریدار در دیتابیس =====
        buyer_info = {}
        for key, value in request.POST.items():
            if key.startswith('full_name_') or key.startswith('national_code_') or \
                    key.startswith('tarikhe_tavallod_') or key.startswith('shomare_hamrah_') or \
                    key.startswith('match_seat_id_') or key.startswith('special_code_'):
                buyer_info[key] = value

        # ===== درصد تخفیف هرگز از ورودی کاربر خوانده نمی‌شود =====
        # discount_percent قبلاً مستقیم از یک فیلد hidden فرم خوانده می‌شد که
        # با DevTools کاملاً قابل دستکاریه -- یعنی کاربر می‌تونست هر عددی
        # (مثلاً ۹۹) بذاره و چون _finalize_ticket_purchase هم همین مقدار رو
        # (نه درصد واقعیِ ثبت‌شده روی خودِ DiscountCode) برای محاسبه‌ی مبلغ
        # نهایی استفاده می‌کرد، بلیط تقریباً رایگان صادر می‌شد. الان درصد
        # همیشه از روی خودِ رکورد DiscountCode (با همون is_valid که مسیر
        # کیف‌پول هم استفاده می‌کنه) خونده می‌شه؛ ورودی کاربر فقط کد رو تعیین می‌کنه.
        from tickets.models import DiscountCode

        discount_code = request.POST.get('discount_code', '').strip()
        discount_percent = 0
        if discount_code:
            try:
                discount_obj = DiscountCode.objects.get(code=discount_code)
                valid, _msg = discount_obj.is_valid(match=match_obj)
                if valid:
                    discount_percent = discount_obj.discount_percent
                else:
                    discount_code = ''
            except DiscountCode.DoesNotExist:
                discount_code = ''

        # ===== تمدید رزرو برای مدت حضور در درگاه =====
        # رزرو صندلی ۱۰ دقیقه اعتبار دارد و تا امروز موقع رفتن به درگاه
        # تمدید نمی‌شد. کاربری که در درگاه بانک معطل می‌شد (رمز پویا، تلاش
        # دوباره) رزروش منقضی می‌شد، صندلی آزاد و به دیگری فروخته می‌شد، و
        # وقتی برمی‌گشت پولش رفته بود ولی صندلی نبود -- این پرتکرارترین علتِ
        # «پرداخت موفق، بلیط صادر نشده» بود (۲۱ مورد در یک روز).
        from tickets.reservation import SeatReservation
        for _key in buyer_info:
            if _key.startswith('match_seat_id_'):
                try:
                    SeatReservation.extend_reservation(int(buyer_info[_key]), request.user.id)
                except (TypeError, ValueError):
                    continue

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
        # ===== شارژ کیف پول: آخرین و مهم‌ترین نقطه‌ی جلوگیری =====
        # صفحه‌ی wallet:charge فقط فرم را نشان می‌دهد؛ شارژ واقعی از همین‌جا
        # شروع می‌شود. اگر فقط آن صفحه بسته می‌شد، یک POST مستقیم به این
        # آدرس هنوز کاربر را به درگاه می‌برد.
        # این شاخه فقط مسیر *شارژ* است، پس کلید شارژ را چک می‌کند نه کلید
        # کلیِ کیف پول -- خرید با موجودی موجود بالاتر و جداگانه کنترل می‌شود.
        if not is_wallet_charge_enabled():
            messages.error(request, WALLET_CHARGE_DISABLED_MESSAGE)
            return redirect('wallet:dashboard')

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

    # دوباره اعتبارسنجی می‌شود، نه فقط موقع ذخیره -- رکوردهای قدیمیِ Payment
    # ممکن است آدرس بیرونیِ اعتبارسنجی‌نشده داشته باشند.
    next_url = _safe_next_url(payment.next_url, reverse('matches:home'))

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
            # ===== اینجا عمداً is_wallet_enabled چک نمی‌شود =====
            # اگر ادمین دقیقاً وقتی کاربر روی صفحه‌ی زیبال بوده کیف پول را
            # خاموش کرده باشد، پول از حساب کاربر کم شده است. رد کردن واریز
            # یعنی گم شدن پول واقعی. جلوگیری در payment_request انجام می‌شود
            # (قبل از رفتن به درگاه)، نه اینجا.
            from wallet.models import Wallet
            wallet, _ = Wallet.objects.get_or_create(user=user)
            if not is_wallet_enabled():
                logger.warning(
                    "Crediting wallet_charge payment %s (track %s) although wallet is disabled: "
                    "money was already captured at the gateway.", payment.id, track_id,
                )
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
                # ===== پول از قبل در درگاه گرفته شده -- نباید گم شود =====
                # تا امروز این شاخه فقط status='failed' می‌گذاشت؛ نتیجه این
                # بود که تراکنش دقیقاً شبیه کسی می‌شد که اصلاً پرداخت نکرده،
                # پول کاربر بلاتکلیف می‌ماند و پیدا کردنش فقط با استعلام
                # تک‌تک تراکنش‌ها از زیبال ممکن بود (۶۴۰ مورد، ۳.۵ میلیارد
                # ریال). حالا مبلغ بلافاصله به کیف پول همان کاربر برمی‌گردد.
                # عمداً مستقل از is_wallet_enabled است: این بازگشت وجه است،
                # نه استفاده از کیف پول -- رد کردنش یعنی گم شدن پول واقعی.
                logger.error(f"❌ Ticket finalize failed for payment {payment.id}: {error_msg}")
                _release_payment_seats(payment)

                refunded = False
                try:
                    from wallet.models import Wallet as _Wallet
                    _w, _ = _Wallet.objects.get_or_create(user=payment.user)
                    refunded = _w.add_balance(
                        amount=amount,
                        description=f'بازگشت وجه -- بلیط صادر نشد (تراکنش {track_id})',
                        reference_id=f'refund-{track_id}',
                    )
                except Exception as exc:            # noqa: BLE001
                    logger.error("بازگشت وجه به کیف پول برای پرداخت %s شکست خورد: %s",
                                 payment.id, exc)

                payment.status = 'failed'
                payment.processed_at = timezone.now()
                payment.save(update_fields=['status', 'processed_at', 'updated_at'])

                if refunded:
                    messages.error(
                        request,
                        f"❌ در صدور بلیط مشکلی پیش آمد: {error_msg} "
                        f"مبلغ {amount:,} ریال به کیف پول شما بازگردانده شد."
                    )
                else:
                    messages.error(
                        request,
                        f"❌ در صدور بلیط مشکلی پیش آمد: {error_msg} "
                        f"اگر مبلغی از حساب شما کسر شده، با پشتیبانی تماس بگیرید و "
                        f"شماره تراکنش {track_id} را اعلام کنید."
                    )
                return redirect(next_url)

        payment.status = 'success'
        payment.processed_at = timezone.now()
        payment.save(update_fields=['status', 'processed_at', 'updated_at'])

    return redirect(next_url)


def _release_payment_seats(payment):
    """وقتی پرداخت باقی‌مانده‌ی خرید بلیط ناموفق بود، صندلی‌های رزروشده رو آزاد کن."""
    from matches.models import MatchSeat
    from tickets.models import Ticket
    from tickets.reservation import SeatReservation
    from django.db import transaction

    seat_ids = [
        int(v) for k, v in payment.buyer_info.items()
        if k.startswith('match_seat_id_')
    ]
    if not seat_ids:
        return

    with transaction.atomic():
        # ===== حتی وقتی کل پرداخت «ناموفق» علامت می‌خوره، ممکنه یکی از
        # صندلی‌های همین سفارش قبلش (توی _finalize_ticket_purchase، نگهبانِ
        # دوبار-فروش) بلیط واقعی گرفته باشه -- مثلاً سفارش تک‌صندلی‌ای که
        # همون یک صندلی از قبل بلیط داشت، پس finalize صفر بلیط ساخت و کلِ
        # پرداخت "ناموفق" علامت خورد. اگه اینجا بدون چک، is_available رو
        # True کنیم، دقیقاً همون صندلیِ از-قبل-فروخته‌شده رو دوباره «آزاد»
        # نشون می‌دیم و امکان فروش سوم رو باز می‌کنیم. =====
        ticketed_seat_ids = set(
            Ticket.objects.filter(
                match_seat_id__in=seat_ids, status__in=['paid', 'admin_assigned', 'vip_issued']
            ).values_list('match_seat_id', flat=True)
        )
        seat_ids_to_release = [sid for sid in seat_ids if sid not in ticketed_seat_ids]
        if seat_ids_to_release:
            MatchSeat.objects.filter(
                id__in=seat_ids_to_release, match_id=payment.match_id
            ).update(is_available=True, reserved_until=None)
        seat_ids = seat_ids_to_release

    SeatReservation.release_many(seat_ids, force=True)


def _finalize_ticket_purchase(payment, gateway_amount_paid):
    from tickets.models import Ticket, Order, DiscountCode, SpecialCode
    from matches.models import Match, MatchSeat, get_block_price_map, get_basa_discount_percent
    from tickets.reservation import SeatReservation
    from wallet.models import Wallet
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
        pre_code_discount_total = 0  # جمع قیمت‌ها بعد از تخفیف باسا، قبل از کد تخفیف -- برای subtotal سفارش
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
                .select_for_update(of=('self',))
                .select_related('seat__row__block')
                .filter(id__in=match_seat_pks, match=match)
            )
        }

        block_price_map = get_block_price_map(match)
        basa_discount_percent = get_basa_discount_percent(match)
        basa_national_codes = set()
        if basa_discount_percent > 0:
            basa_national_codes = set(User.objects.filter(is_basa_member=True).values_list('national_code', flat=True))
        used_special_code_pks = set()  # جلوگیری از استفاده‌ی یک کد ویژه برای دو صندلی در همین سفارش

        for pk in match_seat_pks:
            pk_str = str(pk)
            full_name = payment.buyer_info.get(f'full_name_{pk_str}', '')
            national_code = payment.buyer_info.get(f'national_code_{pk_str}', '')
            tarikhe_tavallod = payment.buyer_info.get(f'tarikhe_tavallod_{pk_str}', '')

            match_seat = locked_seats.get(pk)
            if not match_seat:
                continue

            # ===== تصمیم «رایگانه یا نه» فقط از روی سنِ تأییدشده‌ی کش‌شده در
            # inquiry_fan گرفته می‌شود -- نه از tarikhe_tavallod که همینجا از
            # buyer_info خونده می‌شه و اون هم چیزی جز یک فیلد فرم که کاربر
            # موقع submit فرستاده نیست (کاملاً سمت کلاینت قابل‌دستکاریه؛ کاربر
            # می‌توانست بعد از یک استعلام موفق برای خودش، این فیلد مخفی را با
            # DevTools به یک سال اخیر تغییر دهد و بلیط بزرگسال را رایگان
            # بگیرد). اگر استعلام تأییدشده‌ای موجود نباشد (پیش‌فرض امن)، رایگان
            # محسوب نمی‌شود. raw_age فقط برای نمایش روی خودِ بلیط استفاده می‌شود.
            raw_age = get_age_from_jalali(tarikhe_tavallod)
            verified_age = get_verified_age(user.id, national_code)
            is_free = is_free_for_age(verified_age)
            age = verified_age if verified_age is not None else raw_age

            block = match_seat.seat.row.block
            base_price = block_price_map.get(block.id, block.price) if block else 0
            seat_price = 0 if is_free else base_price
            basa_discount_amount = 0
            if seat_price and basa_discount_percent > 0 and national_code in basa_national_codes:
                discounted_price = seat_price - int(seat_price * basa_discount_percent / 100)
                basa_discount_amount = seat_price - discounted_price
                seat_price = discounted_price

            pre_code_discount_total += seat_price

            # ===== کد تخفیف هم مثل تخفیف باسا روی قیمت خودِ همین بلیط اعمال
            # می‌شود، نه فقط روی مجموع در انتها -- وگرنه Ticket.price هیچ‌وقت
            # این تخفیف را نشان نمی‌داد (مثلاً با کد ۱۰۰٪ بلیط رایگان بود ولی
            # قیمت ثبت‌شده‌ی خودِ بلیط هنوز قیمت کامل را نشان می‌داد) و جمع
            # قیمت بلیط‌ها که برای «درآمد کل» در گزارش مالی استفاده می‌شود، از
            # مبلغ واقعاً دریافتی بیشتر می‌شد. =====
            seat_discount_code_amount = 0
            if seat_price and payment.discount_percent > 0:
                discounted_price = seat_price - int(seat_price * payment.discount_percent / 100)
                seat_discount_code_amount = seat_price - discounted_price
                seat_price = discounted_price

            # ===== کد ویژه (SpecialCode) -- درست مثل مسیر کیف‌پول/رایگان،
            # اگر کاربر برای همین صندلی یک کد ویژه‌ی معتبر وارد کرده باشد،
            # این بلیط کاملاً رایگان می‌شود، مستقل از بقیه‌ی محاسبات. =====
            special_code_input = (payment.buyer_info.get(f'special_code_{pk_str}') or '').strip().upper()
            special_code_obj = None
            # ===== اگر این صندلی از قبل به‌خاطر سن زیر ۱۵ سال رایگانه، کد ویژه
            # نادیده گرفته می‌شود (نه مصرف/نه خطا) -- همون‌طور که توی مسیر
            # رایگان/کیف‌پول (tickets/views.py) هست، نباید کدِ یک‌بارمصرفِ کاربر
            # ویژه روی بلیطی که مجانی سن است هدر بره یا این بلیط توی گزارش‌ها
            # به‌جای «رایگان زیر ۱۵ سال» زیر «کد ویژه» شمرده بشه. =====
            if special_code_input and not is_free:
                try:
                    special_code_obj = SpecialCode.objects.select_for_update().get(code=special_code_input)
                    valid, _msg = special_code_obj.is_valid(match=match)
                    if not valid or special_code_obj.pk in used_special_code_pks:
                        special_code_obj = None
                except SpecialCode.DoesNotExist:
                    special_code_obj = None
            if special_code_obj:
                used_special_code_pks.add(special_code_obj.pk)
                seat_price = 0
                seat_discount_code_amount = 0

            actual_total_price += seat_price
            processed_seats_data.append({
                'match_seat': match_seat,
                'full_name': full_name,
                'national_code': national_code,
                'price': seat_price,
                'age': age,
                'basa_discount_amount': basa_discount_amount,
                'discount_code_amount': seat_discount_code_amount,
                'special_code': special_code_obj,
            })

        discount_amount = pre_code_discount_total - actual_total_price
        total_amount = actual_total_price

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
            user=user, match=match, subtotal=pre_code_discount_total,
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

        # ===== بازگشت مابه‌التفاوت پرداخت اضافی به کیف پول =====
        # gateway_amount_paid روی مبلغی قفل شده که موقع باز کردن صفحه‌ی
        # پرداخت به زیبال فرستاده شده بود؛ اگر بین آن لحظه و همین‌جا (بعد از
        # برگشت از درگاه) قیمت بلوک عوض شده باشد، total_amount که همین بالا
        # از روی block_price_map محاسبه شد می‌تواند از چیزی که کاربر واقعاً
        # پرداخت کرده کمتر باشد. آن پول واقعاً از کاربر گرفته شده، پس باید
        # مابه‌التفاوتش را به کیف پولش برگردانیم، نه اینکه بی‌صدا گم شود.
        overpaid_amount = (gateway_amount_paid + wallet_amount_used) - total_amount
        if overpaid_amount > 0:
            wallet.add_balance(
                amount=overpaid_amount,
                description=(
                    f"بازگشت مابه‌التفاوت قیمت بلیط (تغییر قیمت حین پرداخت) - "
                    f"سفارش #{order.order_number} - مسابقه {match.home_team} vs {match.away_team}"
                ),
                reference_id=f"OVERPAY-{order.id}",
                tx_type='refund',
            )
            logger.warning(
                f"Overpayment refunded to wallet for order {order.id} (payment {payment.id}): "
                f"charged={gateway_amount_paid + wallet_amount_used}, required={total_amount}, "
                f"refunded={overpaid_amount}"
            )

        tickets_created = []
        processed_national_codes = set()

        for seat_data in processed_seats_data:
            match_seat = seat_data['match_seat']
            full_name = seat_data['full_name']
            national_code = seat_data['national_code']
            seat_price = seat_data['price']
            seat_age = seat_data['age']
            seat_basa_discount = seat_data['basa_discount_amount']
            seat_discount_code_amount = seat_data['discount_code_amount']
            seat_special_code = seat_data['special_code']

            # ===== نگهبان نهایی و قطعی در برابر دوبار-فروش (همون فیکسِ مسیر
            # کیف‌پول/رایگان در tickets/views.py) -- match_seat بالاتر با
            # select_for_update قفل شده؛ اینجا مستقیماً و اتمیک چک می‌کنیم که
            # این صندلی از قبل هیچ بلیطی (پولی، سهمیه‌ی VIP، یا صدور دستی
            # ادمین) نداشته باشه -- نه فقط 'paid'، چون is_available هم می‌تونه
            # از واقعیت جدا بیفته. برخلاف مسیر کیف‌پول نمی‌شه اینجا کاربر رو
            # برگردوند چون پول از قبل از طریق زیبال گرفته شده -- فقط از ساختِ
            # بلیط تکراری روی همین صندلی جلوگیری می‌کنیم (بدون دست‌زدن به
            # is_available چون صندلی واقعاً متعلق به همون خریدار قبلیه) و برای
            # پیگیری دستی (بازگشت وجه/تعویض صندلی) لاگ می‌کنیم؛ بقیه‌ی
            # صندلی‌های همین سفارش عادی پردازش می‌شن. =====
            if Ticket.objects.filter(match_seat=match_seat, status__in=['paid', 'admin_assigned', 'vip_issued']).exists():
                logger.error(
                    f"DOUBLE-BOOKING PREVENTED: seat {match_seat.id} (seat number {match_seat.seat.number}) "
                    f"already has a paid ticket. Payment {payment.id} (order {order.id}, user {user.username}, "
                    f"national_code={national_code}) needs manual refund/reseat."
                )
                continue

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
                discount_code=discount_obj if seat_discount_code_amount > 0 else None,
                discount_code_amount=seat_discount_code_amount,
                special_code=seat_special_code,
            )
            tickets_created.append(ticket)

            if seat_special_code is not None:
                seat_special_code.is_used = True
                seat_special_code.used_at = timezone.now()
                seat_special_code.save(update_fields=['is_used', 'used_at'])

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
