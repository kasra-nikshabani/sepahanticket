"""Clearly fictional profiles for the isolated local preview database only."""
from pathlib import Path
from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from matches.models import Event, HomeBanner
from artists.models import ArtistProfile, ArtistCredit


class Command(BaseCommand):
    help = 'ساخت دو پروفایل هنریِ صریحاً نمونه در دیتابیس پیش‌نمایش محلی'

    @transaction.atomic
    def handle(self, *args, **options):
        if not (settings.DEBUG and getattr(settings, 'EVENT_DEMO_MODE', False)
                and Path(str(settings.DATABASES['default']['NAME'])).name == '.event-preview.sqlite3'):
            raise CommandError('این دستور فقط در محیط پیش‌نمایش محلی قابل اجراست.')
        admin = User.objects.filter(is_staff=True, is_active=True).first()
        banners = list(HomeBanner.objects.filter(is_active=True).order_by('order', 'pk')[:2])
        examples = [('didavar-demo-theatre-artist', 'هنرمند نمونهٔ نمایش', 'actor', 'theater',
            'صفحهٔ آزمایشی یک هنرمند تئاتر'),
            ('didavar-demo-music-artist', 'موسیقی‌دان نمونه', 'music', 'concert',
             'صفحهٔ آزمایشی یک هنرمند موسیقی')]
        for index, (username, name, discipline, category, specialty) in enumerate(examples):
            owner, created = User.objects.get_or_create(username=username)
            if created:
                owner.set_unusable_password()
                owner.save(update_fields=['password'])
            artist, created = ArtistProfile.objects.get_or_create(owner=owner, defaults={
                'display_name': name, 'discipline': discipline, 'specialty': specialty, 'city': 'تهران',
                'biography': 'این یک پروفایل ساختگی برای پیش‌نمایش امکانات هنرمندان دیدآور است و به شخص واقعی تعلق ندارد. '
                    'در صفحهٔ هنرمند واقعی، معرفی مسیر هنری، نمونه‌کار و اجراهای تأییدشده نمایش داده می‌شود. '
                    'می‌توانید این صفحهٔ نمونه را دنبال کنید و تنظیم اعلان‌ها را ببینید.',
                'status': 'approved', 'reviewed_by': admin, 'reviewed_at': timezone.now(),
                'review_note': 'پروفایل ساختگیِ محیط پیش‌نمایش.'})
            if created and index < len(banners):
                source = banners[index].image
                with source.open('rb') as image:
                    artist.cover.save(Path(source.name).name, File(image), save=True)
            event = Event.objects.filter(category=category, is_active=True, title__contains='نمونه').first()
            if event:
                ArtistCredit.objects.get_or_create(artist=artist, event=event, role='همکاری نمونه برای پیش‌نمایش',
                    defaults={'status': 'accepted', 'created_by': admin, 'confirmed_at': timezone.now()})
            self.stdout.write(f'{name}: {artist.get_absolute_url()}')
