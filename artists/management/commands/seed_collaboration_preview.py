"""Fictional collaboration examples, restricted to the local preview database."""
from datetime import timedelta
from pathlib import Path
import uuid
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from artists.models import (ArtistProfile, CollaborationOpportunity as Opportunity,
    CollaborationApplication as Application, CollaborationStatusChange, CollaborationMessage)


class Command(BaseCommand):
    help = 'ساخت فراخوان‌ها و درخواست‌های صریحاً ساختگی، فقط برای پیش‌نمایش محلی'

    @transaction.atomic
    def handle(self, *args, **options):
        if not (settings.DEBUG and getattr(settings, 'EVENT_DEMO_MODE', False)
                and Path(str(settings.DATABASES['default']['NAME'])).name == '.event-preview.sqlite3'):
            raise CommandError('این دستور فقط در دیتابیس پیش‌نمایش محلی مجاز است.')
        owner, created = User.objects.get_or_create(username='didavar-demo-project-owner',
            defaults={'first_name': 'مسئول', 'last_name': 'پروژهٔ نمونه'})
        if created:
            owner.set_unusable_password()
            owner.save(update_fields=['password'])
        admin = User.objects.filter(is_staff=True, is_active=True).first()
        examples = [
            ('stage', 'نمونه: دستیار صحنه برای نمایش', 'stage', 'اصفهان', 'negotiable', 2,
                'هماهنگی پشت صحنه، آماده‌سازی وسایل و همراهی گروه در تمرین‌ها.',
                'دقت، مسئولیت‌پذیری و علاقه به کار گروهی؛ امکان همکاری با افراد تازه‌کار.'),
            ('music', 'نمونه: نوازنده برای اجرای موسیقی', 'music', 'تهران', 'range', 1,
                'همکاری با گروه موسیقی در تمرین و اجرای زنده؛ نمونه‌کار اجرایی لازم است.',
                'تجربهٔ اجرای گروهی، توانایی نت‌خوانی و حضور منظم در تمرین‌ها.'),
            ('lighting', 'نمونه: عوامل نور برای پروژهٔ دانشجویی', 'light', 'شیراز', 'unpaid', 2,
                'همراهی یک گروه دانشجویی در طراحی و اجرای نور. این نمونه صرفاً برای پیش‌نمایش است.',
                'آشنایی اولیه با تجهیزات نور و علاقه به تجربهٔ کار روی صحنه.'),
        ]
        demo_artists = list(ArtistProfile.objects.filter(owner__username__in=[
            'didavar-demo-theatre-artist', 'didavar-demo-music-artist']).select_related('owner').order_by('display_name'))
        for index, (slug, title, role, city, pay, positions, description, requirements) in enumerate(examples):
            pk = uuid.uuid5(uuid.NAMESPACE_URL, 'didavar-local-collaboration-preview:' + slug)
            opportunity, created = Opportunity.objects.get_or_create(pk=pk, defaults={
                'owner': owner, 'title': title, 'project_name': 'پروژهٔ ساختگیِ پیش‌نمایش',
                'organizer_name': 'گروه نمونهٔ دیدآور', 'role': role, 'city': city, 'positions': positions,
                'description': 'این فراخوان ساختگی است و به فرصت شغلی واقعی تعلق ندارد. ' + description,
                'requirements': requirements, 'schedule': 'نمونهٔ زمان‌بندی: شنبه و دوشنبه، ساعت ۱۸ تا ۲۰، برای سه هفته.',
                'deadline': timezone.localdate()+timedelta(days=21), 'pay_type': pay,
                'pay_min': 2000000 if pay == 'range' else None, 'pay_max': 4000000 if pay == 'range' else None,
                'pay_details': 'شرایط مالی نمونه برای نمایش فرم؛ ' + ('این همکاری بدون دستمزد است.' if pay == 'unpaid' else 'مبلغ برای کل پروژه و شرایط پرداخت در گفت‌وگو مشخص می‌شود.'),
                'status': 'published', 'reviewed_by': admin, 'reviewed_at': timezone.now(),
                'review_note': 'دادهٔ ساختگی در محیط پیش‌نمایش محلی.'})
            if created and index < len(demo_artists):
                artist = demo_artists[index]
                application = Application.objects.create(opportunity=opportunity, applicant=artist.owner, artist=artist,
                    introduction='این درخواست ساختگی است و فقط برای بررسی فهرست متقاضیان و گفت‌وگو ایجاد شده است.',
                    availability='نمونه: عصرهای شنبه و دوشنبه', status='invited', profile_snapshot={
                        'name': artist.display_name, 'city': artist.city, 'specialty': artist.specialty,
                        'biography': artist.biography, 'skills': 'نمونهٔ مهارت برای پیش‌نمایش', 'experience': 'همکاری در پروژهٔ نمونه'})
                CollaborationStatusChange.objects.create(application=application, actor=artist.owner, status='submitted')
                CollaborationStatusChange.objects.create(application=application, actor=owner, status='invited')
                CollaborationMessage.objects.create(application=application, sender=owner,
                    body='این یک پیام نمونه برای نمایش گفت‌وگوی خصوصی دربارهٔ همکاری است.')
            self.stdout.write(opportunity.get_absolute_url())
