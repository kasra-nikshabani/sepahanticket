from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import Wallet

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_wallet_for_user(sender, instance, created, **kwargs):
    if created and instance.user_type != 'vip':
        Wallet.objects.create(user=instance)