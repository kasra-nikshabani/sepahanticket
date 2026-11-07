from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from matches.models import Event, Match
from .models import ArtistCredit
from .services import notify_artist_event


@receiver(pre_save, sender=Event)
def remember_publication(sender, instance, raw=False, **kwargs):
    if not raw:
        instance._artist_was_public = sender.objects.filter(pk=instance.pk, is_active=True).exists()


@receiver(post_save, sender=Event)
def published_event(sender, instance, raw=False, **kwargs):
    if not raw and instance.is_active and not getattr(instance, '_artist_was_public', True):
        notify_artist_event(instance)


@receiver(pre_save, sender=Match)
def remember_sales(sender, instance, raw=False, **kwargs):
    if not raw:
        previous = sender.objects.filter(pk=instance.pk).first() if instance.pk else None
        instance._artist_sales_were_open = previous.sales_available if previous else False


@receiver(post_save, sender=Match)
def opened_sales(sender, instance, raw=False, **kwargs):
    if not raw and instance.event_id and instance.sales_available and not getattr(instance, '_artist_sales_were_open', True):
        notify_artist_event(instance.event, session=instance)


@receiver(pre_save, sender=ArtistCredit)
def remember_credit(sender, instance, raw=False, **kwargs):
    if not raw:
        instance._artist_was_confirmed = sender.objects.filter(pk=instance.pk, status='accepted').exists()


@receiver(post_save, sender=ArtistCredit)
def confirmed_credit(sender, instance, raw=False, **kwargs):
    if not raw and instance.status == 'accepted' and not getattr(instance, '_artist_was_confirmed', True):
        notify_artist_event(instance.event)
