from django import template

register = template.Library()

@register.filter
def filter_by_status(block_status, status):
    """فیلتر کردن لیست block_status بر اساس وضعیت"""
    return [item for item in block_status if item.get('status') == status]

@register.filter
def mul(value, arg):
    """ضرب دو عدد"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def div(value, arg):
    """تقسیم دو عدد"""
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def neg(value):
    """تبدیل به عدد منفی (برای محاسبه اشغال)"""
    try:
        return -int(value)
    except (ValueError, TypeError):
        return 0