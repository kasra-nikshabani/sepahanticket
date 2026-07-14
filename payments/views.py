import logging
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from zibal_payment.client import ZibalClient

logger = logging.getLogger(__name__)


def payment_request(request):
    logger.info("===== وارد ویو payment_request شد =====")

    if request.method != 'POST':
        return redirect('matches:home')

    # ===== دریافت اطلاعات از فرم =====
    amount = request.POST.get('amount')
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        messages.error(request, "مبلغ نامعتبر است")
        return redirect('wallet:dashboard')

    if amount <= 0:
        messages.error(request, "مبلغ باید بزرگتر از صفر باشد")
        return redirect('wallet:dashboard')

    # ===== ذخیره اطلاعات در سشن =====
    match_id = request.POST.get('match_id')
    if match_id:
        request.session['pending_match_id'] = int(match_id)

    buyer_info = {}
    for key, value in request.POST.items():
        if key.startswith('full_name_') or key.startswith('national_code_'):
            buyer_info[key] = value
    if buyer_info:
        request.session['pending_buyer_info'] = buyer_info

    discount_code = request.POST.get('discount_code', '')
    discount_percent = request.POST.get('discount_percent', '0')
    if discount_code:
        request.session['pending_discount_code'] = discount_code
        request.session['pending_discount_percent'] = int(discount_percent)

    # ===== تعیین آدرس بازگشت =====
    next_url = request.POST.get('next_url', '')
    if not next_url:
        next_url = reverse('tickets:user_tickets')
    request.session['payment_next_url'] = next_url

    # ===== ایجاد کلاینت زیبال =====
    client = ZibalClient(
        merchant_id=settings.ZIBAL_MERCHANT_ID,
        sandbox=settings.ZIBAL_SANDBOX
    )

    try:
        response = client.payment_request(
            amount=amount,  # مقدار به ریال
            callback_url=settings.ZIBAL_CALLBACK_URL,
            description="پرداخت بلیط"  # ← تغییر توضیح
        )

        track_id = response.get('trackId')
        if track_id:
            request.session['track_id'] = track_id
            request.session['payment_amount'] = amount
            payment_url = client.generate_payment_url(track_id)
            return redirect(payment_url)
        else:
            messages.error(request, "خطا در شروع پرداخت")
            return redirect('wallet:dashboard')

    except Exception as e:
        logger.error(f"خطا در درخواست پرداخت: {e}")
        messages.error(request, "خطا در ارتباط با درگاه پرداخت")
        return redirect('wallet:dashboard')


