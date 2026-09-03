from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from .models import Photos

# ---- Delete from storage when Photo record is deleted ----
@receiver(post_delete, sender=Photos)
def delete_photo_on_delete(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(save=False)


# ---- Delete old image from storage when Photo is updated ----
@receiver(pre_save, sender=Photos)
def delete_old_photo_on_update(sender, instance, **kwargs):
    if not instance.pk:
        return  # New record, skip
    try:
        old = Photos.objects.get(pk=instance.pk)
        if old.image and old.image.name != instance.image.name:
            old.image.delete(save=False)
    except Photos.DoesNotExist:
        pass