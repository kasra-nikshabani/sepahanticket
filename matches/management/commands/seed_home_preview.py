"""Load the supplied homepage posters into the isolated preview only."""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from matches.models import Event, Match, Stadium


class Command(BaseCommand):
    help = 'Load the four supplied theatre posters into the local homepage preview.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not getattr(settings, 'EVENT_DEMO_MODE', False):
            raise CommandError('This command is restricted to the isolated preview settings.')
        call_command('seed_demo_events', verbosity=0)
        venue = Stadium.objects.get(name='سالن نمونه')
        Event.objects.filter(title='ریشه‌کن', organizer='برگزارکننده نمونه',
                             description__startswith='پیش‌نمایش طراحی صفحه اصلی').update(title='ریشه‌بر')
        for index, (title, filename) in enumerate((
            ('ریشه‌بر', 'rootcutter-poster.jpg'),
            ('شاخ بی‌سر', 'headless-antler-poster.jpg'),
            ('امروز', 'today-poster.jpg'),
            ('کمدی سیاه', 'black-comedy-poster.jpg'),
        )):
            event, _ = Event.objects.get_or_create(title=title, category='theater', defaults={
                'description': 'پیش‌نمایش طراحی صفحه اصلی با پوستر ارسالی؛ زمان، مکان و قیمت اجرا نمونه است.',
                'organizer': 'برگزارکننده نمونه', 'duration_minutes': 90,
            })
            if not event.poster:
                source = Path(settings.BASE_DIR) / 'static/events/uploads' / filename
                with source.open('rb') as stream:
                    event.poster.save(filename, File(stream), save=True)
            if not event.sessions.exists():
                for day in (index + 1, index + 2):
                    when = (timezone.localtime() + timedelta(days=day)).replace(hour=19, minute=30, second=0, microsecond=0)
                    Match.objects.create(event=event, stadium=venue, date_time=when)
        # Replace only the original demo placeholders, never user-created events.
        Event.objects.filter(organizer='برگزارکننده نمونه', title__in=(
            'نمایش یک عصر پاییزی',
        )).update(is_active=False)
        Event.objects.filter(organizer='برگزارکننده نمونه', title__in=(
            'کنسرت شب‌های موسیقی', 'رویداد هنر و گفتگو',
        )).update(is_active=True)
        self.stdout.write(self.style.SUCCESS('Homepage preview posters are ready.'))
