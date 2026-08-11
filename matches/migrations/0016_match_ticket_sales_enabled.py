from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0015_alter_block_is_vip_alter_block_zone_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='ticket_sales_enabled',
            field=models.BooleanField(default=True, verbose_name='فروش بلیط فعال'),
        ),
    ]
