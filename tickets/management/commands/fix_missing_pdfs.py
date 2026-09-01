from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from tickets.models import Ticket


class Command(BaseCommand):
    """
    شبکه‌ی ایمنی برای صف PDF: هر بلیطی که بیش از چند دقیقه از ایجادش گذشته
    و هنوز pdf_file ندارد را دوباره enqueue می‌کند. صرف‌نظر از علتِ گیر
    کردن (کرش worker، job ناموفق در RQ، هر باگ دیگری که در آینده دوباره
    باعث خالی ماندن pdf_file شود)، این دستور با یک کرون‌جاب دوره‌ای اجرا
    می‌شود تا هیچ بلیطی برای همیشه بدون PDF نماند.
    """
    help = 'بلیط‌هایی که PDF‌شان تولید نشده را دوباره در صف قرار می‌دهد'

    def add_arguments(self, parser):
        parser.add_argument(
            '--older-than-minutes',
            type=int,
            default=10,
            help='فقط بلیط‌هایی که بیش از این مقدار دقیقه از ایجادشان گذشته را در نظر بگیر (پیش‌فرض ۱۰)',
        )

    # ===== سقف‌ها: این دستور باید شبکه‌ی ایمنی باشد، نه منبع سیل =====
    # نسخه‌ی اول هر ۵ دقیقه *همه‌ی* بلیط‌های بی‌PDF را دوباره enqueue می‌کرد،
    # بدون توجه به اینکه چقدر از آن‌ها همین الان در صف منتظرند. وقتی یک
    # انباشت واقعی پیش آمد (شب دربی، ۸۳۰۰ بلیط)، هر اجرا ۸۳۰۰ کار اضافه
    # می‌کرد در حالی که worker ها در همان ۵ دقیقه فقط ~۱۵۰۰ تا را تمام
    # می‌کردند -- صف به‌جای کوچک شدن، بزرگ‌تر می‌شد و خودِ شبکه‌ی ایمنی به
    # مشکل تبدیل شده بود.
    MAX_QUEUE_DEPTH = 2000   # اگر صف از این عمیق‌تر است، چیزی اضافه نکن
    BATCH = 500              # در هر اجرا حداکثر همین تعداد

    def handle(self, *args, **options):
        from tickets.queue import pdf_queue

        depth = len(pdf_queue)
        if depth > self.MAX_QUEUE_DEPTH:
            self.stdout.write(
                f'صف از قبل {depth:,} کار دارد (بیشتر از سقف {self.MAX_QUEUE_DEPTH:,}) — '
                'چیزی اضافه نمی‌شود تا worker ها عقب‌ماندگی را جبران کنند.'
            )
            return

        cutoff = timezone.now() - timedelta(minutes=options['older_than_minutes'])
        stuck = Ticket.objects.filter(pdf_file='', purchase_date__lt=cutoff)
        count = stuck.count()

        if count == 0:
            self.stdout.write('همه‌ی بلیط‌ها PDF دارند.')
            return

        batch = list(stuck[:self.BATCH])
        self.stdout.write(self.style.WARNING(
            f'{count} بلیط بدون PDF پیدا شد (قدیمی‌تر از {options["older_than_minutes"]} دقیقه) — '
            f'{len(batch)} تای اول دوباره enqueue می‌شود...'
        ))
        for ticket in batch:
            ticket.save(update_fields=['pdf_file'])

        self.stdout.write(self.style.SUCCESS(
            f'{len(batch)} بلیط دوباره در صف قرار گرفت (از {count} بلیطِ بی‌PDF).'
        ))
