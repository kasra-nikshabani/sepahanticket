from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_user_gender'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_basa_member',
            field=models.BooleanField(default=False, verbose_name='عضو باسا'),
        ),
    ]
