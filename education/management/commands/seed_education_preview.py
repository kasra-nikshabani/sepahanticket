"""Fictional courses and synthetic video, isolated local preview only."""
import subprocess
import uuid
from datetime import time, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from education.models import Course, Lesson, PrivateEducationStorage
from education.video import ffmpeg_binary, process_video


class Command(BaseCommand):
    help = 'ساخت دو آموزش ساختگی و ویدئوی آزمایشی، فقط در پیش‌نمایش محلی'

    def handle(self, *args, **options):
        if not (settings.DEBUG and getattr(settings, 'EVENT_DEMO_MODE', False)
                and Path(str(settings.DATABASES['default']['NAME'])).name == '.event-preview.sqlite3'):
            raise CommandError('این دستور فقط در دیتابیس پیش‌نمایش محلی قابل اجراست.')
        teacher, created = User.objects.get_or_create(username='didavar-demo-education-teacher')
        if created:
            teacher.set_unusable_password()
            teacher.save(update_fields=['password'])
        common = {'owner':teacher, 'teacher_name':'مدرس نمونهٔ دیدآور', 'academy':'آموزشگاه آزمایشی دیدآور',
                  'subject':'acting', 'level':'beginner', 'prerequisites':'بدون پیش‌نیاز؛ علاقه به یادگیری هنر.',
                  'summary':'این آموزش ساختگی است و فقط برای پیش‌نمایش امکانات دیدآور نمایش داده می‌شود.',
                  'description':'این آموزش به مدرس یا آموزشگاه واقعی تعلق ندارد. برای آزمایش معرفی آموزش، خرید از کیف پول، مسیر یادگیری و مدیریت هنرجویان ساخته شده است.',
                  'outcomes':'آشنایی با مسیر یادگیری\nتمرین بیان و حضور روی صحنه\nتمرین فردی و بازخورد در کلاس',
                  'submitted_at':timezone.now(), 'review_note':'آموزش ساختگی محیط پیش‌نمایش؛ بدون فروش یا ثبت‌نام جعلی.'}
        recorded, _ = Course.objects.get_or_create(pk=uuid.uuid5(uuid.NAMESPACE_URL,'didavar-preview-recorded-course'),
            defaults={**common, 'title':'شروع بازیگری | دورهٔ ویدئویی نمونه', 'kind':'recorded', 'price_toman':150000})
        private=Path(PrivateEducationStorage().location)
        private.mkdir(parents=True,exist_ok=True)
        clip=private/'synthetic-preview.mp4'
        if not clip.exists():
            subprocess.run([ffmpeg_binary(),'-y','-nostdin','-loglevel','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24',
                            '-t','12','-c:v','libx264','-threads','2','-pix_fmt','yuv420p',str(clip)],check=True,capture_output=True,timeout=60)
        for index,title in enumerate(['آشنایی با دوره و روش یادگیری','اولین تمرین حضور روی صحنه'],1):
            lesson, created=Lesson.objects.get_or_create(pk=uuid.uuid5(uuid.NAMESPACE_URL,f'didavar-preview-lesson-{index}'),
                defaults={'course':recorded,'title':title,'chapter':'قدم اول','order':index,'is_preview':index==1,
                          'description':'ویدئوی این درس یک الگوی تصویری ساخته‌شده برای آزمایش پخش خصوصی است؛ محتوای آموزشی واقعی نیست.'})
            if created:
                lesson.source.save('preview.mp4',ContentFile(clip.read_bytes()),save=True)
            if lesson.state=='queued' and not process_video(lesson.pk):
                raise CommandError('آماده‌سازی ویدئوی نمونه انجام نشد.')
        if not recorded.published_at:
            recorded.status='published';recorded.published_at=timezone.now();recorded.save()
        today=timezone.localdate()
        classroom,_=Course.objects.get_or_create(pk=uuid.uuid5(uuid.NAMESPACE_URL,'didavar-preview-class'),
            defaults={**common,'title':'کارگاه بیان و بدن | کلاس حضوری نمونه','kind':'class','price_toman':250000,
                'city':'تهران','address':'نشانی آزمایشی؛ این کلاس برای حضور واقعی برگزار نمی‌شود.',
                'schedule':'هشت جلسهٔ نمونه، شنبه‌ها و دوشنبه‌ها از ساعت ۱۸ تا ۲۰.',
                'start_date':today+timedelta(days=30),'start_time':time(18),'end_date':today+timedelta(days=58),'end_time':time(20),
                'registration_deadline':today+timedelta(days=29),'capacity':12,'status':'published','published_at':timezone.now()})
        for course in [recorded,classroom]:
            self.stdout.write(f'{course.title}: {course.get_absolute_url()}')
        self.stdout.write('No enrollments, wallet credits or payment records were generated.')
