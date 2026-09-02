"""جبران کسریِ بلیط: کسی که پول داده ولی به‌اندازه‌ی پرداختش بلیط نگرفته.

تفاوت با compensate_paid_no_ticket
----------------------------------
آن دستور فقط پرداخت‌هایی را می‌دید که وضعیت محلی‌شان pending/failed بود.
ولی بعضی کاربران پرداخت *موفق* داشتند که بلیط کاملش صادر نشده بود -- مثلاً
پول ۱۲ صندلی را داده و ۷ بلیط گرفته. آن‌ها در هیچ‌کدام از دسته‌های قبلی
نبودند و جا ماندند.

اینجا تراز واقعی هر کاربر حساب می‌شود:
    کسری = صندلی‌هایی که پولش داده شده − بلیط‌هایی که واقعاً دارد
    طلب  = کسری × قیمت − جبرانی که قبلاً گرفته (واریز کیف پول)
و فقط به‌اندازه‌ی طلبِ باقی‌مانده بلیط صادر می‌شود.

تأمین صندلی
-----------
اول از صندلی‌هایی استفاده می‌کند که از قبل ساخته شده‌اند ولی خاموشند
(بازمانده‌ی جبران‌های قبلی)، و تنها برای کسری، ردیف تازه می‌سازد. این هم
سریع‌تر است و هم سکوی جدیدی باز نمی‌کند.
"""
import json
import re
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Sum

from accounts.models import User
from matches.models import (
    Block, Match, MatchRowActive, MatchSeat, Row, Seat,
    ZONE_CHOICES, get_block_price_map, get_block_zone_map,
)
from payments.models import Payment
from tickets.models import Ticket
from wallet.models import Transaction as WalletTx

# ===== چیدمانی که باشگاه تعیین کرده =====
#   reuse -> بلوک‌هایی که صندلی ساخته‌شده‌ی خاموش دارند (اول از این‌ها)
#   new   -> اگر کم آمد، در این بلوک ردیف تازه با این تعداد صندلی ساخته شود
ALLOCATION = {
    'home':       {'reuse': [('بلوک ۵', 'ground')],
                   'new': ('بلوک ۵', 'ground', 30)},
    'away':       {'reuse': [('بلوک ۲۸', 'ground'), ('بلوک ۲۹', 'ground'),
                             ('بلوک ۳۰', 'ground')],
                   'new': ('بلوک ۳۰', 'ground', 30)},
    'women':      {'reuse': [('بلوک ۱۰ (طبقه دوم)', 'second')],
                   'new': ('بلوک ۹ (طبقه دوم)', 'second', 30)},
    'women_away': {'reuse': [('بلوک ۲۴ (طبقه دوم)', 'second')],
                   'new': ('بلوک ۲۹ (طبقه دوم)', 'second', 30)},
}
PRICE = 3000000


