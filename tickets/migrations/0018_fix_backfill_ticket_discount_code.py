from django.db import migrations


def backfill_discount_code_tickets(apps, schema_editor):
    """
    مایگریشن قبلی (0017) برای کدهای ۱۰۰٪ تخفیف کار نمی‌کرد: چون سعی می‌کرد
    قیمتِ قبل از تخفیف را با تقسیم بر (۱ - درصد/۱۰۰) برگرداند، و برای
    درصد=۱۰۰ این عدد صفر می‌شود (تقسیم بر صفر) -- در نتیجه هیچ بلیطی
    برچسب نخورد (حتی روی داده‌ی واقعی که یک بلیط با کد ۱۰۰٪ خریداری شده بود).

    این نسخه به‌جای معکوس‌کردن درصد، مستقیماً از خودِ Order.subtotal (مبلغ
    قبل از کد) و Order.discount_amount (مبلغِ تخفیفِ کد، برای کل سفارش)
    استفاده می‌کند که مستقل از درصد و همیشه صحیح است. اگر سفارش چند بلیط
    داشته باشد، چون قیمتِ تفکیکی هر بلیط قبل از کد جایی ذخیره نشده،
    مبلغ تخفیف به‌طور مساوی بین بلیط‌های مشمول (غیر رایگانِ سنی) همان سفارش
    تقسیم می‌شود -- تنها تقریبِ ممکن با داده‌ی موجود.
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
        if not order.discount_amount or order.discount_amount <= 0:
            continue

        tickets = list(Ticket.objects.filter(order=order))
        discountable_tickets = [
            t for t in tickets
            if t.price is not None and not (t.price == 0 and t.age is not None and t.age < 15)
        ]
        if not discountable_tickets:
            continue

        n = len(discountable_tickets)
        base_share = order.discount_amount // n
        remainder = order.discount_amount - base_share * n

        for i, ticket in enumerate(discountable_tickets):
            amount = base_share + (1 if i < remainder else 0)
            if amount <= 0:
                continue
            ticket.discount_code = code_obj
            ticket.discount_code_amount = amount
            ticket.save(update_fields=['discount_code', 'discount_code_amount'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0017_backfill_ticket_discount_code'),
    ]

    operations = [
        migrations.RunPython(backfill_discount_code_tickets, noop_reverse),
    ]
