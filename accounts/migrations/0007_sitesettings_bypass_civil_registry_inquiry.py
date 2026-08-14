from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_user_national_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='bypass_civil_registry_inquiry',
            field=models.BooleanField(
                default=False,
                verbose_name='غیرفعال‌سازی استعلام ثبت‌احوال (حالت اضطراری)',
                help_text=(
                    'فقط برای مواقعی که سرویس استعلام ثبت‌احوال قطع/خراب است. در صورت '
                    'فعال بودن، خریدار بلیط بدون تأیید هویت از ثبت‌احوال می‌تواند خرید را '
                    'تکمیل کند (فقط فرمت اطلاعات -- نام فارسی و کد ملی ۱۰ رقمی -- چک '
                    'می‌شود). محاسبه‌ی قیمت و سن هیچ‌وقت به این سرویس وابسته نیست و همیشه '
                    'سمت سرور مستقل دوباره محاسبه می‌شود.'
                ),
            ),
        ),
    ]
