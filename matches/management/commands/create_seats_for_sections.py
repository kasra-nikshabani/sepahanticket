from django.core.management.base import BaseCommand
from matches.models import Row, Seat


class Command(BaseCommand):
    help = 'ایجاد صندلی‌ها برای تمام ردیف‌های موجود'

    def handle(self, *args, **options):
        rows = Row.objects.all()
        if not rows.exists():
            self.stdout.write(self.style.WARNING('هیچ ردیفی وجود ندارد. ابتدا create_sections را اجرا کنید.'))
            return

        total_created = 0
        for row in rows:
            # حذف صندلی‌های قبلی (در صورت وجود)
            Seat.objects.filter(row=row).delete()

            # ایجاد صندلی‌ها
            seats = [Seat(row=row, number=i, is_available=True) for i in range(1, row.seat_count + 1)]
            Seat.objects.bulk_create(seats)
            total_created += len(seats)
            self.stdout.write(f'صندلی‌های "{row.name}" ایجاد شدند.')

        self.stdout.write(self.style.SUCCESS(f'{total_created} صندلی با موفقیت ایجاد شد.'))