from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0011_ticket_age'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='basa_discount_amount',
            field=models.PositiveIntegerField(default=0, verbose_name='مبلغ تخفیف باسا (ریال)'),
        ),
    ]
