# matches/management/commands/create_stadium_blocks.py
from django.core.management.base import BaseCommand
from matches.models import Block, Row, Seat

# ============================================================
# داده‌های کامل بلوک‌ها (بر اساس نقشه ورزشگاه نقش جهان – طبقه اول)
# استخراج شده از کد جاوااسکریپت ارسال‌شده توسط کاربر
# ============================================================

BLOCKS_DATA = {
    "بلوک ۲": {
        1: list(range(1, 31)),
        2: list(range(1, 31)),
        3: list(range(1, 31)),
        4: list(range(1, 31)),
        5: list(range(1, 30)),
        6: list(range(1, 30)),
        7: list(range(1, 30)),
        8: list(range(1, 30)),
        9: list(range(1, 30)),
        10: list(range(1, 30)),
        11: list(range(1, 30)),
        12: list(range(1, 30)),
        13: list(range(1, 30)),
        14: list(range(1, 30)),
        15: list(range(1, 30)),
        16: list(range(1, 29)),
        17: list(range(1, 29)),
        18: list(range(1, 29)),
        19: list(range(1, 29)),
        20: list(range(1, 29)),
        21: list(range(1, 29)),
        22: list(range(1, 29)),
        23: list(range(1, 29)),
        24: list(range(1, 29)),
        25: list(range(1, 29)),
        26: list(range(2, 29)),
        27: list(range(2, 29)),
        28: list(range(2, 29)),
        29: list(range(2, 28)),
        30: list(range(2, 28)),
        31: list(range(2, 28)),
        32: list(range(2, 28)),
        33: list(range(2, 28)),
    },
    "بلوک ۳": {
        **{i: list(range(2, 30)) for i in range(1, 26)},
        26: list(range(3, 30)),
        27: list(range(3, 30)),
        28: list(range(3, 29)),
        29: list(range(3, 29)),
        30: list(range(3, 29)),
        31: list(range(3, 29)),
        32: list(range(3, 29)),
        33: list(range(3, 29)),
    },
    "بلوک ۴": {
        **{i: list(range(2, 30)) for i in range(1, 22)},
        22: list(range(16, 30)),
        23: list(range(16, 30)),
        24: list(range(16, 30)),
        25: list(range(16, 29)),
        26: list(range(16, 29)),
        27: list(range(16, 29)),
        28: list(range(16, 29)),
        29: list(range(16, 29)),
        30: list(range(16, 29)),
        31: list(range(16, 28)),
        32: list(range(16, 28)),
        33: list(range(16, 28)),
    },
    "بلوک ۵": {
        **{i: list(range(1, 31)) for i in range(1, 12)},
        12: list(range(2, 31)),
        13: list(range(2, 31)),
        14: list(range(2, 31)),
        15: list(range(2, 31)),
        16: list(range(2, 31)),
        17: list(range(3, 31)),
        18: list(range(3, 31)),
        19: list(range(3, 31)),
        20: list(range(3, 31)),
        21: list(range(3, 31)),
        22: list(range(3, 17)),
        23: list(range(4, 17)),
        24: list(range(4, 17)),
        25: list(range(4, 17)),
        26: list(range(4, 17)),
        27: list(range(4, 17)),
        28: list(range(5, 17)),
        29: list(range(5, 17)),
        30: list(range(5, 17)),
        31: list(range(5, 17)),
        32: list(range(5, 17)),
        33: list(range(6, 17)),
    },
    "بلوک ۷": {
        **{i: list(range(1, 31)) for i in range(1, 12)},
        12: [],  # به‌طور جداگانه در SPLIT_ROWS مدیریت می‌شود
        13: [],
        14: [],
        15: [],
        16: list(range(1, 31)),
        17: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(18, 22)},
        22: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(23, 28)},
        28: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۸": {
        **{i: list(range(1, 31)) for i in range(1, 18)},
        **{i: list(range(2, 30)) for i in range(18, 23)},
        **{i: list(range(3, 29)) for i in range(23, 27)},
        27: list(range(16, 29)),
        28: list(range(16, 29)),
        **{i: list(range(16, 28)) for i in range(29, 34)},
    },
    "بلوک ۹": {
        **{i: list(range(1, 31)) for i in range(1, 16)},
        16: list(range(1, 30)),
        **{i: list(range(2, 30)) for i in range(17, 23)},
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 27)},
        27: list(range(3, 16)),
        28: list(range(3, 16)),
        **{i: list(range(4, 16)) for i in range(29, 34)},
    },
    "بلوک ۱۰": {
        **{i: list(range(1, 31)) for i in range(1, 12)},
        12: [],
        13: [],
        14: [],
        15: [],
        16: list(range(1, 31)),
        17: list(range(1, 30)),
        **{i: list(range(2, 30)) for i in range(18, 22)},
        22: list(range(2, 29)),
        **{i: list(range(3, 29)) for i in range(23, 28)},
        28: list(range(3, 28)),
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۱۱": {
        **{i: list(range(1, 31)) for i in range(1, 12)},
        12: [],
        13: [],
        14: [],
        15: [],
        16: list(range(1, 31)),
        17: list(range(2, 31)),
        18: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(19, 22)},
        22: list(range(3, 30)),
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 28)},
        28: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۱۲": {
        **{i: list(range(1, 31)) for i in range(1, 17)},
        17: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(18, 22)},
        22: list(range(3, 30)),
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 28)},
        28: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۱۳": {
        **{i: list(range(1, 31)) for i in range(1, 16)},
        16: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(17, 21)},
        21: list(range(3, 30)),
        22: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(23, 27)},
        27: list(range(4, 29)),
        28: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(29, 33)},
        33: list(range(5, 28)),
    },
    "بلوک ۱۴": {
        **{i: list(range(1, 31)) for i in range(1, 13)},
        13: list(range(1, 30)),
        **{i: list(range(2, 30)) for i in range(14, 28)},
        28: list(range(2, 29)),
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۱۵": {
        **{i: list(range(1, 31)) for i in range(1, 14)},
        14: list(range(2, 31)),
        15: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(16, 26)},
        26: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(27, 34)},
    },
    "بلوک ۱۶": {
        **{i: list(range(1, 31)) for i in range(1, 14)},
        14: list(range(1, 30)),
        15: list(range(1, 30)),
        **{i: list(range(2, 30)) for i in range(16, 26)},
        **{i: list(range(2, 29)) for i in range(26, 29)},
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۱۷": {
        **{i: list(range(1, 31)) for i in range(1, 14)},
        14: list(range(1, 30)),
        15: list(range(1, 30)),
        **{i: list(range(2, 30)) for i in range(16, 26)},
        **{i: list(range(2, 29)) for i in range(26, 29)},
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۱۸": {
        **{i: list(range(1, 31)) for i in range(1, 14)},
        14: list(range(2, 31)),
        15: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(16, 26)},
        **{i: list(range(3, 30)) for i in range(26, 29)},
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۱۹": {
        **{i: list(range(1, 31)) for i in range(1, 13)},
        **{i: list(range(2, 31)) for i in range(13, 24)},
        24: list(range(2, 30)),
        25: list(range(3, 30)),
        26: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(27, 34)},
    },
    "بلوک ۲۰": {
        **{i: list(range(1, 31)) for i in range(1, 13)},
        **{i: list(range(2, 31)) for i in range(13, 16)},
        **{i: list(range(2, 30)) for i in range(16, 25)},
        **{i: list(range(3, 30)) for i in range(25, 29)},
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۲۱": {
        **{i: list(range(1, 31)) for i in range(1, 13)},
        **{i: list(range(2, 31)) for i in range(13, 16)},
        **{i: list(range(2, 30)) for i in range(16, 25)},
        **{i: list(range(3, 30)) for i in range(25, 29)},
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۲۲": {
        **{i: list(range(1, 31)) for i in range(1, 13)},
        **{i: list(range(2, 31)) for i in range(13, 16)},
        **{i: list(range(2, 30)) for i in range(16, 25)},
        **{i: list(range(3, 30)) for i in range(25, 29)},
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۲۳": {
        **{i: list(range(1, 31)) for i in range(1, 14)},
        14: list(range(2, 31)),
        15: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(16, 26)},
        **{i: list(range(3, 30)) for i in range(26, 29)},
        **{i: list(range(3, 29)) for i in range(29, 34)},
    },
    "بلوک ۲۴": {
        **{i: list(range(1, 31)) for i in range(1, 16)},
        16: list(range(1, 30)),
        **{i: list(range(2, 30)) for i in range(17, 24)},
        **{i: list(range(3, 29)) for i in range(24, 30)},
        **{i: list(range(4, 28)) for i in range(30, 34)},
    },
    "بلوک ۲۵": {
        **{i: list(range(1, 31)) for i in range(1, 17)},
        17: list(range(2, 31)),
        18: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(19, 23)},
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 28)},
        28: list(range(4, 29)),
        29: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(30, 34)},
    },
    "بلوک ۲۶": {
        **{i: list(range(1, 31)) for i in range(1, 17)},
        17: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(18, 24)},
        **{i: list(range(3, 29)) for i in range(24, 28)},
        28: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۲۷": {
        **{i: list(range(1, 31)) for i in range(1, 16)},
        16: list(range(2, 31)),
        17: list(range(2, 31)),
        **{i: list(range(2, 30)) for i in range(18, 21)},
        **{i: list(range(3, 30)) for i in range(21, 24)},
        **{i: list(range(3, 29)) for i in range(24, 26)},
        **{i: list(range(4, 29)) for i in range(26, 29)},
        **{i: list(range(4, 28)) for i in range(29, 32)},
        32: list(range(5, 28)),
        33: list(range(5, 28)),
    },
    "بلوک ۲۸": {
        **{i: list(range(1, 31)) for i in range(1, 15)},
        **{i: list(range(1, 30)) for i in range(15, 19)},
        **{i: list(range(1, 29)) for i in range(19, 22)},
        22: list(range(2, 29)),
        23: list(range(2, 29)),
        **{i: list(range(2, 28)) for i in range(24, 27)},
        **{i: list(range(16, 28)) for i in range(27, 30)},
        **{i: list(range(16, 27)) for i in range(30, 34)},
    },
    "بلوک ۲۹": {
        **{i: list(range(2, 30)) for i in range(1, 23)},
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 27)},
        **{i: list(range(4, 15)) for i in range(27, 34)},
    },
    "بلوک ۳۰": {
        **{i: list(range(2, 30)) for i in range(1, 22)},
        22: list(range(3, 30)),
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 29)},
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۳۱": {
        **{i: list(range(2, 30)) for i in range(1, 23)},
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 28)},
        28: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۳۲": {
        **{i: list(range(2, 30)) for i in range(1, 22)},
        22: list(range(3, 30)),
        23: list(range(3, 30)),
        **{i: list(range(3, 29)) for i in range(24, 27)},
        27: list(range(4, 29)),
        28: list(range(4, 29)),
        **{i: list(range(4, 28)) for i in range(29, 34)},
    },
    "بلوک ۳۳": {
        **{i: list(range(1, 29)) for i in range(1, 12)},
        **{i: list(range(2, 29)) for i in range(12, 22)},
        22: list(range(2, 28)),
        **{i: list(range(3, 28)) for i in range(23, 28)},
        28: list(range(3, 27)),
        29: list(range(3, 27)),
        **{i: list(range(3, 26)) for i in range(30, 34)},
    },
    "بلوک کلاس ۱ (۱)": {
        **{i: list(range(1, 29)) for i in range(1, 16)},
        **{i: list(range(2, 29)) for i in range(16, 22)},
        22: list(range(7, 29)),
        23: list(range(7, 29)),
        **{i: list(range(8, 29)) for i in range(24, 28)},
        28: list(range(8, 28)),
        **{i: list(range(3, 28)) for i in range(29, 34)},
    },
    "بلوک کلاس ۱ (۲)": {
        **{i: list(range(1, 29)) for i in range(1, 25)},
        **{i: list(range(2, 29)) for i in range(25, 29)},
        **{i: list(range(2, 28)) for i in range(29, 34)},
    },
    "بلوک کلاس ۱ (۳)": {
        **{i: list(range(1, 29)) for i in range(1, 13)},
        **{i: list(range(2, 29)) for i in range(13, 19)},
        **{i: list(range(2, 28)) for i in range(19, 25)},
        **{i: list(range(3, 28)) for i in range(25, 34)},
    },
    "بلوک VIP1": {
        **{i: list(range(1, 29)) for i in range(1, 16)},
        **{i: list(range(2, 28)) for i in range(16, 28)},
        **{i: list(range(3, 27)) for i in range(28, 34)},
    },
    "بلوک VIP2": {
        **{i: list(range(1, 29)) for i in range(1, 27)},
        **{i: list(range(2, 15)) for i in range(27, 34)},
    },
    "بلوک VIP3": {
        **{i: list(range(1, 29)) for i in range(1, 24)},
        24: list(range(2, 29)),
        25: list(range(2, 29)),
        **{i: list(range(16, 29)) for i in range(26, 29)},
        **{i: list(range(16, 28)) for i in range(29, 34)},
    },
}

