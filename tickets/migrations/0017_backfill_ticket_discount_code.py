from django.db import migrations


def backfill_discount_code_tickets(apps, schema_editor):
    """
    قبل از این مایگریشن، هیچ فیلدی روی خودِ Ticket نبود که مشخص کنه کدوم
    بلیط دقیقاً با یک کد تخفیف خریداری شده (فقط Order.discount_code بود که
    سطحِ کل سفارش بود، نه هر بلیط). این مایگریشن بلیط‌های قدیمیِ از قبل
    ثبت‌شده رو بر همون اساس برمی‌گردونه و پر می‌کنه، تا گزارش‌های تاریخی هم
    مثل بلیط‌های جدید درست دسته‌بندی بشن.

    بلیطی که واقعاً به‌خاطر سنِ زیر ۱۵ رایگان بوده (price=0 و age<15) از این
    برچسب‌گذاری مستثنا می‌شه، چون کد تخفیف روی بلیطِ رایگانِ سنی اصلاً اعمال
    نمی‌شه (طبق منطق tickets/views.py و payments/views.py).
    """
    Ticket = apps.get_model('tickets', 'Ticket')
    Order = apps.get_model('tickets', 'Order')
    DiscountCode = apps.get_model('tickets', 'DiscountCode')

    orders_with_code = Order.objects.exclude(discount_code='').exclude(discount_code__isnull=True)
    for order in orders_with_code.iterator():
        try:
            code_obj = DiscountCode.objects.get(code=order.discount_code)
        except DiscountCode.DoesNotExist:
            continue
        if not order.discount_percent or order.discount_percent <= 0:
            continue

        for ticket in Ticket.objects.filter(order=order):
            if ticket.price is None:
                continue
            is_free_age_ticket = ticket.price == 0 and ticket.age is not None and ticket.age < 15
            if is_free_age_ticket:
                continue

            denom = 1 - (order.discount_percent / 100)
            if denom <= 0:
                continue
            original_price = round(ticket.price / denom)
            amount = max(original_price - ticket.price, 0)
            if amount <= 0:
                continue

            ticket.discount_code = code_obj
            ticket.discount_code_amount = amount
            ticket.save(update_fields=['discount_code', 'discount_code_amount'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0016_ticket_discount_code_ticket_discount_code_amount'),
    ]

    operations = [
        migrations.RunPython(backfill_discount_code_tickets, noop_reverse),
    ]