class Command(BaseCommand):
    OCCUPIED = ['paid', 'admin_assigned', 'vip_issued']
    help = 'صدور بلیط برای کسانی که پول داده‌اند ولی بلیط کاملشان صادر نشده'

    def add_arguments(self, parser):
        parser.add_argument('--match-id', type=int, required=True)
        parser.add_argument('--scan-file', required=True)
        parser.add_argument('--execute', action='store_true')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.dry = not opts['execute']
        self.match = Match.objects.get(id=opts['match_id'])
        self.zmap = get_block_zone_map(self.match)
        self.pmap = get_block_price_map(self.match)
        self.labels = dict(ZONE_CHOICES)

        demand = self._shortfall(opts['scan_file'])
        total = sum(len(v) for v in demand.values())
        users = {uid for items in demand.values() for uid, _ in items}
        self.stdout.write(f'کاربران طلبکار: {len(users):,}   بلیط موردنیاز: {total:,}')
        self.stdout.write(f'مبلغ: {total * PRICE:,} ریال\n')
        for z, items in sorted(demand.items(), key=lambda kv: -len(kv[1])):
            self.stdout.write(f'  {self.labels.get(z, z):<16} {len(items):,}')

        self.stdout.write('\n=== تأمین صندلی ===')
        pools, ok = {}, True
        for z, items in demand.items():
            pools[z] = self._provision(z, len(items))
            have = len(pools[z])
            self.stdout.write(f'  {self.labels.get(z, z):<16} نیاز {len(items):,} / '
                              f'آماده {have:,}  {"✅" if have >= len(items) else "❌ کسری"}')
            if have < len(items):
                ok = False
        if not ok:
            self.stdout.write(self.style.ERROR('\nصندلی کافی نیست — هیچ بلیطی صادر نشد.'))
            return
        if self.dry:
            self.stdout.write(self.style.WARNING(
                '\n[حالت آزمایشی] هیچ چیزی نوشته نشد. برای اجرا --execute بدهید.'))
            return
        self._issue(demand, pools)

    # ------------------------------------------------------------------
    def _shortfall(self, scan_file):
        """{zone: [(user_id, seat_pk_نمونه), ...]} — بلیط‌هایی که باید صادر شود."""
        zibal_paid = set()
        with open(scan_file) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get('zibal_status') in (1, 2):
                    zibal_paid.add(d['payment_id'])

        seats = defaultdict(list)
        for p in Payment.objects.filter(match=self.match, purpose='ticket_purchase'):
            if not (p.status == 'success' or p.id in zibal_paid):
                continue
            for k in (p.buyer_info or {}):
                if k.startswith('match_seat_id_') and (m := re.search(r'_(\d+)$', k)):
                    seats[p.user_id].append(int(m.group(1)))

        tickets = dict(Ticket.objects.filter(match=self.match, status__in=self.OCCUPIED)
                       .values_list('user_id').annotate(n=Count('id')))
        credited = dict(WalletTx.objects
                        .filter(reference_id__startswith=f'compensate-{self.match.id}-')
                        .values_list('user_id').annotate(s=Sum('amount')))

        seat_zone = {}
        allpk = {x for v in seats.values() for x in v}
        for ms in MatchSeat.objects.filter(id__in=allpk).select_related('seat__row'):
            seat_zone[ms.id] = self.zmap.get(ms.seat.row.block_id, '?')

        demand = defaultdict(list)
        for uid, pks in seats.items():
            gap = len(pks) - tickets.get(uid, 0)
            if gap <= 0:
                continue
            owed = gap * PRICE - credited.get(uid, 0)
            need = min(gap, owed // PRICE)
            if need <= 0:
                continue
            # جایگاهِ همان صندلی‌هایی که پولش داده شده
            for pk in pks[-need:]:
                demand[seat_zone.get(pk, '?')].append((uid, pk))
        return demand

    # ------------------------------------------------------------------
    def _block(self, name, floor):
        return Block.objects.get(stadium=self.match.stadium_id, name=name, floor=floor)

    def _provision(self, zone, needed):
        conf = ALLOCATION.get(zone)
        if not conf:
            return []
        pool = []

        # ۱) اول صندلی‌های ساخته‌شده‌ی خاموش را برگردان
        for name, floor in conf['reuse']:
            if len(pool) >= needed:
                break
            block = self._block(name, floor)
            found = list(MatchSeat.objects.filter(
                match=self.match, seat__row__block=block,
                is_available=True, seat__is_available=True)
                .select_related('seat__row')
                .order_by('seat__row__number', 'seat__number')[:needed - len(pool)])
            if not self.dry and found:
                MatchSeat.objects.filter(id__in=[s.id for s in found]).update(is_enabled=True)
                for row_id in {s.seat.row_id for s in found}:
                    MatchRowActive.objects.update_or_create(
                        match=self.match, row_id=row_id, defaults={'is_active': True})
            pool.extend(found)

        # ۲) برای کسری، ردیف تازه بساز
        if len(pool) < needed and conf.get('new'):
            name, floor, per = conf['new']
            block = self._block(name, floor)
            while len(pool) < needed:
                if self.dry:
                    pool.extend([None] * min(per, needed - len(pool)))
                    continue
                last = block.rows.order_by('-number').first()
                row = Row.objects.create(block=block, number=(last.number if last else 0) + 1,
                                         is_active=True)
                MatchRowActive.objects.update_or_create(
                    match=self.match, row=row, defaults={'is_active': True})
                for i in range(1, per + 1):
                    seat = Seat.objects.create(row=row, number=i, is_available=True)
                    pool.append(MatchSeat.objects.create(
                        match=self.match, seat=seat, is_available=True, is_enabled=True))
        return pool

    # ------------------------------------------------------------------
    def _issue(self, demand, pools):
        issued = failed = 0
        for zone, items in demand.items():
            pool = pools[zone]
            for idx, (uid, _old_pk) in enumerate(items):
                target = pool[idx]
                try:
                    with transaction.atomic():
                        ms = MatchSeat.objects.select_for_update(of=('self',)).get(id=target.id)
                        if not ms.is_available:
                            failed += 1
                            continue
                        user = User.objects.get(id=uid)
                        Ticket.objects.create(
                            user=user, match=self.match, seat=ms.seat, match_seat=ms,
                            status='paid',
                            price=self.pmap.get(ms.seat.row.block_id) or PRICE,
                            full_name=(f'{user.first_name or ""} {user.last_name or ""}'.strip()
                                       or user.username),
                            national_code=user.national_code or '',
                        )
                        ms.is_available = False
                        ms.save(update_fields=['is_available'])
                        issued += 1
                except Exception as exc:            # noqa: BLE001
                    failed += 1
                    self.stdout.write(self.style.ERROR(f'  کاربر {uid}: {type(exc).__name__}: {exc}'))

        # صندلی‌های استفاده‌نشده دوباره خاموش تا به فروش عمومی نروند
        leftovers = [s.id for z, pool in pools.items()
                     for s in pool[len(demand[z]):] if s is not None]
        if leftovers:
            MatchSeat.objects.filter(id__in=leftovers).update(is_enabled=False)
        self.stdout.write(self.style.SUCCESS(
            f'\nصادر شد: {issued:,}   ناموفق: {failed:,}   '
            f'صندلی مازادِ خاموش‌شده: {len(leftovers):,}'))
