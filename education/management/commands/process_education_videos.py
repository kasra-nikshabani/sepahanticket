import time
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from education.models import Lesson
from education.video import process_video


class Command(BaseCommand):
    help = 'Package private education video uploads; --watch runs the durable database queue.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, *args, **options):
        try:
            while True:
                close_old_connections()
                Lesson.objects.filter(state='processing', processing_started_at__lt=timezone.now()-timedelta(hours=3)).update(state='queued')
                ids = list(Lesson.objects.filter(state='queued').order_by('created_at').values_list('pk', flat=True)[:10])
                for pk in ids:
                    self.stdout.write(f'{pk}: ' + ('ready' if process_video(pk) else 'skipped/failed'))
                if not options['watch']:
                    break
                if not ids:
                    time.sleep(3)
        except KeyboardInterrupt:
            self.stdout.write('Video worker stopped.')