# ============================================================
# ردیف‌های خاص با دو بخش مجزا (بلوک‌های ۷، ۱۰، ۱۱)
# ============================================================
SPLIT_ROWS = {
    "بلوک ۷": {
        12: list(range(1, 7)) + list(range(25, 31)),
        13: list(range(1, 7)) + list(range(25, 31)),
        14: list(range(1, 7)) + list(range(25, 31)),
        15: list(range(1, 7)) + list(range(25, 31)),
    },
    "بلوک ۱۰": {
        12: list(range(1, 7)) + list(range(25, 31)),
        13: list(range(1, 7)) + list(range(25, 31)),
        14: list(range(1, 7)) + list(range(25, 31)),
        15: list(range(1, 7)) + list(range(25, 31)),
    },
    "بلوک ۱۱": {
        12: list(range(1, 7)) + list(range(25, 31)),
        13: list(range(1, 7)) + list(range(25, 31)),
        14: list(range(1, 7)) + list(range(25, 31)),
        15: list(range(1, 7)) + list(range(25, 31)),
    },
}


class Command(BaseCommand):
    help = 'ایجاد بلوک‌ها، ردیف‌ها و صندلی‌های ورزشگاه بر اساس داده‌های واقعی'

    def handle(self, *args, **options):
        # پاک کردن داده‌های قبلی
        Block.objects.all().delete()
        self.stdout.write("🗑️ داده‌های قبلی حذف شدند.")

        for block_name, rows_data in BLOCKS_DATA.items():
            # استخراج شماره ترتیب از نام بلوک (برای مرتب‌سازی)
            order = 0
            if "VIP" in block_name:
                order = 100  # VIPها در انتها
            elif "کلاس" in block_name:
                order = 90
            else:
                # استخراج عدد از نام (مثلاً "بلوک ۲" -> 2)
                try:
                    order = int(block_name.split()[-1])
                except:
                    order = 0

            block, created = Block.objects.get_or_create(
                name=block_name,
                defaults={
                    'order': order,
                    'is_vip': "VIP" in block_name,
                    'is_class1': "کلاس" in block_name,
                }
            )
            if created:
                self.stdout.write(f"📦 ایجاد بلوک: {block_name}")
            else:
                self.stdout.write(f"♻️ بلوک {block_name} از قبل وجود داشت، به‌روزرسانی می‌شود.")

            for row_num, seat_numbers in rows_data.items():
                # اگر ردیف در SPLIT_ROWS تعریف شده، از آن استفاده کن
                if block_name in SPLIT_ROWS and row_num in SPLIT_ROWS[block_name]:
                    final_seats = SPLIT_ROWS[block_name][row_num]
                else:
                    final_seats = seat_numbers if isinstance(seat_numbers, list) else list(range(seat_numbers[0], seat_numbers[1]+1))

                row, _ = Row.objects.get_or_create(block=block, number=row_num)
                # حذف صندلی‌های قدیمی و ایجاد جدید
                Seat.objects.filter(row=row).delete()
                if final_seats:
                    seats = [Seat(row=row, number=s) for s in final_seats]
                    Seat.objects.bulk_create(seats)
                    self.stdout.write(f"   ✅ ردیف {row_num}: {len(seats)} صندلی")
                else:
                    self.stdout.write(f"   ⚠️ ردیف {row_num} فاقد صندلی است (پرش شد)")

        self.stdout.write(self.style.SUCCESS("✅ همه بلوک‌ها و صندلی‌ها با موفقیت ایجاد شدند."))