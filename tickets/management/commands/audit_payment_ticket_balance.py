"""تراز پول و بلیط: آیا کسی پول داده و چیزی که خریده را نگرفته؟

چرا این نسخه با نسخه‌ی قبلی فرق دارد
------------------------------------
نسخه‌ی اول *صندلی* می‌شمرد و فقط پرداخت‌های status='success' را می‌دید. هر دو
انتخاب، نقطه‌ی کور داشتند و هر دو نقطه‌ی کور در بازی ۶۶ فعال شدند:

۱) پرداختی که کاربر انجام داده ولی به سایت برنگشته، تا ابد 'pending' می‌ماند.
   گزارش قبلی آن را «پرداخت‌نشده» می‌دید و با اطمینان می‌گفت «تراز درست است»
   در حالی که پول دو کاربر نزد باشگاه مانده بود.

۲) شمردنِ صندلی وقتی جواب می‌دهد که همه‌ی بلیط‌ها هم‌قیمت باشند. کاربری که
   ۷٬۰۰۰٬۰۰۰ ریال پرداخت کرده بود و ۱۲ بلیط داشت (۸ تای رایگانِ زیر ۱۵ سال)
   از نظر «تعداد صندلی» بستانکار به‌نظر می‌رسید، در حالی که ۲٬۰۰۰٬۰۰۰ ریال
   طلبکار بود.

این نسخه به‌جای صندلی، *پول* را می‌شمارد و مبنای «پول گرفته شد» را
Payment.gateway_captured_at می‌گذارد -- فیلدی که فقط یک چیز می‌گوید: زیبال
تأیید کرده پول از کاربر کم شده، مستقل از اینکه بلیط صادر شد یا نه.

    تراز هر کاربر = (پولِ گرفته‌شده از درگاه + پرداختی از کیف پول)
                    − ارزش بلیط‌های تحویل‌شده
                    − هر بازگشتی که قبلاً گرفته

برای اجرای دوره‌ای (systemd timer) ساخته شده: اگر چیزی پیدا نشود ساکت است،
اگر پیدا شود با کد خروجی ۱ برمی‌گردد تا مانیتورینگ ببیند.
"""
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from matches.models import Match
from payments.models import Payment
from payments.reconciliation import TOLERANCE, match_balances


class Command(BaseCommand):
    OCCUPIED = ['paid', 'admin_assigned', 'vip_issued']
    help = 'گزارش کاربرانی که پول داده‌اند ولی معادلش را نگرفته‌اند'

    def add_arguments(self, parser):
        parser.add_argument('--match-id', type=int,
                            help='فقط یک مسابقه؛ بدون آن، همه‌ی مسابقات فعال')
        parser.add_argument('--stale-minutes', type=int, default=45,
                            help='پرداخت معلقِ قدیمی‌تر از این، «وضعیت نامعلوم» شمرده می‌شود')
        parser.add_argument('--verbose-ok', action='store_true',
                            help='حتی وقتی همه‌چیز سالم است، جزئیات را چاپ کن')

    def handle(self, *args, **opts):
        matches = ([Match.objects.get(id=opts['match_id'])] if opts['match_id']
                   else list(Match.objects.filter(is_active=True)))
        problems = False

        for match in matches:
            rows = self._audit(match)
            stale = self._stale_pending(match, opts['stale_minutes'])

            if rows:
                problems = True
                total = sum(r[1] for r in rows)
                self.stdout.write(self.style.ERROR(
                    f'\n[مسابقه {match.id}] {len(rows)} کاربر طلبکار — {total:,} ریال'))
                for uid, owed, captured, wallet_used, delivered, refunded, phone in rows[:20]:
                    self.stdout.write(
                        f'   کاربر {uid} ({phone or "-"}): طلب={owed:,} '
                        f'[گرفته‌شده={captured:,} کیف‌پول={wallet_used:,} '
                        f'تحویل‌شده={delivered:,} برگشته={refunded:,}]')
                if len(rows) > 20:
                    self.stdout.write(f'   ... و {len(rows) - 20} کاربر دیگر')

            # ===== وضعیت نامعلوم هم باید دیده شود =====
            # پرداختی که مدت‌هاست معلق مانده یعنی «نمی‌دانیم پول گرفته شد یا
            # نه». سکوت درباره‌اش همان اشتباهی است که یک بار کردیم؛ اینجا
            # صریحاً گزارش می‌شود تا جاروکش سراغش برود.
            if stale:
                problems = True
                self.stdout.write(self.style.WARNING(
                    f'[مسابقه {match.id}] {len(stale)} پرداختِ معلقِ تعیین‌تکلیف‌نشده '
                    f'({sum(s[1] for s in stale):,} ریال) — '
                    f'sweep_pending_payments باید اجرا شود'))
                for pid, amt, uid in stale[:10]:
                    self.stdout.write(f'   پرداخت {pid} کاربر {uid} مبلغ {amt:,} ریال')

            if not rows and not stale and opts['verbose_ok']:
                self.stdout.write(self.style.SUCCESS(f'[مسابقه {match.id}] تراز درست است.'))

        if not problems:
            self.stdout.write(self.style.SUCCESS(
                'تراز درست است: هیچ کاربری پول داده‌ی بی‌معادل ندارد و پرداخت بلاتکلیفی نمانده.'))
            return
        sys.exit(1)

    # ------------------------------------------------------------------
    def _stale_pending(self, match, minutes):
        cutoff = timezone.now() - timedelta(minutes=minutes)
        return list(Payment.objects
                    .filter(match=match, purpose='ticket_purchase', status='pending',
                            gateway_captured_at__isnull=True, created_at__lte=cutoff)
                    .exclude(track_id__isnull=True).exclude(track_id='')
                    .values_list('id', 'gateway_amount', 'user_id'))

    def _audit(self, match):
        # محاسبه در payments/reconciliation انجام می‌شود -- همان کدی که
        # sweep_pending_payments سقفِ بازگشت وجه را از آن می‌گیرد. اگر این دو
        # نسخه‌ی جدا داشتند، دیر یا زود از هم واگرا می‌شدند و آن واگرایی روی
        # پول واقعی مردم می‌نشست.
        balances = match_balances(match)
        phones = dict(Payment.objects.filter(match=match).values_list(
            'user_id', 'user__phone_number'))

        out = [
            (uid, b['owed'], b['captured'], b['wallet_used'],
             b['delivered'], b['refunded'], phones.get(uid))
            for uid, b in balances.items() if b['owed'] > TOLERANCE
        ]
        out.sort(key=lambda r: -r[1])
        return out
