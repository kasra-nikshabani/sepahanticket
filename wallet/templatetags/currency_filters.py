# football_tickets/tickets/templatetags/currency_filters.py
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