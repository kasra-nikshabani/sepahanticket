from django.db import migrations, models


def backfill_floor_from_name(apps, schema_editor):
    """
    قبل از این مایگریشن، «طبقه» هر بلوک فقط از روی وجود رشته‌ی «(طبقه دوم)»
    در نام بلوک تشخیص داده می‌شد (در matches/views.py: select_block). این
    تابع همان قرارداد را دقیقاً بازتولید می‌کند تا رفتار فعلی سایت برای
    بلوک‌های موجود عوض نشود.
    """
    Block = apps.get_model('matches', 'Block')
    Block.objects.filter(name__contains='طبقه دوم').update(floor='second')


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0017_match_is_cancelled_match_cancelled_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='block',
            name='floor',
            field=models.CharField(
                choices=[('ground', 'طبقه پایین'), ('second', 'طبقه دوم')],
                default='ground',
                max_length=10,
                verbose_name='طبقه',
            ),
        ),
        migrations.RunPython(backfill_floor_from_name, reverse_code=migrations.RunPython.noop),
    ]
