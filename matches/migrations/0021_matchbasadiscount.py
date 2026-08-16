from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0020_alter_matchblockprice_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='MatchBasaDiscount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('discount_percent', models.PositiveSmallIntegerField(verbose_name='درصد تخفیف باسا')),
                ('match', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='basa_discount', to='matches.match')),
            ],
            options={
                'verbose_name': 'تخفیف باسا برای مسابقه',
                'verbose_name_plural': 'تخفیف‌های باسا برای مسابقات',
            },
        ),
    ]
