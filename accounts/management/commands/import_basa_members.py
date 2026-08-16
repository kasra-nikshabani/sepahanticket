from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import User

PLACEHOLDER_NATIONAL_CODES = {'0123456789'}
GENDER_MAP = {'مرد': 'male', 'زن': 'female'}


def normalize_national_code(raw):
    code = str(raw).strip()
    if code.isdigit() and len(code) == 9:
        code = code.zfill(10)
    return code


def normalize_phone(raw):
    if raw is None:
        return None
    phone = str(raw).strip()
    if not phone:
        return None
    return phone


class Command(BaseCommand):
    help = 'وارد کردن اعضای باسا از فایل اکسل کارت‌های صادرشده (ستون‌ها بر اساس نام هدر پیدا می‌شوند)'

    def add_arguments(self, parser):
        parser.add_argument('file', type=str, help='مسیر فایل xlsx')

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError:
            raise CommandError('openpyxl نصب نیست: pip install openpyxl')

        wb = openpyxl.load_workbook(options['file'], data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            raise CommandError('فایل خالی است.')

        header = [str(c).strip() if c is not None else '' for c in rows[0]]

        def col(*names):
            for name in names:
                if name in header:
                    return header.index(name)
            raise CommandError(f'ستون‌های {names} توی فایل پیدا نشد. هدر فایل: {header}')

        idx_first_name = col('نام')
        idx_last_name = col('نام خانوادگی')
        idx_gender = col('جنسیت')
        idx_national_code = col('کد ملی')
        idx_phone = col('شماره همراه')

        created = 0
        updated = 0
        skipped_placeholder = 0
        skipped_duplicate_in_file = []
        skipped_phone_conflict = []
        seen_national_codes = set()

        with transaction.atomic():
            for row_num, row in enumerate(rows[1:], start=2):
                raw_national_code = row[idx_national_code]
                if raw_national_code is None:
                    continue

                national_code = normalize_national_code(raw_national_code)
                if national_code in PLACEHOLDER_NATIONAL_CODES:
                    skipped_placeholder += 1
                    continue
                if national_code in seen_national_codes:
                    skipped_duplicate_in_file.append((row_num, national_code))
                    continue
                seen_national_codes.add(national_code)

                first_name = str(row[idx_first_name]).strip() if row[idx_first_name] else ''
                last_name = str(row[idx_last_name]).strip() if row[idx_last_name] else ''
                gender_raw = str(row[idx_gender]).strip() if row[idx_gender] else ''
                gender = GENDER_MAP.get(gender_raw)
                phone = normalize_phone(row[idx_phone])

                existing = User.objects.filter(national_code=national_code).first()
                if existing:
                    if not existing.is_basa_member:
                        existing.is_basa_member = True
                        existing.save(update_fields=['is_basa_member'])
                    updated += 1
                    continue

                if phone and User.objects.filter(phone_number=phone).exists():
                    skipped_phone_conflict.append((row_num, national_code, phone))
                    continue

                user = User(
                    username=phone or f'basa_{national_code}',
                    first_name=first_name,
                    last_name=last_name,
                    national_code=national_code,
                    phone_number=phone,
                    gender=gender,
                    user_type='normal',
                    is_basa_member=True,
                    is_phone_verified=bool(phone),
                    is_active=True,
                )
                user.set_unusable_password()
                user.save()
                created += 1

        self.stdout.write(self.style.SUCCESS(f'ایجاد شد: {created}'))
        self.stdout.write(self.style.SUCCESS(f'به‌روزرسانی شد (قبلاً کاربر داشتند): {updated}'))
        self.stdout.write(self.style.WARNING(f'رد شد (کد ملی جایگزین/نامعتبر: {sorted(PLACEHOLDER_NATIONAL_CODES)}): {skipped_placeholder}'))
        self.stdout.write(self.style.WARNING(f'رد شد (تکراری داخل فایل): {len(skipped_duplicate_in_file)}'))
        if skipped_duplicate_in_file:
            for row_num, code in skipped_duplicate_in_file[:10]:
                self.stdout.write(f'  ردیف {row_num}: کد ملی {code}')
            if len(skipped_duplicate_in_file) > 10:
                self.stdout.write(f'  ... و {len(skipped_duplicate_in_file) - 10} مورد دیگر')
        self.stdout.write(self.style.WARNING(f'رد شد (شماره موبایل قبلاً برای کد ملی دیگری ثبت شده): {len(skipped_phone_conflict)}'))
        if skipped_phone_conflict:
            for row_num, code, phone in skipped_phone_conflict[:10]:
                self.stdout.write(f'  ردیف {row_num}: کد ملی {code} - موبایل {phone}')
            if len(skipped_phone_conflict) > 10:
                self.stdout.write(f'  ... و {len(skipped_phone_conflict) - 10} مورد دیگر')
