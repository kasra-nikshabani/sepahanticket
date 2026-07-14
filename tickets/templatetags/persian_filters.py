# tickets/templatetags/persian_filters.py
from django import template

register = template.Library()

@register.filter(name='to_persian')
def to_persian(value):
    if value is None:
        return '۰'
    persian = {'0':'۰','1':'۱','2':'۲','3':'۳','4':'۴','5':'۵','6':'۶','7':'۷','8':'۸','9':'۹'}
    return ''.join(persian.get(c, c) for c in str(value))