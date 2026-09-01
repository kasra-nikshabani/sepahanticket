from django.db import migrations, models


class Migration(migrations.Migration):
    """کلید جدا برای «شارژ کیف پول».

    عمداً به 0013 وابسته است نه به آخرین migration این شاخه: شاخه‌ی
    feature/keycloak-sso چند migration دارد که روی main نیستند، و 0013
    آخرین گره‌ی مشترک بین دو شاخه است. وابستگی به یک گره‌ی feature-only
    روی production خطای NodeNotFoundError می‌دهد.
    """

    dependencies = [
        ('accounts', '0013_sitesettings_free_under_15'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitesettings',
            name='wallet_charge_enabled',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'اگر خاموش باشد کاربر نمی‌تواند کیف پولش را شارژ کند، ولی '
                    'موجودی فعلی‌اش همچنان برای خرید بلیط قابل استفاده است '
                    '(به شرطی که «فعال بودن کیف پول» روشن باشد).'
                ),
                verbose_name='امکان شارژ کیف پول',
            ),
        ),
    ]
