from django.core.management.base import BaseCommand
from accounts.models import User

class Command(BaseCommand):
    help = 'ایجاد کاربران ویژه (VIP) برای باشگاه'

    def handle(self, *args, **options):
        vip_users = [
            {'username': 'fanclub', 'full_name': 'کانون هواداران باشگاه', 'national_code': '1111111111', 'phone': '09111111111'},
            {'username': 'commerce', 'full_name': 'معاونت بازرگانی باشگاه', 'national_code': '1111111112', 'phone': '09111111112'},
            {'username': 'senior_football', 'full_name': 'فوتبال بزرگسالان', 'national_code': '1111111113', 'phone': '09111111113'},
            {'username': 'folad', 'full_name': 'فولاد مبارکه', 'national_code': '1111111114', 'phone': '09111111114'},
            {'username': 'public_relations', 'full_name': 'روابط عمومی', 'national_code': '1111111115', 'phone': '09111111115'},
            {'username': 'ceo_office', 'full_name': 'دفتر مدیر عامل', 'national_code': '1111111116', 'phone': '09111111116'},
        ]

        for vip in vip_users:
            user, created = User.objects.get_or_create(
                username=vip['username'],
                defaults={
                    'first_name': vip['full_name'],
                    'user_type': 'vip',
                    'national_code': vip['national_code'],
                    'phone_number': vip['phone'],
                    'is_staff': False,
                    'is_superuser': False,
                }
            )
            if created:
                user.set_password('vip_password_123')
                user.save()
                self.stdout.write(self.style.SUCCESS(f'کاربر "{vip["full_name"]}" با موفقیت ایجاد شد.'))
            else:
                # به‌روزرسانی اطلاعات در صورت تغییر
                if user.national_code != vip['national_code'] or user.phone_number != vip['phone']:
                    user.national_code = vip['national_code']
                    user.phone_number = vip['phone']
                    user.save()
                    self.stdout.write(self.style.WARNING(f'اطلاعات کاربر "{vip["full_name"]}" به‌روزرسانی شد.'))
                else:
                    self.stdout.write(self.style.WARNING(f'کاربر "{vip["full_name"]}" از قبل وجود دارد.'))