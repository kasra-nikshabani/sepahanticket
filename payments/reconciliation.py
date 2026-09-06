"""تک‌منبعِ حقیقت برای «چقدر به این کاربر بدهکاریم؟»

چرا یک ماژول جدا
----------------
دو مصرف‌کننده دارد و اگر هرکدام نسخه‌ی خودش را داشته باشد، دیر یا زود از هم
واگرا می‌شوند و آن واگرایی روی پول واقعی مردم می‌نشیند:

* audit_payment_ticket_balance -- گزارش می‌دهد چه کسی طلبکار است.
* sweep_pending_payments -- پیش از هر بازگشت وجهی، سقفش را از همین‌جا
  می‌گیرد.

مورد دوم درسِ گران‌قیمتی است. اولین نسخه‌ی جاروکش، پرداختی را که زیبال
تأیید کرده بود «پول گرفته شده» بی‌قید و شرط برمی‌گرداند. ولی ۲۱٬۷۱۴ پرداختِ
شب دربی از قبل دستی جبران شده بودند؛ اجرای آن نسخه یعنی پرداخت دوباره به
صدها نفر. محدودکردن به بازه‌ی زمانی جلویش را نمی‌گرفت (دربی فقط شش روز
قبل بود). تنها نگهبانِ درست این است: هیچ‌وقت بیشتر از بدهیِ باقی‌مانده
پرداخت نکن.

    بدهی = (پولِ گرفته‌شده از درگاه + پرداختی از کیف پول)
           − ارزش بلیط‌های تحویل‌شده
           − هر بازگشتی که قبلاً گرفته

«پولِ گرفته‌شده» از Payment.gateway_captured_at می‌آید، نه از status --
چون status سرنوشت سفارش را می‌گوید نه سرنوشت پول را.
"""
from collections import defaultdict

from django.db.models import Q, Sum

from payments.models import Payment
from tickets.models import Ticket
from wallet.models import Transaction as WalletTx

OCCUPIED = ['paid', 'admin_assigned', 'vip_issued']

# اختلاف کمتر از این مقدار، خطای گِردکردن است نه بدهی (ریال)
TOLERANCE = 1_000


def settlement_references(match):
    """همه‌ی reference_id هایی که «پولِ برگشته بابت این مسابقه» را نشان می‌دهند.

    عمداً از روی شناسه‌ی پرداخت‌های همین مسابقه ساخته می‌شود و نه با پیشوندِ
    خام، تا بازگشتِ مسابقه‌ی دیگر به‌اشتباه اینجا حساب نشود.
    """
    refs = set()
    for pid, track_id in Payment.objects.filter(
            match=match, purpose='ticket_purchase').values_list('id', 'track_id'):
        refs.update({f'refund-{track_id}', f'SHORTFALL-{pid}', f'OVERPAY-{pid}'})
    return refs


def match_balances(match):
    """تراز همه‌ی کاربران این مسابقه: uid -> dict

    خروجی هر کاربر: captured, wallet_used, delivered, refunded, owed
    """
    captured = defaultdict(int)
    wallet_used = defaultdict(int)

    # مبنا gateway_captured_at است؛ شرط status='success' فقط برای رکوردهای
    # قدیمی‌ای است که پیش از افزوده‌شدن آن فیلد ثبت شده‌اند.
    for uid, amount, w_used in Payment.objects.filter(
            match=match, purpose='ticket_purchase').filter(
            Q(gateway_captured_at__isnull=False) | Q(status='success')
    ).values_list('user_id', 'gateway_amount', 'wallet_amount_used'):
        captured[uid] += amount or 0
        wallet_used[uid] += w_used or 0

    delivered = defaultdict(int)
    for uid, price in Ticket.objects.filter(
            match=match, status__in=OCCUPIED).values_list('user_id', 'price'):
        delivered[uid] += price or 0

    refunded = defaultdict(int)
    for uid, s in WalletTx.objects.filter(is_wallet=True, amount__gt=0).filter(
            Q(reference_id__in=settlement_references(match))
            | Q(reference_id__startswith=f'compensate-{match.id}-')
    ).values_list('user_id').annotate(s=Sum('amount')):
        refunded[uid] += s or 0

    out = {}
    for uid in set(captured) | set(delivered) | set(refunded):
        owed = (captured[uid] + wallet_used[uid]) - delivered[uid] - refunded[uid]
        out[uid] = {
            'captured': captured[uid], 'wallet_used': wallet_used[uid],
            'delivered': delivered[uid], 'refunded': refunded[uid], 'owed': owed,
        }
    return out


def user_balance(match, user_id):
    """تراز یک کاربر -- با کوئری‌های هدفمند، نه اسکن کل مسابقه.

    عمداً کش نمی‌شود: جاروکش بین دو پرداختِ همان کاربر، خودش تراز را عوض
    می‌کند (بازگشت وجه می‌زند یا بلیط صادر می‌کند). خواندن از یک تصویرِ
    قدیمی یعنی همان اضافه‌پرداختی که این ماژول برای جلوگیری از آن ساخته شد.
    """
    captured = wallet_used = 0
    refs = set()
    for pid, track_id, amount, w_used, cap_at, status in Payment.objects.filter(
            match=match, purpose='ticket_purchase', user_id=user_id
    ).values_list('id', 'track_id', 'gateway_amount', 'wallet_amount_used',
                  'gateway_captured_at', 'status'):
        refs.update({f'refund-{track_id}', f'SHORTFALL-{pid}', f'OVERPAY-{pid}'})
        if cap_at is not None or status == 'success':
            captured += amount or 0
            wallet_used += w_used or 0

    delivered = Ticket.objects.filter(
        match=match, user_id=user_id, status__in=OCCUPIED
    ).aggregate(s=Sum('price'))['s'] or 0

    refunded = WalletTx.objects.filter(is_wallet=True, amount__gt=0, user_id=user_id).filter(
        Q(reference_id__in=refs) | Q(reference_id__startswith=f'compensate-{match.id}-')
    ).aggregate(s=Sum('amount'))['s'] or 0

    return {'captured': captured, 'wallet_used': wallet_used, 'delivered': delivered,
            'refunded': refunded, 'owed': (captured + wallet_used) - delivered - refunded}


def amount_still_owed(match, user_id):
    """چقدر *هنوز* به این کاربر بدهکاریم -- سقفِ مجاز برای هر بازگشت وجه.

    هرگز عدد منفی برنمی‌گرداند: اگر کاربر از قبل تسویه یا بیش‌جبران شده،
    جواب صفر است و هیچ پولی نباید پرداخت شود.
    """
    return max(0, user_balance(match, user_id)['owed'])
