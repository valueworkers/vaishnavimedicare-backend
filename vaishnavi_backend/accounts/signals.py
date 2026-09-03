from django.db.models.signals import post_save, post_migrate
from django.core.management import call_command
from django.contrib.auth.models import Group
from django.dispatch import receiver
from django.utils import timezone
from .models import CustomUser,UserHierarchy
from django.db import transaction


# ---------------------------
# Assign Group on User Save
# ---------------------------
@receiver(post_save, sender=CustomUser)
def assign_group_to_user(sender, instance, created, **kwargs):
    """Automatically assign the correct group based on user_type."""
    if not instance.user_type:
        return

    try:
        group = Group.objects.get(name=instance.user_type)
    except Group.DoesNotExist:
        return

    # Remove user from other groups and add to correct one
    instance.groups.clear()
    instance.groups.add(group)


# ---------------------------
# Auto-create Groups after Migration
# ---------------------------
# @receiver(post_migrate)
# def create_default_groups_after_migration(sender, **kwargs):
#     """Automatically run group creation after migrations."""
#     if sender.name != "accounts":
#         return
#     print("Running post_migrate: creating default groups and permissions...")
#     call_command("create_default_groups")


# ---------------------------
# Auto generate Employee Id 
# ---------------------------

@receiver(post_save, sender=CustomUser)
def generate_employee_id(sender, instance, created, **kwargs):
    """
    Generate employee ID format:

    M20250001
    LM20250001
    S20250001
    """

    # Prevent regeneration
    if not created or instance.employee_id:
        return

    prefix_map = {
        "VSRE_MANAGER": "M",
        "LINE_MANAGER": "LM",
        "VSRE_STAFF": "S",
    }

    prefix = prefix_map.get(instance.user_type)

    # Skip if invalid type
    if not prefix:
        return

    year = timezone.now().year

    with transaction.atomic():
        instance.employee_id = f"{prefix}{year}{instance.id:04d}"
        CustomUser.objects.filter(pk=instance.pk).update(
            employee_id=instance.employee_id
        )