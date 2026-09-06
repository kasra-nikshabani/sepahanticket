"""پرداخت‌های بی‌سرانجام را از زیبال استعلام می‌کند و تعیین تکلیف می‌کند.

چرا لازم است
------------
کل مسیر تأیید پرداخت به یک فرض متکی بود: «کاربر بعد از پرداخت به سایت
برمی‌گردد». هر کاری که باید بعد از گرفتن پول انجام شود -- صدور بلیط،
بازگشت وجه در صورت شکست، حتی ثبت اینکه اصلاً پولی گرفته شده -- داخل
payment_verify بود، و payment_verify فقط وقتی اجرا می‌شود که مرورگرِ کاربر
به آدرس بازگشت برسد.

اگر کاربر پرداخت کند و برنگردد (مرورگر بسته شود، اینترنت قطع شود، درگاه
ریدایرکت نکند) هیچ‌کس هرگز از زیبال نمی‌پرسد چه شد. پرداخت تا ابد
'pending' می‌ماند، پول نزد باشگاه است، کاربر نه بلیط دارد نه پولش را، و
هیچ گزارشی هم او را نمی‌بیند چون همه‌ی گزارش‌ها status='success' را
می‌شمردند. در بازی ۶۶ دقیقاً دو نفر همین‌طور شدند؛ شب دربی همین الگو در
مقیاس ۶۴۰ نفر تکرار شده بود و کشفش ساعت‌ها طول کشید.

این دستور همان فرض را حذف می‌کند: به‌جای انتظار برای کاربر، خودِ سرور
به‌صورت دوره‌ای از زیبال می‌پرسد.

قواعد ایمنی
-----------
* هر واریز به کیف پول با reference_id یکتا محافظت می‌شود؛ اجرای دوباره‌ی
  دستور هیچ‌وقت پول را دو بار برنمی‌گرداند.
* تراکنش‌های «پرداخت‌شده ولی تأییدنشده» (status=1) اول verify می‌شوند. بدون
  آن، زیبال بعد از مدتی خودش تراکنش را برمی‌گرداند و اگر ما هم بازگشت وجه
  زده باشیم، کاربر دو بار پول می‌گیرد.
* برای مسابقه‌ای که وقتش گذشته بلیط صادر نمی‌شود -- پول برمی‌گردد. بلیطِ
  بازیِ تمام‌شده به درد کسی نمی‌خورد.
* فقط پرداخت‌های تازه (پیش‌فرض ۷ روز) بررسی می‌شوند. رکوردهای قدیمی‌تر قبلاً
  دستی تسویه شده‌اند و بازکردنشان یعنی خطر پرداخت دوباره.
"""
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from payments.models import Payment

INQUIRY_URL = 'https://gateway.zibal.ir/v1/inquiry'

# در پاسخ استعلام زیبال: ۱ = پرداخت‌شده و تأییدنشده، ۲ = پرداخت‌شده و تأییدشده
ZIBAL_PAID_UNVERIFIED = 1
ZIBAL_PAID_VERIFIED = 2


