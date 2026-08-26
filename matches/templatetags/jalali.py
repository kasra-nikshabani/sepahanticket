from django import template
import jdatetime
from datetime import datetime
from django.utils import timezone as django_timezone

register = template.Library()


def _to_local_jalali(date_obj):
    """تبدیل به jdatetime، با لوکالایز به منطقه‌زمانی فعال (Asia/Tehran) اگر
    ورودی timezone-aware باشه. بدون این، چون همه‌ی تاریخ‌ها در دیتابیس به
    UTC ذخیره می‌شن (USE_TZ=True)، ساعت نمایش‌داده‌شده ۳:۳۰ ساعت عقب‌تر از
    ساعت واقعی تهران بود."""
    if not date_obj or not isinstance(date_obj, datetime):
        return None
    if django_timezone.is_aware(date_obj):
        date_obj = django_timezone.localtime(date_obj)
    return jdatetime.datetime.fromgregorian(datetime=date_obj)


@register.filter
def to_jalali(date_obj):
    """تبدیل تاریخ میلادی به شمسی با فرمت نمایشی"""
    jalali_date = _to_local_jalali(date_obj)
    if not jalali_date:
        return ''
    return jalali_date.strftime('%Y/%m/%d - %H:%M')

@register.filter
def to_jalali_date(date_obj):
    """تبدیل تاریخ میلادی به شمسی (فقط تاریخ)"""
    jalali_date = _to_local_jalali(date_obj)
    if not jalali_date:
        return ''
    return jalali_date.strftime('%Y/%m/%d')

@register.filter
def to_jalali_time(date_obj):
    """تبدیل تاریخ میلادی به شمسی (فقط ساعت)"""
    jalali_date = _to_local_jalali(date_obj)
    if not jalali_date:
        return ''
    return jalali_date.strftime('%H:%M')

@register.filter
def to_jalali_full(date_obj):
    """تبدیل تاریخ میلادی به شمسی با ماه و روز هفته به فارسی"""
    jalali_date = _to_local_jalali(date_obj)
    if not jalali_date:
        return ''
    months = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
              'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']
    weekdays = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه']
    return f"{weekdays[jalali_date.weekday()]} {jalali_date.day} {months[jalali_date.month-1]} {jalali_date.year} - {jalali_date.strftime('%H:%M')}"