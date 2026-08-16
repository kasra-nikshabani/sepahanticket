from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0019_matchblockprice'),
    ]

    operations = [
        migrations.AlterField(
            model_name='matchblockprice',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
    ]
