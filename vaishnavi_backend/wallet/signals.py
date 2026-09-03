
from django.db.models.signals import post_save
from django.dispatch import receiver
from accounts.models import CustomUser
from .models import Wallet

@receiver(post_save, sender=CustomUser)
def create_wallet_for_customer(sender, instance, created, **kwargs):
    """Auto-create wallet when a customer account is created."""
    if created and instance.is_customer:
        Wallet.objects.get_or_create(user=instance)