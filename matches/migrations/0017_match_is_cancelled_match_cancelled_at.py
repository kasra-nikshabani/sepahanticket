from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0016_match_ticket_sales_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='is_cancelled',
            field=models.BooleanField(default=False, verbose_name='لغو شده'),
        ),
        migrations.AddField(
            model_name='match',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='زمان لغو'),
        ),
    ]
