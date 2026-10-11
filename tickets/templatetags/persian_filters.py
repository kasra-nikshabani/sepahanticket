# tickets/templatetags/persian_filters.py
from django import template
from django.utils import translation
from django.utils.translation import gettext

register = template.Library()

@register.filter(name='to_persian')
def to_persian(value):
    if not (translation.get_language() or 'fa').startswith('fa'):
        return '0' if value is None else str(value)
    if value is None:
        return '۰'
    persian = {'0':'۰','1':'۱','2':'۲','3':'۳','4':'۴','5':'۵','6':'۶','7':'۷','8':'۸','9':'۹'}
    return ''.join(persian.get(c, c) for c in str(value))


@register.filter(name='t')
def t(value):
    """ترجمه‌ی یک رشته‌ی پویا (مثلاً برچسب‌های ذخیره‌شده در داده) با gettext."""
    return gettext(value) if isinstance(value, str) and value else value
