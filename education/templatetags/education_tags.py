from datetime import date, datetime
import jdatetime
from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def education_date(value):
    if isinstance(value, datetime):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    if not isinstance(value, date):
        return ''
    return jdatetime.date.fromgregorian(date=value).strftime('%Y/%m/%d')
