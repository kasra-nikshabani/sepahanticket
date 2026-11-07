# Generated for the Didavar art card application workflow.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0027_supportticket_studio'),
    ]

    operations = [
        migrations.CreateModel(
            name='ArtCardApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('requested', 'درخواست ثبت‌شده'), ('sent_to_bank', 'ارسال‌شده به بانک'), ('active', 'صادرشده و فعال'), ('rejected', 'نیازمند پیگیری')], db_index=True, default='requested', max_length=16)),
                ('bank_reference', models.CharField(blank=True, max_length=100, verbose_name='شناسه پیگیری بانک')),
                ('card_last_four', models.CharField(blank=True, max_length=4, verbose_name='چهار رقم پایانی کارت')),
                ('admin_note', models.TextField(blank=True, max_length=2000, verbose_name='پیام به کاربر')),
                ('requested_at', models.DateTimeField(auto_now_add=True, verbose_name='زمان درخواست')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='آخرین به‌روزرسانی')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='art_card_application', to=settings.AUTH_USER_MODEL, verbose_name='کاربر')),
            ],
            options={
                'verbose_name': 'درخواست هنرکارت',
                'verbose_name_plural': 'درخواست‌های هنرکارت',
                'ordering': ['-requested_at'],
            },
        ),
    ]
