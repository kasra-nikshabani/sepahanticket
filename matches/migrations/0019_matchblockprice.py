from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0018_block_floor'),
    ]

    operations = [
        migrations.CreateModel(
            name='MatchBlockPrice',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('price', models.DecimalField(decimal_places=0, max_digits=10, verbose_name='قیمت (ریال)')),
                ('block', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='match_price_overrides', to='matches.block')),
                ('match', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='block_price_overrides', to='matches.match')),
            ],
            options={
                'verbose_name': 'قیمت اختصاصی بلوک برای مسابقه',
                'verbose_name_plural': 'قیمت‌های اختصاصی بلوک برای مسابقات',
                'unique_together': {('match', 'block')},
            },
        ),
    ]
