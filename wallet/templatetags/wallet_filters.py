# football_tickets/wallet/templatetags/wallet_filters.py
from django import template
from django.utils import translation

register = template.Library()


def _sep():
    return '٬' if (translation.get_language() or 'fa').startswith('fa') else ','


@register.filter(name='rial_display')
def rial_display(value):
    """
    نمایش ریال با جداکننده هزارگان (بدون تبدیل)
    """
    if value is None:
        return '۰' if _sep() == '٬' else '0'
    try:
        return f"{int(value):,}".replace(',', _sep())
    except (ValueError, TypeError):
        return value


@register.filter(name='to_rial')
def to_rial(value):
    """
    تبدیل تومان به ریال با جداکننده هزارگان
    """
    if value is None:
        return '۰' if _sep() == '٬' else '0'
    try:
        rial_value = int(float(value) * 10)
        return f"{rial_value:,}".replace(',', _sep())
    except (ValueError, TypeError):
        return value