class Command(BaseCommand):
    help = 'استعلام پرداخت‌های معلق/ناموفق از زیبال و تعیین تکلیف آن‌ها'

    def add_arguments(self, parser):
        parser.add_argument('--min-age', type=int, default=20,
                            help='فقط پرداخت‌های قدیمی‌تر از این تعداد دقیقه (پیش‌فرض ۲۰)')
        parser.add_argument('--max-age-days', type=int, default=7,
                            help='پرداخت‌های قدیمی‌تر از این تعداد روز نادیده گرفته می‌شوند')
        parser.add_argument('--limit', type=int, default=300,
                            help='حداکثر تعداد استعلام در هر اجرا')
        parser.add_argument('--execute', action='store_true',
                            help='بدون این گزینه فقط گزارش می‌دهد و چیزی را تغییر نمی‌دهد')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        now = timezone.now()
        qs = (Payment.objects
              .filter(status__in=['pending', 'failed'],
                      gateway_captured_at__isnull=True,
                      created_at__lte=now - timedelta(minutes=opts['min_age']),
                      created_at__gte=now - timedelta(days=opts['max_age_days']))
              .exclude(track_id__isnull=True).exclude(track_id='')
              .order_by('created_at'))

        total = qs.count()
        rows = list(qs[:opts['limit']])
        if not rows:
            self.stdout.write(self.style.SUCCESS('پرداخت بی‌سرانجامی برای بررسی نیست.'))
            return

        self.stdout.write(f'{len(rows)} پرداخت از {total} مورد بررسی می‌شود'
                          f'{"" if opts["execute"] else "  (حالت آزمایشی -- چیزی تغییر نمی‌کند)"}')

        session = requests.Session()
        stats = {'not_paid': 0, 'issued': 0, 'refunded': 0, 'already_refunded': 0,
                 'charged': 0, 'unknown': 0, 'captured': 0}

        for p in rows:
            try:
                zstatus, amount = self._inquire(session, p)
            except Exception as exc:                    # noqa: BLE001
                stats['unknown'] += 1
                self.stdout.write(self.style.WARNING(
                    f'  پرداخت {p.id}: استعلام ناموفق ({exc}) -- دست‌نخورده ماند'))
                continue
            finally:
                time.sleep(0.12)                        # فشار نیاوردن به درگاه

            if zstatus not in (ZIBAL_PAID_UNVERIFIED, ZIBAL_PAID_VERIFIED):
                stats['not_paid'] += 1
                if opts['execute'] and p.status == 'pending':
                    self._mark_not_paid(p)
                continue

            stats['captured'] += 1
            if not opts['execute']:
                # در حالت آزمایشی هم سقفِ واقعی نشان داده می‌شود، وگرنه گزارش
                # ترسناک‌تر از واقعیت به‌نظر می‌رسد: بیشترِ این پرداخت‌ها از قبل
                # تسویه شده‌اند و چیزی بابتشان پرداخت نخواهد شد.
                owed = self._owed(p)
                stats['would_pay'] = stats.get('would_pay', 0) + min(p.gateway_amount, owed)
                if owed <= 0:
                    stats['already_settled'] = stats.get('already_settled', 0) + 1
                else:
                    self.stdout.write(
                        f'  پرداخت {p.id} (کاربر {p.user_id}): زیبال پول را گرفته '
                        f'{p.gateway_amount:,} ریال -- بدهیِ باقی‌مانده {owed:,} ریال')
                continue

            outcome = self._resolve_captured(p, zstatus, amount, session)
            stats[outcome] = stats.get(outcome, 0) + 1

        self.stdout.write('')
        self.stdout.write('  پرداخت‌نشده (بسته شد)      : %d' % stats['not_paid'])
        self.stdout.write('  پول گرفته‌شده              : %d' % stats['captured'])
        self.stdout.write('     -> بلیط صادر شد        : %d' % stats['issued'])
        self.stdout.write('     -> وجه برگشت           : %d' % stats['refunded'])
        self.stdout.write('     -> از قبل برگشته بود   : %d' % stats['already_refunded'])
        self.stdout.write('     -> کیف پول شارژ شد     : %d' % stats['charged'])
        self.stdout.write('  نامعلوم (خطای استعلام)     : %d' % stats['unknown'])

        if stats['captured'] and not opts['execute']:
            self.stdout.write(self.style.WARNING(
                '  از این پول‌گرفته‌شده‌ها، %d مورد از قبل تسویه شده‌اند'
                % stats.get('already_settled', 0)))
            self.stdout.write(self.style.WARNING(
                '  مجموع پولی که واقعاً پرداخت می‌شود: %s ریال'
                % format(stats.get('would_pay', 0), ',')))
            self.stdout.write('\nبرای اعمال واقعی دوباره با --execute اجرا کنید.')

    # ------------------------------------------------------------------
    def _inquire(self, session, payment):
        r = session.post(INQUIRY_URL,
                         json={'merchant': settings.ZIBAL_MERCHANT_ID,
                               'trackId': int(payment.track_id)},
                         timeout=12)
        d = r.json()
        return d.get('status'), d.get('amount') or payment.gateway_amount

    def _mark_not_paid(self, payment):
        """کاربر واقعاً پرداخت نکرده -- صندلی‌های رزروشده باید آزاد شوند."""
        from payments.views import _release_payment_seats
        with transaction.atomic():
            p = Payment.objects.select_for_update().get(pk=payment.pk)
            if p.status != 'pending':
                return
            p.status = 'failed'
            p.processed_at = timezone.now()
            p.save(update_fields=['status', 'processed_at', 'updated_at'])
            if p.purpose == 'ticket_purchase':
                _release_payment_seats(p)

    def _resolve_captured(self, payment, zstatus, amount, session):
        """پول گرفته شده -- یا بلیط بده، یا پول را برگردان. هیچ حالت سومی نیست."""
        from payments.views import _finalize_ticket_purchase, _release_payment_seats
        from zibal_payment.client import ZibalClient

        # تراکنشِ تأییدنشده را اول قطعی کن، وگرنه زیبال خودش برش می‌گرداند و
        # بازگشت وجهِ ما روی آن، پرداخت دوباره به کاربر می‌شود.
        if zstatus == ZIBAL_PAID_UNVERIFIED:
            try:
                client = ZibalClient(merchant_id=settings.ZIBAL_MERCHANT_ID,
                                     sandbox=settings.ZIBAL_SANDBOX)
                res = client.payment_verify(track_id=payment.track_id)
                if res.get('result') not in (100, 101):
                    self.stdout.write(self.style.WARNING(
                        f'  پرداخت {payment.id}: verify نشد (کد {res.get("result")}) -- دست‌نخورده ماند'))
                    return 'unknown'
            except Exception as exc:                    # noqa: BLE001
                self.stdout.write(self.style.WARNING(
                    f'  پرداخت {payment.id}: خطای verify ({exc}) -- دست‌نخورده ماند'))
                return 'unknown'

        with transaction.atomic():
            p = Payment.objects.select_for_update().get(pk=payment.pk)
            if p.gateway_captured_at is not None:
                return 'already_refunded'               # اجرای موازی، کار انجام شده

            p.gateway_captured_at = timezone.now()
            p.save(update_fields=['gateway_captured_at', 'updated_at'])

            if p.purpose == 'wallet_charge':
                done = self._credit_wallet(p, amount, p.track_id,
                                           f'شارژ کیف پول از طریق زیبال - تراکنش {p.track_id}',
                                           tx_type='deposit')
                p.status = 'success'
                p.processed_at = timezone.now()
                p.save(update_fields=['status', 'processed_at', 'updated_at'])
                self.stdout.write(f'  پرداخت {p.id}: کیف پول کاربر {p.user_id} '
                                  f'{amount:,} ریال شارژ شد')
                return 'charged' if done else 'already_refunded'

            # ===== خرید بلیط =====
            if self._match_is_over(p):
                reason = 'مسابقه برگزار شده'
                issued = False
            else:
                issued, err = _finalize_ticket_purchase(p, amount)
                reason = err

            if issued:
                p.status = 'success'
                p.processed_at = timezone.now()
                p.save(update_fields=['status', 'processed_at', 'updated_at'])
                self.stdout.write(self.style.SUCCESS(
                    f'  پرداخت {p.id}: بلیط کاربر {p.user_id} صادر شد'))
                return 'issued'

            _release_payment_seats(p)

            # ===== هرگز بیشتر از بدهیِ واقعی پرداخت نکن =====
            # نسخه‌ی اول این دستور، مبلغ پرداخت را بی‌قید و شرط برمی‌گرداند.
            # ولی ۲۱٬۷۱۴ پرداختِ شب دربی از قبل دستی جبران شده بودند؛ آن نسخه
            # به صدها نفر دوباره پول می‌داد. محدودکردن به بازه‌ی زمانی کافی
            # نبود (دربی فقط شش روز قبل بود). تنها نگهبانِ درست همین است:
            # سقفِ هر بازگشت، بدهیِ باقی‌مانده‌ی همان کاربر در همان مسابقه.
            payable = min(amount, self._owed(p))
            if payable <= 0:
                p.status = 'failed'
                p.processed_at = timezone.now()
                p.save(update_fields=['status', 'processed_at', 'updated_at'])
                self.stdout.write(
                    f'  پرداخت {p.id}: از قبل تسویه شده -- فقط ثبت شد، پولی پرداخت نشد')
                return 'already_refunded'

            done = self._credit_wallet(
                p, payable, f'refund-{p.track_id}',
                f'بازگشت وجه -- بلیط صادر نشد ({reason}) (تراکنش {p.track_id})',
                tx_type='refund')
            p.status = 'failed'
            p.processed_at = timezone.now()
            p.save(update_fields=['status', 'processed_at', 'updated_at'])
            self.stdout.write(self.style.WARNING(
                f'  پرداخت {p.id}: بلیط صادر نشد ({reason}) -- '
                f'{payable:,} ریال {"به کیف پول کاربر برگشت" if done else "از قبل برگشته بود"}'))
            return 'refunded' if done else 'already_refunded'

    @staticmethod
    def _owed(payment):
        """بدهیِ باقی‌مانده‌ی این کاربر در این مسابقه (تازه محاسبه می‌شود)."""
        from payments.reconciliation import amount_still_owed
        if payment.match_id is None:
            return payment.gateway_amount
        return amount_still_owed(payment.match, payment.user_id)

    # ------------------------------------------------------------------
    @staticmethod
    def _match_is_over(payment):
        if payment.match_id is None:
            return False
        m = payment.match
        return (not m.is_active) or m.is_cancelled or (m.date_time <= timezone.now())

    @staticmethod
    def _credit_wallet(payment, amount, reference_id, description, tx_type):
        """واریز به کیف پول، فقط اگر قبلاً با همین reference انجام نشده باشد.

        این نگهبان است که اجرای دوباره‌ی دستور (یا اجرای هم‌زمانِ دو نسخه) را
        بی‌خطر می‌کند.
        """
        from wallet.models import Wallet, Transaction as WTx
        if WTx.objects.filter(user_id=payment.user_id, reference_id=reference_id).exists():
            return False
        wallet, _ = Wallet.objects.get_or_create(user=payment.user)
        return wallet.add_balance(amount=amount, description=description,
                                  reference_id=reference_id, tx_type=tx_type)
