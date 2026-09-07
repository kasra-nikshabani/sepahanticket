"""استعلام مالکیت شبا برای درخواست‌های برداشتی که هنوز بررسی نشده‌اند.

چرا لازم است
------------
استعلام در لحظه‌ی ثبتِ درخواست انجام می‌شود، ولی اگر آن لحظه سرویس زیبال
در دسترس نباشد (کد ۴۵) یا کیف پول کارمزد خالی باشد (کد ۲۹)، نتیجه
«نامعلوم» می‌ماند و درخواست بدون کنترل خودکار وارد صف می‌شود. آن درخواست
تا ابد بی‌استعلام می‌ماند مگر کسی دوباره بپرسد.

این دستور همان «دوباره پرسیدن» است: هر درخواستِ بازی که هنوز استعلام
نشده را می‌گیرد و نتیجه را رویش می‌نشاند. برای اجرای دوره‌ای هم ساخته
شده، تا وقتی سرویس زیبال برمی‌گردد صفِ عقب‌افتاده خودش تعیین تکلیف شود.
"""
import time

from django.core.management.base import BaseCommand

from wallet.iban_inquiry import is_configured, verify_iban_ownership
from wallet.models import WithdrawalRequest


class Command(BaseCommand):
    help = 'استعلام مالکیت شبا برای درخواست‌های برداشتِ بررسی‌نشده'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=200,
                            help='حداکثر تعداد استعلام در هر اجرا')
        parser.add_argument('--all', action='store_true',
                            help='درخواست‌هایی که قبلاً استعلام شده‌اند را هم دوباره بپرس')
        parser.add_argument('--execute', action='store_true',
                            help='بدون این گزینه فقط گزارش می‌دهد و چیزی را تغییر نمی‌دهد')

    def handle(self, *args, **opts):
        if not is_configured():
            self.stdout.write(self.style.ERROR(
                'ZIBAL_FACILITY_TOKEN تنظیم نشده -- استعلامی انجام نمی‌شود.'))
            return

        qs = (WithdrawalRequest.objects
              .filter(status__in=WithdrawalRequest.OPEN_STATUSES)
              .select_related('user').order_by('created_at'))
        if not opts['all']:
            qs = qs.filter(iban_verified__isnull=True)

        rows = list(qs[:opts['limit']])
        if not rows:
            self.stdout.write(self.style.SUCCESS('درخواست بررسی‌نشده‌ای نمانده.'))
            return

        self.stdout.write(f'{len(rows)} درخواست بررسی می‌شود'
                          f'{"" if opts["execute"] else "  (حالت آزمایشی)"}')

        stats = {'approved': 0, 'correction': 0, 'unknown': 0}
        for req in rows:
            check = verify_iban_ownership(
                req.iban, req.user, req.national_code or req.user.national_code or '')
            time.sleep(0.15)                            # فشار نیاوردن به درگاه

            owner = check.get('ownership')
            name = check.get('name') or ''
            label = ('تأیید' if owner is True else
                     'مغایر' if owner is False else
                     'نامعلوم' if check.get('status') == 'unavailable' else check.get('status'))
            self.stdout.write(
                f'  #{req.id} {req.user.phone_number or req.user.username}: {label}'
                f'{f" — بانک: {name}" if name else ""}  ({check.get("detail", "")})')

            if not opts['execute']:
                continue

            names = [req.account_holder, req.user.get_full_name(), req.user.username]
            req.record_iban_check(check, *names)
            req.refresh_from_db()
            if req.status == 'approved':
                stats['approved'] += 1
            elif req.status == 'needs_correction':
                stats['correction'] += 1
            else:
                stats['unknown'] += 1

        if opts['execute']:
            self.stdout.write('')
            self.stdout.write('  تأیید و در انتظار پرداخت : %d' % stats['approved'])
            self.stdout.write('  برگشت برای اصلاح       : %d' % stats['correction'])
            self.stdout.write('  همچنان نامعلوم         : %d' % stats['unknown'])
        else:
            self.stdout.write(self.style.WARNING(
                '\nبرای اعمال، دوباره با --execute اجرا کنید.'))