def payment_verify(request):
    """تایید پرداخت پس از بازگشت از زیبال"""
    print("===== PAYMENT VERIFY CALLED =====")
    print(f"GET params: {request.GET}")

    # ===== دریافت track_id =====
    track_id = request.GET.get('trackId') or request.GET.get('track_id') or request.session.get('track_id')

    if not track_id:
        print("❌ NO track_id in GET or SESSION")
        messages.error(request, "اطلاعات پرداخت یافت نشد")
        return redirect('tickets:user_tickets')

    print(f"✅ track_id found: {track_id}")

    # ===== ایجاد کلاینت زیبال =====
    client = ZibalClient(
        merchant_id=settings.ZIBAL_MERCHANT_ID,
        sandbox=settings.ZIBAL_SANDBOX
    )

    next_url = request.session.get('payment_next_url', reverse('tickets:user_tickets'))

    try:
        result = client.payment_verify(track_id=track_id)
        result_code = result.get('result')

        if result_code == 100:
            # ===== پرداخت موفق =====
            amount = result.get('amount', 0)  # مبلغ به ریال از زیبال برمی‌گردد

            # ================================================================
            # ===== ❌ بخش شارژ کیف پول حذف شد =====
            # ===== مبلغ فقط برای خرید بلیط استفاده می‌شود =====
            # ================================================================

            # ===== ۱. صدور بلیط =====
            match_id = request.session.get('pending_match_id')
            buyer_info = request.session.get('pending_buyer_info', {})
            discount_code = request.session.get('pending_discount_code', '')
            discount_percent = request.session.get('pending_discount_percent', 0)

            tickets_created = []
            order = None

            if match_id and buyer_info:
                try:
                    from tickets.models import Ticket, Order, DiscountCode
                    from matches.models import Match, MatchSeat
                    from tickets.reservation import SeatReservation

                    match = Match.objects.get(id=match_id)

                    # ===== محاسبه قیمت کل (به ریال) =====
                    total_price = 0
                    for key, full_name in buyer_info.items():
                        if key.startswith('full_name_'):
                            match_seat_pk = key.replace('full_name_', '')
                            try:
                                match_seat = MatchSeat.objects.select_related(
                                    'seat__row__block'
                                ).get(id=int(match_seat_pk), match=match)
                                price = match_seat.seat.row.block.price if match_seat.seat.row.block else 0
                                total_price += price
                            except MatchSeat.DoesNotExist:
                                pass

                    # ===== محاسبه تخفیف =====
                    discount_obj = None
                    if discount_code:
                        try:
                            discount_obj = DiscountCode.objects.get(code=discount_code)
                            discount_percent = discount_obj.discount_percent
                        except DiscountCode.DoesNotExist:
                            pass

                    discounted_total = total_price - int(total_price * discount_percent / 100)

                    # ===== ایجاد سفارش =====
                    order = Order.objects.create(
                        user=request.user,
                        match=match,
                        subtotal=total_price,
                        discount_percent=discount_percent,
                        discount_amount=int(total_price * discount_percent / 100),
                        total_amount=discounted_total,
                        wallet_balance_before=0,  # چون از کیف پول استفاده نشده
                        wallet_amount=0,
                        wallet_balance_after=0,
                        payment_method='zibal',
                        payment_status='paid',
                        discount_code=discount_obj.code if discount_obj else '',
                        discount_code_id=discount_obj.id if discount_obj else None,
                        full_name=request.user.get_full_name() or request.user.username,
                        phone_number=getattr(request.user, 'phone_number', ''),
                        track_id=track_id,
                        paid_at=timezone.now(),
                    )
                    print(f"✅ Order created: {order.order_number}")

                    # ===== پردازش اطلاعات خریدار =====
                    for key, full_name in buyer_info.items():
                        if key.startswith('full_name_'):
                            match_seat_pk = key.replace('full_name_', '')
                            national_code_key = f'national_code_{match_seat_pk}'
                            national_code = buyer_info.get(national_code_key, '')

                            try:
                                match_seat = MatchSeat.objects.select_related(
                                    'seat__row__block'
                                ).get(id=int(match_seat_pk), match=match)

                                ticket = Ticket.objects.create(
                                    match=match,
                                    seat=match_seat.seat,
                                    match_seat=match_seat,
                                    user=request.user,
                                    full_name=full_name,
                                    national_code=national_code,
                                    status='paid',
                                    is_admin_assigned=False,
                                    order=order,
                                )
                                tickets_created.append(ticket)

                                match_seat.is_available = False
                                match_seat.reserved_until = None
                                match_seat.save()
                                SeatReservation.release(match_seat.id)

                                print(f"✅ Ticket created for match_seat {match_seat_pk}")

                            except MatchSeat.DoesNotExist:
                                print(f"❌ MatchSeat {match_seat_pk} not found")
                                messages.warning(
                                    request,
                                    f"صندلی با شناسه {match_seat_pk} یافت نشد."
                                )
                                continue

                            except Exception as e:
                                print(f"❌ Error creating ticket for match_seat {match_seat_pk}: {e}")
                                continue

                    # ===== افزایش استفاده از کد تخفیف =====
                    if discount_obj and tickets_created:
                        try:
                            discount_obj.used_count += 1
                            discount_obj.save()
                            print(f"✅ Discount code {discount_obj.code} usage updated")
                        except Exception as e:
                            print(f"⚠️ Could not update discount usage: {e}")

                    # ===== پاک کردن سشن =====
                    request.session.pop('pending_match_id', None)
                    request.session.pop('pending_buyer_info', None)
                    request.session.pop('pending_discount_code', None)
                    request.session.pop('pending_discount_percent', None)
                    request.session.pop('payment_next_url', None)
                    request.session.pop('track_id', None)

                except Match.DoesNotExist:
                    print(f"❌ Match {match_id} not found")
                    messages.error(request, "مسابقه مورد نظر یافت نشد.")

                except Exception as e:
                    print(f"❌ Error in ticket issuance: {e}")
                    messages.error(request, f"خطا در صدور بلیط: {str(e)}")

            # ===== نمایش پیام نهایی =====
            if tickets_created:
                messages.success(
                    request,
                    f"✅ پرداخت مبلغ {amount:,} ریال با موفقیت انجام شد. "
                    f"{len(tickets_created)} بلیط صادر شد."
                )
            else:
                if match_id and buyer_info:
                    messages.warning(
                        request,
                        "پرداخت موفق بود اما هیچ بلیطی صادر نشد. لطفاً دوباره تلاش کنید."
                    )
                else:
                    messages.success(
                        request,
                        f"✅ پرداخت مبلغ {amount:,} ریال با موفقیت انجام شد."
                    )

            return redirect(next_url)

        else:
            # ===== پرداخت ناموفق =====
            error_messages = {
                101: "تراکنش قبلاً تایید شده است",
                102: "تراکنش ناموفق بوده است",
                103: "خطای امنیتی",
                104: "کد مرچنت نامعتبر",
                105: "مبلغ نامعتبر",
                106: "آدرس بازگشت نامعتبر",
            }
            error_msg = error_messages.get(result_code, f"کد خطای {result_code}")
            messages.error(request, f"❌ پرداخت ناموفق! {error_msg}")

            request.session.pop('pending_match_id', None)
            request.session.pop('pending_buyer_info', None)
            request.session.pop('payment_next_url', None)
            request.session.pop('track_id', None)

            return redirect(next_url)

    except Exception as e:
        print(f"❌ Unexpected error in payment_verify: {e}")
        logger.error(f"خطا در تایید پرداخت: {e}")
        messages.error(request, "❌ خطا در تایید پرداخت. لطفاً با پشتیبانی تماس بگیرید.")

        request.session.pop('pending_match_id', None)
        request.session.pop('pending_buyer_info', None)
        request.session.pop('payment_next_url', None)
        request.session.pop('track_id', None)

        return redirect(next_url)


