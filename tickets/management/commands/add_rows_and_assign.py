"""افزودن ردیف تازه به بلوک‌های موجود و تخصیص صندلی‌هایش به یک کاربر ویژه.

چرا دستور و نه اجرای دستی
-------------------------
این کار سه چیز را هم‌زمان دست می‌زند: ساختار ورزشگاه (Row/Seat)، وضعیت
صندلی‌های یک مسابقه (MatchSeat) و بلیط. اجرای دستیِ همین کار قبلاً یک
اشتباه داد -- صندلی‌های مازاد روشن ماندند و در معرض فروش عمومی قرار
گرفتند. اینجا همه‌ی مراحل یک‌جا، با حالت آزمایشی و بازبینی‌پذیر انجام
می‌شود.

نکته‌ی مهم درباره‌ی شماره‌ی بلوک
--------------------------------
شماره‌ی بلوک‌ها در طبقه پایین و طبقه دوم تکرار شده و جایگاهشان فرق دارد
(مثلاً «بلوک ۲۷» طبقه پایین میهمانِ آقایان است ولی طبقه دومش بانوان
میهمان). به همین دلیل floor در ورودی اجباری است و دستور جایگاهِ نتیجه را
هم چاپ می‌کند تا قبل از اجرا قابل کنترل باشد.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User
from matches.models import (
    Block, Match, MatchRowActive, MatchSeat, Row, Seat,
    ZONE_CHOICES, get_block_price_map, get_block_zone_map,
)
from tickets.models import Ticket


class Command(BaseCommand):
    help = 'افزودن ردیف به بلوک‌ها و تخصیص صندلی‌های آن به یک کاربر ویژه'

    def add_arguments(self, parser):
        parser.add_argument('--match-id', type=int, required=True)
        parser.add_argument('--user', required=True, help='username کاربر ویژه')
        parser.add_argument(
            '--spec', required=True,
            help='JSON: [{"block": "بلوک ۳", "floor": "ground", "rows": [30]}, ...] '
                 'هر عدد در rows یعنی یک ردیف تازه با همان تعداد صندلی',
        )
        parser.add_argument('--execute', action='store_true',
                            help='بدون این فلگ فقط گزارش می‌دهد و چیزی نمی‌نویسد')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        dry = not opts['execute']
        match = Match.objects.get(id=opts['match_id'])
        try:
            user = User.objects.get(username=opts['user'])
        except User.DoesNotExist:
            raise CommandError(f'کاربر {opts["user"]} پیدا نشد')

        spec = json.loads(opts['spec'])
        zmap = get_block_zone_map(match)
        pmap = get_block_price_map(match)
        labels = dict(ZONE_CHOICES)

        # ===== مرحله‌ی ۱: بازبینی، پیش از هر نوشتنی =====
        plan = []
        for item in spec:
            try:
                block = Block.objects.get(
                    stadium=match.stadium_id, name=item['block'], floor=item['floor'])
            except Block.DoesNotExist:
                raise CommandError(f'بلوک «{item["block"]}» در طبقه {item["floor"]} پیدا نشد')
            last = block.rows.order_by('-number').first()
            nxt = (last.number if last else 0) + 1
            for i, count in enumerate(item['rows']):
                plan.append({'block': block, 'row_number': nxt + i, 'seats': count,
                             'zone': zmap.get(block.id, '?'),
                             'price': pmap.get(block.id) or 0})

        self.stdout.write(f'کاربر: {user.username} — '
                          f'{(user.first_name or "") + " " + (user.last_name or "")}'.strip())
        self.stdout.write(f'مسابقه: {match.id}\n')
        self.stdout.write(f'{"بلوک":<24}{"طبقه":<11}{"جایگاه":<16}{"ردیف":>6}{"صندلی":>8}{"قیمت":>13}')
        self.stdout.write('-' * 80)
        total = 0
        per_zone = {}
        for p in plan:
            total += p['seats']
            per_zone[p['zone']] = per_zone.get(p['zone'], 0) + p['seats']
            self.stdout.write(
                f'{p["block"].name:<24}{p["block"].get_floor_display():<11}'
                f'{labels.get(p["zone"], p["zone"]):<16}{p["row_number"]:>6}'
                f'{p["seats"]:>8}{p["price"]:>13,}')
        self.stdout.write(f'\nجمع: {total} صندلی')
        for z, n in sorted(per_zone.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f'   {labels.get(z, z):<16} {n}')

        if dry:
            self.stdout.write(self.style.WARNING(
                '\n[حالت آزمایشی] هیچ چیزی نوشته نشد. برای اجرای واقعی --execute بدهید.'))
            return

        # ===== مرحله‌ی ۲: اجرا =====
        created_seats = issued = 0
        with transaction.atomic():
            for p in plan:
                row = Row.objects.create(block=p['block'], number=p['row_number'], is_active=True)
                # ردیف تازه باید برای همین مسابقه هم صریحاً فعال شود، وگرنه
                # اگر بلوک override ردیف داشته باشد نامرئی می‌ماند.
                MatchRowActive.objects.update_or_create(
                    match=match, row=row, defaults={'is_active': True})

                for num in range(1, p['seats'] + 1):
                    seat = Seat.objects.create(row=row, number=num, is_available=True)
                    ms = MatchSeat.objects.create(
                        match=match, seat=seat, is_available=True, is_enabled=True)
                    created_seats += 1

                    Ticket.objects.create(
                        user=user, match=match, seat=seat, match_seat=ms,
                        status='admin_assigned', is_admin_assigned=True,
                        price=p['price'],
                        full_name=(f'{user.first_name or ""} {user.last_name or ""}'.strip()
                                   or user.username),
                        national_code='',
                    )
                    # صندلی بلافاصله فروخته‌شده علامت می‌خورد تا در فاصله‌ی
                    # ساخت و تخصیص، کسی نتواند بخردش.
                    ms.is_available = False
                    ms.save(update_fields=['is_available'])
                    issued += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nصندلی ساخته‌شده: {created_seats}   بلیط صادرشده: {issued}'))
