import logging

from django.core.management.base import BaseCommand
from django.db.models import Count

from matches.models import Match, MatchSeat
from tickets.models import Ticket

logger = logging.getLogger(__name__)

OCCUPIED_STATUSES = ['paid', 'admin_assigned', 'vip_issued']


class Command(BaseCommand):
    help = (
        'بررسی دوره‌ای سلامت صندلی‌ها: پیدا کردن صندلی‌های دوبار-فروخته‌شده '
        '(بیش از یک بلیط روی یک MatchSeat) و صندلی‌های یتیم (بلیط دارند ولی '
        'is_available هنوز True مونده -- ریسک فروش سوم). این چک بعد از کشف '
        'یک باگ واقعی race condition که باعث چندین صندلی دوبار-فروخته‌شده روی '
        'مسابقات زنده شده بود اضافه شد؛ حتی با رفع اون باگ، این‌جا به‌عنوان '
        'شبکه‌ی ایمنی می‌مونه تا هر تکرار احتمالی (از هر مسیر دیگه‌ای) سریع '
        'کشف بشه، نه اینکه روزها بعد توی یک گزارش پیدا بشه.'
    )

    def handle(self, *args, **options):
        active_matches = Match.objects.filter(is_active=True)

        dupes = (
            Ticket.objects.filter(status__in=OCCUPIED_STATUSES, match_seat__isnull=False, match__in=active_matches)
            .values('match_seat_id', 'match_id')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )
        dupe_count = dupes.count()
        if dupe_count:
            logger.error(f'SEAT INTEGRITY: {dupe_count} صندلی دوبار-فروخته‌شده پیدا شد!')
            for row in dupes:
                logger.error(f"  match {row['match_id']} match_seat {row['match_seat_id']}: {row['n']} بلیط")
        self.stdout.write(
            self.style.ERROR(f'{dupe_count} صندلی دوبار-فروخته‌شده پیدا شد.')
            if dupe_count else self.style.SUCCESS('صندلی دوبار-فروخته‌شده‌ای پیدا نشد.')
        )

        orphan_fixed = 0
        for match in active_matches:
            tickets = (
                Ticket.objects.filter(match=match, status__in=OCCUPIED_STATUSES, match_seat__isnull=False)
                .select_related('match_seat')
            )
            for t in tickets:
                if t.match_seat.is_available:
                    logger.error(
                        f'SEAT INTEGRITY: ticket {t.id} (#{t.ticket_number}) match {match.id} '
                        f'match_seat {t.match_seat_id} has a ticket but is_available=True -- fixing.'
                    )
                    MatchSeat.objects.filter(id=t.match_seat_id).update(is_available=False, reserved_until=None)
                    orphan_fixed += 1

        self.stdout.write(
            self.style.WARNING(f'{orphan_fixed} صندلی یتیم (بلیط داشت ولی آزاد نشون داده می‌شد) خودکار اصلاح شد.')
            if orphan_fixed else self.style.SUCCESS('صندلی یتیمی پیدا نشد.')
        )
