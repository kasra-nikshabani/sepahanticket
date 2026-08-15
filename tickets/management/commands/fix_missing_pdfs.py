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

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options['older_than_minutes'])
        stuck = Ticket.objects.filter(pdf_file='', created_at__lt=cutoff)
        count = stuck.count()

        if count == 0:
            self.stdout.write('همه‌ی بلیط‌ها PDF دارند.')
            return

        self.stdout.write(self.style.WARNING(
            f'{count} بلیط بدون PDF پیدا شد (قدیمی‌تر از {options["older_than_minutes"]} دقیقه) — دوباره enqueue می‌شود...'
        ))
        for ticket in stuck:
            ticket.save(update_fields=['pdf_file'])
            self.stdout.write(f'  - بلیط {ticket.id} ({ticket.ticket_number}) دوباره enqueue شد')

        self.stdout.write(self.style.SUCCESS(f'{count} بلیط دوباره در صف قرار گرفت.'))
