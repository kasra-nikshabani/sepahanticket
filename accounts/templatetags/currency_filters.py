# tickets/templatetags/currency_filters.py
from django import template
from django.template.defaultfilters import floatformat

register = template.Library()

@register.filter(name='to_rial')
def to_rial(value):
    """
    تبدیل تومان به ریال (ضرب در ۱۰) و اضافه کردن جداکننده هزارگان
    مثال: 1000 تومان → ۱۰,۰۰۰ ریال
    """
    if value is None:
        return '۰'
    try:
        value = float(value)
        rial_value = int(value * 10)
        return f"{rial_value:,}".replace(',', '٬')
    except (ValueError, TypeError):
        return value


@register.filter(name='price_format')
def price_format(value, unit='rial'):
    """
    نمایش قیمت با واحد مشخص (ریال یا تومان)
    استفاده: {{ price|price_format:"rial" }}
    """
    if value is None:
        return '۰'
    try:
        value = float(value)
        if unit == 'rial':
            rial_value = int(value)
            formatted = f"{rial_value:,}".replace(',', '٬')
            return f"{formatted} ریال"
        elif unit == 'toman':
            rial_value = int(value * 10)
            formatted = f"{rial_value:,}".replace(',', '٬')
            return f"{formatted} ریال"
        else:
            return f"{int(value):,}".replace(',', '٬')
    except (ValueError, TypeError):
        return value


@register.filter(name='rial')
def rial(value):
    """
    فقط تبدیل تومان به ریال (بدون واحد) با جداکننده
    """
    if value is None:
        return '۰'
    try:
        return f"{int(float(value) * 10):,}".replace(',', '٬')
    except (ValueError, TypeError):
        return value


@register.filter(name='rial_value')
def rial_value(value):
    """
    تبدیل تومان به ریال به صورت عدد خالص (بدون جداکننده و بدون واحد)
    مناسب برای مقدار input fields و ارسال به درگاه
    مثال: 1000 تومان → 10000
    """
    if value is None:
        return '0'
    try:
        return int(float(value) * 10)
    except (ValueError, TypeError):
        return '0'