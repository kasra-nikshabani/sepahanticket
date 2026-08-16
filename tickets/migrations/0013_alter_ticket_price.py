from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0012_ticket_basa_discount_amount'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ticket',
            name='price',
            field=models.BigIntegerField(blank=True, default=None, null=True, verbose_name='قیمت (ریال)'),
        ),
    ]
