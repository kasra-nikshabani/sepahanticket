"""Fictional listings and original vector artwork, local preview only."""
import uuid
from datetime import time,timedelta
from pathlib import Path
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand,CommandError
from django.utils import timezone
from accounts.models import User
from studios.models import Studio,StudioPhoto
from studios.services import build_schedule,publication_errors


class Command(BaseCommand):
    help='ساخت دو پلاتوی آزمایشی با تقویم، فقط در دیتابیس پیش‌نمایش محلی'
    def handle(self,*args,**options):
        if not (settings.DEBUG and getattr(settings,'EVENT_DEMO_MODE',False) and Path(str(settings.DATABASES['default']['NAME'])).name=='.event-preview.sqlite3'):
            raise CommandError('این دستور فقط در پیش‌نمایش محلی قابل اجراست.')
        owner,created=User.objects.get_or_create(username='didavar-demo-studio-owner')
        if created: owner.set_unusable_password();owner.save(update_fields=['password'])
        artwork=(settings.BASE_DIR/'static/events/studios/room.svg').read_bytes()
        today=timezone.localdate()
        for index,title,district,price,area,capacity in [(1,'پلاتوی صحنه | نمونهٔ آزمایشی','مرکز شهر',180000,75,12),(2,'فضای تمرین گروه | نمونهٔ آزمایشی','محلهٔ نمونه',250000,110,20)]:
            studio,created=Studio.objects.get_or_create(pk=uuid.uuid5(uuid.NAMESPACE_URL,f'didavar-preview-studio-{index}'),defaults={'owner':owner,'title':title,'city':'تهران','district':district,'address':'نشانی ساختگی برای پیش‌نمایش؛ این پلاتو برای حضور واقعی نیست.','description':'این پلاتو یک نمونهٔ ساختگی برای بررسی امکانات دیدآور است و به فضای واقعی تعلق ندارد. تصاویر، تصویرسازی هستند و عکس واقعی یک پلاتو نیستند.','amenities':'آینه، سیستم صوت، فضای گرم کردن، رختکن، تهویه و نور تمرین — اطلاعات نمونه.','rules':'این نمونه برای آزمایش انتخاب ساعت است؛ رزرو یا پرداخت واقعی برای حضور در این فضا انجام ندهید. در پلاتوهای واقعی، زمان ورود و پایان رزرو باید رعایت شود.','hourly_price':price,'area':area,'capacity':capacity})
            if created:
                studio.cover.save(f'preview-room-{index}.svg',ContentFile(artwork),save=True)
                StudioPhoto.objects.create(studio=studio,image=ContentFile(artwork.replace(b'viewBox="0 0 1000 660"',b'viewBox="240 60 550 380"'),name=f'preview-mirror-{index}.svg'),caption='تصویرسازی نمای آینه و فضای تمرین؛ نمونهٔ آزمایشی')
            build_schedule(studio.pk,today,today+timedelta(days=13),time(10),time(22),list(range(7)),price)
            studio.refresh_from_db()
            if not studio.published_at:
                if errors:=publication_errors(studio): raise CommandError(' '.join(errors))
                studio.status='published';studio.published_at=timezone.now();studio.review_note='نمونهٔ ساختگی محیط پیش‌نمایش، بدون رزرو و فروش جعلی.';studio.save()
            self.stdout.write(f'{studio.title}: {studio.get_absolute_url()}')
        self.stdout.write('No bookings, wallet credits or payment records were generated.')
