# football_tickets/wallet/templatetags/currency_filters.py
#
# این تنها ماژول currency_filters توی کل پروژه‌ست -- قبلاً ۴ نسخه‌ی هم‌نام
# (accounts, matches, payments, tickets) با فیلترهای مختلف وجود داشت که
# جنگو به‌صورت ضمنی (بر اساس ترتیب لود اپ‌ها) فقط یکی‌شون رو انتخاب می‌کرد؛
# اگر آن ترتیب عوض می‌شد، هر صفحه‌ای که از rial_display استفاده می‌کرد
# می‌توانست ناگهان با TemplateSyntaxError خراب شود. الان فقط همین یک نسخه
# هست، پس ابهامی در بارگذاری {% load currency_filters %} وجود ندارد.
from django import template

register = template.Library()


@register.filter(name='rial_display')
def rial_display(value):
    """
    نمایش ریال با جداکننده هزارگان (بدون تبدیل)
    """
    if value is None:
        return '۰'
    try:
        return f"{int(value):,}".replace(',', '٬')
    except (ValueError, TypeError):
        return value


@register.filter(name='to_rial')
def to_rial(value):
    """
    تبدیل تومان به ریال با جداکننده هزارگان
    """
    if value is None:
        return '۰'
    try:
        rial_value = int(float(value) * 10)
        return f"{rial_value:,}".replace(',', '٬')
    except (ValueError, TypeError):
        return value


@register.filter(name='rial_value')
def rial_value(value):
    """
    تبدیل تومان به ریال به صورت عدد خالص
    """
    if value is None:
        return '0'
    try:
        return int(float(value) * 10)
    except (ValueError, TypeError):
        return '0'