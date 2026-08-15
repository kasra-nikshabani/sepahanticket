from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_sitesettings_bypass_civil_registry_inquiry'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='gender',
            field=models.CharField(
                blank=True,
                choices=[('male', 'مرد'), ('female', 'زن')],
                max_length=10,
                null=True,
                verbose_name='جنسیت',
            ),
        ),
    ]
