"""تراز پول و بلیط: آیا کسی پول داده و بلیطش را نگرفته؟

چرا لازم است
------------
تا امروز این وضعیت فقط وقتی کشف می‌شد که کاربر شکایت کند یا کسی دستی
دنبالش بگردد. شب دربی ۶۴۰ پرداخت و بعد ۱۶۳ کاربر دیگر از همین راه پیدا
شدند -- بعد از اینکه ساعت‌ها پول مردم بلاتکلیف مانده بود.

این دستور همان تراز را خودکار حساب می‌کند و برای اجرای دوره‌ای (systemd
timer / cron) ساخته شده. اگر چیزی پیدا نشود ساکت است؛ اگر پیدا شود با کد
خروجی ۱ برمی‌گردد تا مانیتورینگ آن را ببیند.

تراز هر کاربر:
    کسری = صندلی‌هایی که پولش داده شده − بلیط‌هایی که واقعاً دارد
    طلب  = کسری × قیمت − هر جبرانی که قبلاً گرفته
"""
import re
import sys
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from matches.models import Match
from payments.models import Payment
from tickets.models import Ticket
from wallet.models import Transaction as WalletTx

# پیشوندهای همه‌ی مسیرهایی که پول را به کاربر برمی‌گردانند
COMPENSATION_PREFIXES = ('compensate-', 'refund-', 'OVERPAY-', 'SHORTFALL-')


class Command(BaseCommand):
    OCCUPIED = ['paid', 'admin_assigned', 'vip_issued']
    help = 'گزارش کاربرانی که پول داده‌اند ولی بلیط کاملشان صادر نشده'

    def add_arguments(self, parser):
        parser.add_argument('--match-id', type=int,
                            help='فقط یک مسابقه؛ بدون آن، همه‌ی مسابقات فعال')
        parser.add_argument('--price', type=int, default=3000000,
                            help='قیمت مبنا برای محاسبه‌ی طلب (ریال)')

    def handle(self, *args, **opts):
        matches = ([Match.objects.get(id=opts['match_id'])] if opts['match_id']
                   else list(Match.objects.filter(is_active=True)))
        price = opts['price']
        found_any = False

        for match in matches:
            rows = self._audit(match, price)
            if not rows:
                continue
            found_any = True
            total = sum(r[3] for r in rows)
            self.stdout.write(self.style.ERROR(
                f'\n[مسابقه {match.id}] {len(rows)} کاربر طلبکار — {total:,} ریال'))
            for uid, paid_n, got, owed in sorted(rows, key=lambda r: -r[3])[:20]:
                self.stdout.write(
                    f'   کاربر {uid}: پرداخت={paid_n} صندلی  بلیط={got}  طلب={owed:,} ریال')
            if len(rows) > 20:
                self.stdout.write(f'   ... و {len(rows) - 20} کاربر دیگر')

        if not found_any:
            self.stdout.write(self.style.SUCCESS(
                'تراز درست است: هیچ کاربری پول داده‌ی بدون بلیط ندارد.'))
            return
        # کد خروجی غیرصفر تا تایمر/مانیتورینگ متوجه شود
        sys.exit(1)

    # ------------------------------------------------------------------
    def _audit(self, match, price):
        seats = defaultdict(int)
        for p in Payment.objects.filter(match=match, purpose='ticket_purchase',
                                        status='success'):
            seats[p.user_id] += len([k for k in (p.buyer_info or {})
                                     if k.startswith('match_seat_id_')])

        tickets = dict(Ticket.objects.filter(match=match, status__in=self.OCCUPIED)
                       .values_list('user_id').annotate(n=Count('id')))

        compensated = defaultdict(int)
        for pre in COMPENSATION_PREFIXES:
            for uid, s in (WalletTx.objects.filter(reference_id__startswith=pre)
                           .values_list('user_id').annotate(s=Sum('amount'))):
                compensated[uid] += s or 0

        out = []
        for uid, paid_n in seats.items():
            got = tickets.get(uid, 0)
            gap = paid_n - got
            if gap <= 0:
                continue
            owed = gap * price - compensated.get(uid, 0)
            if owed > 0:
                out.append((uid, paid_n, got, owed))
        return out
