"""Validate cultural purchases and calculate prices from server inventory."""
from decimal import Decimal, InvalidOperation
import re
from django.utils import timezone
from matches.models import MatchSeat, get_active_row_ids, get_active_block_ids, get_seat_price_map
from wallet.models import is_wallet_enabled, Wallet
from .models import DiscountCode, Ticket
from .reservation import SeatReservation


def validate_purchase(request, match):
    if not match.sales_available:
        raise ValueError('فروش این سانس در دسترس نیست.')
    try:
        selected = [int(value) for value in request.session.get('selected_seats', [])]
        submitted = []
        for key, value in request.POST.items():
            if key.startswith('match_seat_id_'):
                seat_id = int(value)
                if key != f'match_seat_id_{seat_id}':
                    raise ValueError('شناسه صندلی معتبر نیست.')
                submitted.append(seat_id)
    except (TypeError, ValueError):
        raise ValueError('صندلی‌های انتخاب‌شده معتبر نیستند.')
    if not selected or len(selected) != len(set(selected)) or sorted(selected) != sorted(submitted):
        raise ValueError('صندلی‌ها را دوباره انتخاب کنید.')
    seats = list(MatchSeat.objects.filter(pk__in=selected, match=match, is_enabled=True,
        seat__is_available=True, seat__row_id__in=get_active_row_ids(match),
        seat__row__block_id__in=get_active_block_ids(match)).select_related('seat__row__block'))
    if len(seats) != len(selected):
        raise ValueError('یکی از صندلی‌ها برای این سانس فعال نیست.')
    if Ticket.objects.filter(match_seat_id__in=selected, status__in=['paid', 'admin_assigned', 'vip_issued']).exists():
        raise ValueError('یکی از صندلی‌ها قبلاً فروخته شده است.')
    prices = get_seat_price_map(match, [item.seat for item in seats])
    subtotal = 0
    for seat in seats:
        if not SeatReservation.is_reserved_by_user(seat.pk, request.user.pk):
            raise ValueError('رزرو صندلی منقضی شده است؛ دوباره انتخاب کنید.')
        if seat.reserved_until and seat.reserved_until <= timezone.now():
            raise ValueError('مهلت رزرو به پایان رسیده است.')
        name = request.POST.get(f'full_name_{seat.pk}', '').strip()
        if not name or len(name) > 200:
            raise ValueError('نام دارنده هر بلیط را وارد کنید (حداکثر ۲۰۰ حرف).')
        if request.POST.get(f'special_code_{seat.pk}', '').strip():
            raise ValueError('برای این خرید از کد تخفیف سفارش استفاده کنید.')
        subtotal += int(prices[seat.seat_id])
    code = request.POST.get('discount_code', '').strip()
    percent = 0
    if code:
        discount = DiscountCode.objects.filter(code=code).first()
        if discount is None:
            raise ValueError('کد تخفیف یافت نشد.')
        valid, message = discount.is_valid(match=match)
        if not valid:
            raise ValueError(message)
        if discount.block_id and any(seat.seat.row.block_id != discount.block_id for seat in seats):
            raise ValueError('این کد تخفیف برای بخش انتخاب‌شده معتبر نیست.')
        percent = discount.discount_percent
    # Match the existing per-ticket rounding used by issuance and reconciliation.
    total = sum(int(prices[seat.seat_id]) -
                int(int(prices[seat.seat_id]) * percent / 100)
                for seat in seats)
    wallet_amount = wallet_amount_from_post(request.POST)
    if not is_wallet_enabled() or request.POST.get('use_wallet') != 'true':
        wallet_amount = 0
    balance = Wallet.objects.filter(user=request.user).values_list('balance', flat=True).first() or 0
    if wallet_amount < 0 or wallet_amount > min(total, balance):
        raise ValueError('مبلغ کیف پول از موجودی یا مبلغ سفارش بیشتر است.')
    return total, wallet_amount
def wallet_amount_from_post(post):
    """Accept the public toman field; preserve rial input for existing callers."""
    if 'wallet_amount_toman' not in post:
        try:
            return int(post.get('wallet_amount', '0') or 0)
        except (ValueError, TypeError):
            raise ValueError('مبلغ کیف پول معتبر نیست.')
    raw = str(post.get('wallet_amount_toman', '') or '0').strip()
    raw = raw.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬', '01234567890123456789.,')).replace(',', '')
    if not re.fullmatch(r'\d{1,15}(?:\.\d)?', raw):
        raise ValueError('مبلغ کیف پول را به تومان وارد کنید (حداکثر یک رقم اعشار).')
    try:
        amount = Decimal(raw) * 10
        return int(amount)
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError('مبلغ کیف پول معتبر نیست.')
