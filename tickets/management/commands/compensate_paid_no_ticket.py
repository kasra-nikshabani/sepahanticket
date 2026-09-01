"""صدور بلیط جایگزین برای کسانی که پولشان کم شد ولی بلیطی نگرفتند.

پس‌زمینه
--------
شب دربی، در مسیر بازگشت از درگاه سه چیز می‌توانست صدور بلیط را بشکند
*بعد از* اینکه زیبال پرداخت را تأیید کرده و پول از حساب کاربر کم شده بود:
صندلی در فاصله‌ی حضور کاربر در درگاه به کس دیگری فروخته شده بود، سنِ
محاسبه‌شده منفی بود (تاریخ تولد آینده) و قید دیتابیس درج را رد می‌کرد، یا
مبلغ پرداختی با قیمت واقعی بلیط‌ها نمی‌خواند. در هر سه حالت تراکنش
«ناموفق» علامت می‌خورد و کاربر نه بلیط داشت نه پول.

این دستور آن‌ها را جبران می‌کند: برای هر صندلیِ خریداری‌شده یک صندلی
جایگزین در *همان نوع جایگاه* می‌دهد (خریدارِ میهمان در جایگاه میهمان
می‌نشیند، نه میزبان) و بلیط را با همان مشخصات خریدار صادر می‌کند.

ورودی
-----
فایل JSONL خروجیِ اسکنِ استعلام از زیبال؛ هر خط یک رکورد با کلیدهای
payment_id و zibal_status. فقط رکوردهایی که zibal_status آن‌ها ۱ یا ۲
باشد (یعنی پول واقعاً کم شده) در نظر گرفته می‌شوند.

ایمنی
-----
* پیش‌فرض حالت آزمایشی است؛ بدون --execute هیچ چیزی نوشته نمی‌شود.
* idempotent: پرداختی که از قبل بلیط گرفته باشد رد می‌شود، پس اجرای
  دوباره بلیط تکراری نمی‌سازد.
* هر پرداخت در تراکنش خودش انجام می‌شود؛ خطای یک پرداخت بقیه را
  خراب نمی‌کند.
"""
import json
import re
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from matches.models import (
    Match, MatchSeat, Row, Seat, Block, MatchBlockActive, MatchRowActive,
    get_block_zone_map, get_block_price_map, ZONE_CHOICES,
)
from payments.models import Payment
from tickets.models import Ticket

# ===== نقشه‌ی جبران: هر جایگاه از کجا صندلی بگیرد =====
# این چیدمان را باشگاه تعیین کرده، نه کد. سه حالت متفاوت دارد:
#   rows   -> ردیف‌هایی که از قبل وجود دارند و فقط باید فعال شوند
#   block  -> کل بلوک باید فعال شود (صندلی‌های استفاده‌نشده خاموش می‌مانند)
#   newrow -> در بلوکی که *از قبل باز است* یک ردیف تازه ساخته می‌شود
ALLOCATION = {
    'home': {
        'mode': 'rows',
        'block': ('بلوک ۵', 'ground'),
        'note': 'ردیف‌های خاموشِ بلوکی که از قبل باز و مأمور دارد',
    },
    'away': {
        'mode': 'newrow',
        'blocks': [(f'بلوک {n}', 'ground') for n in
                   ('۲۲', '۲۳', '۲۴', '۲۵', '۲۶', '۲۷', '۲۸', '۲۹', '۳۰')],
        'seats_per_row': 30,
        'note': 'ردیف تازه در سکوهای میهمانِ باز',
    },
    'women_away': {
        'mode': 'block',
        'block': ('بلوک ۲۴ (طبقه دوم)', 'second'),
        'note': 'بلوک بانوان میهمانِ طبقه دوم',
    },
    'women': {
        'mode': 'block',
        'block': ('بلوک ۱۰ (طبقه دوم)', 'second'),
        'note': 'بلوک بانوان میزبانِ طبقه دوم',
    },
}


