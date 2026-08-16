from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0010_ticket_share_token'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='age',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='سن'),
        ),
    ]
