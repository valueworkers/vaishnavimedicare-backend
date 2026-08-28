# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Notification
from .utils import push_notification


@receiver(post_save, sender=Notification)
def notification_live(sender, instance, created, **kwargs):
    push_notification(instance)