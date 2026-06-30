from django.core.management.base import BaseCommand
from matches.models import Row


class Command(BaseCommand):
    help = 'ایجاد ردیف‌های (جایگاه‌های) اولیه ورزشگاه'

    def handle(self, *args, **options):
        # حذف ردیف‌های قبلی (اختیاری)
        Row.objects.all().delete()

        sections = []
        # ردیف‌های ۱ تا ۳۳ به جز ۱ و ۶
        for i in range(1, 34):
            if i in [1, 6]:
                continue
            sections.append(Row(
                name=f"ردیف {i}",
                seat_count=1000,
                price=50000,
                order=i,
                is_vip=False
            ))

        # سه کلاس VIP
        for i in range(1, 4):
            sections.append(Row(
                name=f"کلاس {i}",
                seat_count=1000,
                price=150000,
                order=40 + i,
                is_vip=True
            ))

        Row.objects.bulk_create(sections)
        self.stdout.write(self.style.SUCCESS(f'{len(sections)} ردیف ایجاد شد.'))