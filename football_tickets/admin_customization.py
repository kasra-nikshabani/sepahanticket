# football_tickets/admin_customization.py
"""
سفارشی‌سازی سایدبار پنل ادمین جنگو.

به‌جای اینکه «بلیط‌ها» داخل گروه TICKETS (کنار تخصیص ظرفیت، تراکنش‌ها، سفارش‌ها،
کدهای تخفیف) و «کاربران» داخل گروه ACCOUNTS گم بشن، هرکدوم به‌صورت یک گروه
مستقل و پین‌شده در بالای سایدبار نشون داده می‌شن؛ بقیه‌ی مدل‌های همون اپ‌ها
سرجای خودشون (توی گروه اصلی) می‌مونن.

get_app_list همون تابعیه که هم سایدبار و هم صفحه‌ی اصلی پنل ادمین (index)
رو می‌سازه، پس این تغییر روی هر دو اعمال می‌شه.
"""
import types

from django.contrib.admin import site as default_admin_site

_original_get_app_list = default_admin_site.__class__.get_app_list

# (app_label مدل, اسم کلاس مدل, برچسبی که به‌عنوان گروه مستقل نشون داده می‌شه)
PINNED_MODELS = [
    ('tickets', 'Ticket', 'بلیط‌ها'),
    ('accounts', 'User', 'کاربران'),
]


def _pinned_get_app_list(self, request, app_label=None):
    app_list = _original_get_app_list(self, request, app_label=app_label)

    pinned_groups = []
    for target_app_label, target_object_name, group_label in PINNED_MODELS:
        for app in app_list:
            if app['app_label'] != target_app_label:
                continue
            for i, model in enumerate(app['models']):
                if model['object_name'] == target_object_name:
                    extracted = app['models'].pop(i)
                    pinned_groups.append({
                        'name': group_label,
                        'app_label': f'pinned_{target_object_name.lower()}',
                        'app_url': extracted['admin_url'],
                        'has_module_perms': True,
                        'models': [extracted],
                    })
                    break
            break

    # اگر با حذف مدل پین‌شده، اپی خالی از مدل موند (مثلاً ACCOUNTS فقط
    # همون User رو داشت)، خودِ آن گروه خالی از سایدبار حذف می‌شود
    app_list = [app for app in app_list if app['models']]

    return pinned_groups + app_list


default_admin_site.get_app_list = types.MethodType(_pinned_get_app_list, default_admin_site)
