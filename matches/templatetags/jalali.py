from django import template
import jdatetime
from datetime import datetime

register = template.Library()

@register.filter
def to_jalali(date_obj):
    """تبدیل تاریخ میلادی به شمسی با فرمت نمایشی"""
    if not date_obj:
        return ''
    if isinstance(date_obj, datetime):
        # تبدیل datetime به jdatetime
        jalali_date = jdatetime.datetime.fromgregorian(datetime=date_obj)
        return jalali_date.strftime('%Y/%m/%d - %H:%M')
    return ''

@register.filter
def to_jalali_date(date_obj):
    """تبدیل تاریخ میلادی به شمسی (فقط تاریخ)"""
    if not date_obj:
        return ''
    if isinstance(date_obj, datetime):
        jalali_date = jdatetime.datetime.fromgregorian(datetime=date_obj)
        return jalali_date.strftime('%Y/%m/%d')
    return ''

@register.filter
def to_jalali_time(date_obj):
    """تبدیل تاریخ میلادی به شمسی (فقط ساعت)"""
    if not date_obj:
        return ''
    if isinstance(date_obj, datetime):
        jalali_date = jdatetime.datetime.fromgregorian(datetime=date_obj)
        return jalali_date.strftime('%H:%M')
    return ''

@register.filter
def to_jalali_full(date_obj):
    """تبدیل تاریخ میلادی به شمسی با ماه و روز هفته به فارسی"""
    if not date_obj:
        return ''
    if isinstance(date_obj, datetime):
        jalali_date = jdatetime.datetime.fromgregorian(datetime=date_obj)
        months = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                  'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']
        weekdays = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه']
        return f"{weekdays[jalali_date.weekday()]} {jalali_date.day} {months[jalali_date.month-1]} {jalali_date.year} - {jalali_date.strftime('%H:%M')}"
    return ''