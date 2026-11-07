"""Create demo content only inside the isolated local preview database."""
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from matches.models import Block, Event, Match, Row, Seat, Stadium


class Command(BaseCommand):
    help = 'Create sample theatre, concert and event sessions in the local preview database.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, 'EVENT_DEMO_MODE', False):
            raise CommandError('Demo data requires football_tickets.settings_preview.')
        venue, _ = Stadium.objects.get_or_create(name='سالن نمونه', defaults={
            'city': 'اصفهان', 'address': 'آدرس نمونه برای پیش‌نمایش', 'capacity': 120})
        for index, name in enumerate(('همکف راست', 'همکف چپ', 'بالکن')):
            block, _ = Block.objects.get_or_create(stadium=venue, name=name,
                defaults={'order': index, 'floor': 'second' if index == 2 else 'ground', 'price': 1500000 + index * 500000})
            for number in range(1, 5):
                row, _ = Row.objects.get_or_create(block=block, number=number)
                for seat in range(1, 11):
                    Seat.objects.get_or_create(row=row, number=seat)
        for index, (category, title) in enumerate((
            ('theater', 'نمایش یک عصر پاییزی'), ('concert', 'کنسرت شب‌های موسیقی'),
            ('event', 'رویداد هنر و گفتگو'),
        )):
            event, _ = Event.objects.get_or_create(title=title, category=category,
                defaults={'description': 'این رویداد صرفاً برای نمایش امکانات سامانه ساخته شده است.',
                          'organizer': 'برگزارکننده نمونه', 'duration_minutes': 90})
            if not event.sessions.exists():
                for day in (index + 2, index + 3):
                    when = (timezone.localtime()+timedelta(days=day)).replace(hour=19, minute=30, second=0, microsecond=0)
                    Match.objects.create(event=event, stadium=venue, date_time=when)
        self.stdout.write(self.style.SUCCESS('Demo events and six sessions are ready.'))
