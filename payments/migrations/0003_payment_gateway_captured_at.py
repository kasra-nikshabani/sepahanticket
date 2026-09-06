from django.db import migrations, models


def backfill_captured(apps, schema_editor):
    """رکوردهای موفقِ قدیمی را پر می‌کند.

    هر پرداختی که status='success' دارد قطعاً پولش گرفته شده -- گزارش‌ها هم
    تا امروز بر همین مبنا کار می‌کردند. پس مقدار این فیلد برایشان معلوم است.

    رکوردهای pending/failed عمداً دست نمی‌خورند: درباره‌ی آن‌ها *نمی‌دانیم* پول
    گرفته شده یا نه، و همین ندانستن باید حفظ شود تا sweep_pending_payments
    از خودِ زیبال بپرسد. پر کردنشان با حدس، دقیقاً همان خطایی است که این
    فیلد برای رفعش ساخته شده.
    """
    Payment = apps.get_model('payments', 'Payment')
    Payment.objects.filter(status='success', gateway_captured_at__isnull=True,
                           processed_at__isnull=False).update(
        gateway_captured_at=models.F('processed_at'))
    # چند رکورد قدیمی processed_at ندارند؛ برایشان زمان به‌روزرسانی مبنا است.
    Payment.objects.filter(status='success', gateway_captured_at__isnull=True).update(
        gateway_captured_at=models.F('updated_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_payment_delete_transaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='gateway_captured_at',
            field=models.DateTimeField(
                blank=True, db_index=True, null=True,
                help_text='لحظه‌ای که زیبال تأیید کرد پول از کاربر گرفته شده -- '
                          'مستقل از اینکه بلیط صادر شد یا نه'),
        ),
        migrations.RunPython(backfill_captured, migrations.RunPython.noop),
    ]
