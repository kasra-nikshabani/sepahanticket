import uuid

from django.db import migrations, models


def generate_share_tokens(apps, schema_editor):
    Ticket = apps.get_model('tickets', 'Ticket')
    for ticket in Ticket.objects.all().only('id'):
        Ticket.objects.filter(pk=ticket.pk).update(share_token=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0009_alter_order_payment_method'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticket',
            name='share_token',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(generate_share_tokens, reverse_code=migrations.RunPython.noop),
        migrations.AlterField(
            model_name='ticket',
            name='share_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
