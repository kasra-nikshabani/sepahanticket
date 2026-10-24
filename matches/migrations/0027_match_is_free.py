from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0026_match_has_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='is_free',
            field=models.BooleanField(default=False, help_text='اگر روشن باشد، همه‌ی بلیط‌های این مسابقه رایگان صادر می‌شوند.', verbose_name='مسابقه رایگان'),
        ),
    ]