class Command(BaseCommand):
    OCCUPIED = ['paid', 'admin_assigned', 'vip_issued']

    help = 'صدور بلیط جایگزین برای پرداخت‌هایی که پول کم شد ولی بلیط صادر نشد'

    def add_arguments(self, parser):
        parser.add_argument('--match-id', type=int, required=True)
        parser.add_argument('--scan-file', required=True,
                            help='فایل JSONL خروجی استعلام زیبال')
        parser.add_argument('--execute', action='store_true',
                            help='بدون این فلگ فقط گزارش می‌دهد و چیزی نمی‌نویسد')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.dry = not opts['execute']
        match = Match.objects.get(id=opts['match_id'])
        self.match = match
        self.zmap = get_block_zone_map(match)
        self.labels = dict(ZONE_CHOICES)
        self.price_map = get_block_price_map(match)

        payments = self._load_payments(opts['scan_file'], match)
        self.stdout.write(f'پرداخت‌های واجد شرایط: {len(payments):,}')
        if not payments:
            return

        # چه تعداد صندلی از هر جایگاه لازم است
        demand = defaultdict(list)   # zone -> [(payment, seat_pk), ...]
        skipped_no_seats = 0
        for p in payments:
            pks = self._seat_pks(p)
            if not pks:
                skipped_no_seats += 1
                continue
            for pk in pks:
                zone = self._zone_of_seat(pk)
                demand[zone].append((p, pk))

        self.stdout.write('\n=== نیاز به تفکیک جایگاه ===')
        for z, items in sorted(demand.items(), key=lambda kv: -len(kv[1])):
            self.stdout.write(f'  {self.labels.get(z, z):<16} {len(items):,} صندلی')
        if skipped_no_seats:
            self.stdout.write(f'  (پرداخت بدون اطلاعات صندلی: {skipped_no_seats})')

        # تأمین صندلی برای هر جایگاه
        pools = {}
        for zone, items in demand.items():
            pools[zone] = self._provision(zone, len(items))

        self.stdout.write('\n=== تأمین صندلی ===')
        ok = True
        for zone, items in demand.items():
            have = len(pools.get(zone) or [])
            mark = '✅' if have >= len(items) else '❌ کسری'
            self.stdout.write(f'  {self.labels.get(zone, zone):<16} '
                              f'نیاز {len(items):,} / موجود {have:,}  {mark}')
            if have < len(items):
                ok = False
        if not ok:
            self.stdout.write(self.style.ERROR(
                '\nصندلی کافی نیست — هیچ بلیطی صادر نشد.'))
            return

        # ===== مسیر دوم: واریز به کیف پول =====
        per_user = defaultdict(int)
        for p in self.wallet_track:
            per_user[p.user_id] += p.gateway_amount
        self.stdout.write('\n=== واریز به کیف پول (کاربرانی که بلیط دارند) ===')
        self.stdout.write(f'  کاربر: {len(per_user):,}   مبلغ کل: {sum(per_user.values()):,} ریال')

        if self.dry:
            self.stdout.write(self.style.WARNING(
                '\n[حالت آزمایشی] هیچ چیزی نوشته نشد. برای اجرای واقعی --execute بدهید.'))
            return

        self._issue(demand, pools)
        self._credit(per_user)

    # ------------------------------------------------------------------
    def _load_payments(self, path, match):
        """پرداخت‌هایی که زیبال تأیید کرده و هنوز بلیطی ندارند."""
        ids = []
        with open(path) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get('zibal_status') in (1, 2):
                    ids.append(d['payment_id'])

        # ===== دو مسیر جبران =====
        # کاربری که هیچ بلیطی برای این مسابقه ندارد، بلیط جایگزین می‌گیرد.
        # کاربری که بلیط دارد (خرید دومش موفق شده) بلیط دوم نمی‌گیرد --
        # پولِ پرداختِ تحویل‌نشده به کیف پولش واریز می‌شود. این تصمیم باشگاه
        # است، نه پیش‌فرض کد.
        from django.db.models import Count
        have = dict(
            Ticket.objects.filter(match=match, status__in=self.OCCUPIED)
            .values_list('user_id').annotate(n=Count('id'))
        )
        qs = Payment.objects.filter(id__in=ids, match=match).select_related('user')
        ticket_track, wallet_track = [], []
        for p in qs:
            (wallet_track if have.get(p.user_id, 0) else ticket_track).append(p)
        self.wallet_track = wallet_track
        return ticket_track

    def _seat_pks(self, payment):
        return [int(m.group(1)) for k in (payment.buyer_info or {})
                if k.startswith('match_seat_id_') and (m := re.search(r'_(\d+)$', k))]

    def _zone_of_seat(self, match_seat_pk):
        ms = (MatchSeat.objects.filter(id=match_seat_pk)
              .select_related('seat__row').first())
        if not ms:
            return '?'
        return self.zmap.get(ms.seat.row.block_id, '?')

    # ------------------------------------------------------------------
    def _provision(self, zone, needed):
        """صندلی‌های آزادِ قابل‌استفاده برای این جایگاه را برگردان (و در حالت
        اجرا، ردیف/بلوک لازم را فعال یا بساز)."""
        conf = ALLOCATION.get(zone)
        if not conf:
            return []

        if conf['mode'] == 'rows':
            block = self._block(*conf['block'])
            if not self.dry:
                for row in block.rows.all():
                    MatchRowActive.objects.update_or_create(
                        match=self.match, row=row, defaults={'is_active': True})
            return list(MatchSeat.objects.filter(
                match=self.match, seat__row__block=block, is_available=True,
                is_enabled=True, seat__is_available=True)
                .select_related('seat__row').order_by('seat__row__number', 'seat__number'))

        if conf['mode'] == 'block':
            block = self._block(*conf['block'])
            seats = list(MatchSeat.objects.filter(
                match=self.match, seat__row__block=block, is_available=True,
                is_enabled=True, seat__is_available=True)
                .select_related('seat__row').order_by('seat__row__number', 'seat__number'))
            if not self.dry:
                MatchBlockActive.objects.update_or_create(
                    match=self.match, block=block, defaults={'is_active': True})
                # ===== صندلی‌های اضافه را خاموش کن =====
                # فروش مسابقه هنوز باز است؛ روشن کردن این بلوک بدون این کار،
                # ۶۸۵ صندلی را یک‌باره در معرض فروش عمومی می‌گذاشت.
                keep = {s.id for s in seats[:needed]}
                MatchSeat.objects.filter(
                    match=self.match, seat__row__block=block
                ).exclude(id__in=keep).update(is_enabled=False)
                for row in block.rows.all():
                    MatchRowActive.objects.update_or_create(
                        match=self.match, row=row, defaults={'is_active': True})
            return seats

        if conf['mode'] == 'newrow':
            out = []
            per = conf['seats_per_row']
            for name, floor in conf['blocks']:
                block = self._block(name, floor)
                if self.dry:
                    out.extend([None] * per)
                    continue
                nxt = (block.rows.order_by('-number').first().number + 1)
                row = Row.objects.create(block=block, number=nxt, is_active=True)
                MatchRowActive.objects.update_or_create(
                    match=self.match, row=row, defaults={'is_active': True})
                for i in range(1, per + 1):
                    seat = Seat.objects.create(row=row, number=i, is_available=True)
                    out.append(MatchSeat.objects.create(
                        match=self.match, seat=seat, is_available=True, is_enabled=True))
            return out

        return []

    def _block(self, name, floor):
        return Block.objects.get(stadium=self.match.stadium_id, name=name, floor=floor)

    # ------------------------------------------------------------------
    def _issue(self, demand, pools):
        cursors = defaultdict(int)
        issued = failed = 0
        for zone, items in demand.items():
            pool = pools[zone]
            for payment, old_pk in items:
                idx = cursors[zone]
                cursors[zone] += 1
                target = pool[idx]
                try:
                    with transaction.atomic():
                        ms = MatchSeat.objects.select_for_update(of=('self',)).get(id=target.id)
                        if not ms.is_available:
                            failed += 1
                            continue
                        info = payment.buyer_info or {}
                        k = str(old_pk)
                        price = self.price_map.get(ms.seat.row.block_id) or 0
                        Ticket.objects.create(
                            user=payment.user, match=self.match, seat=ms.seat,
                            match_seat=ms, status='paid', price=price,
                            full_name=info.get(f'full_name_{k}', '') or payment.user.get_full_name(),
                            national_code=info.get(f'national_code_{k}', '') or '',
                        )
                        ms.is_available = False
                        ms.save(update_fields=['is_available'])
                        if payment.status != 'success':
                            payment.status = 'success'
                            payment.save(update_fields=['status', 'updated_at'])
                        issued += 1
                except Exception as exc:            # noqa: BLE001
                    failed += 1
                    self.stdout.write(self.style.ERROR(
                        f'  پرداخت {payment.id}: {type(exc).__name__}: {exc}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nصادر شد: {issued:,}   ناموفق: {failed:,}'))

    # ------------------------------------------------------------------
    def _credit(self, per_user):
        """واریز مبلغ پرداخت‌های تحویل‌نشده به کیف پول کاربر.

        idempotent با reference_id: اگر این جبران قبلاً برای همین کاربر و
        همین مسابقه ثبت شده باشد، دوباره واریز نمی‌شود.
        """
        from wallet.models import Wallet, Transaction

        ok = skip = fail = 0
        for uid, amount in per_user.items():
            ref = f'compensate-{self.match.id}-{uid}'
            try:
                if Transaction.objects.filter(reference_id=ref).exists():
                    skip += 1
                    continue
                with transaction.atomic():
                    wallet, _ = Wallet.objects.get_or_create(user_id=uid)
                    wallet.add_balance(
                        amount=amount,
                        description=f'جبران پرداخت بدون صدور بلیط -- مسابقه {self.match.id}',
                        reference_id=ref,
                    )
                ok += 1
            except Exception as exc:            # noqa: BLE001
                fail += 1
                self.stdout.write(self.style.ERROR(f'  کاربر {uid}: {type(exc).__name__}: {exc}'))
        self.stdout.write(self.style.SUCCESS(
            f'واریز شد: {ok:,}   قبلاً واریز شده: {skip:,}   ناموفق: {fail:,}'))
