from django.db.models.signals import post_save, post_migrate
from django.core.management import call_command
from django.contrib.auth.models import Group
from django.dispatch import receiver
from django.utils import timezone
from .models import CustomUser, EmployeeProfile
from django.db.models import Q


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

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import EmployeeProfile


@receiver(post_save, sender=EmployeeProfile)
def generate_employee_id(sender, instance, created, **kwargs):
    """
    Generate employee ID when EmployeeProfile is created.

    Works for existing CustomUser records.
    Does not overwrite an existing employee_id.
    """

    # Only generate on creation
    if not created:
        return

    # Do not overwrite existing employee_id
    if instance.employee_id:
        return

    prefix_map = {
        "VSRE_MANAGER": "M",
        "LINE_MANAGER": "LM",
        "VSRE_STAFF": "S",
    }

    prefix = prefix_map.get(instance.user.user_type)

    # Skip non-employee user types
    if not prefix:
        return

    year = timezone.now().year

    employee_id = f"{prefix}{year}{instance.user_id:04d}"

    # Use update to avoid triggering post_save again
   
    sender.objects.filter(
        Q(employee_id__isnull=True) | Q(employee_id=""),
        pk=instance.pk,
    ).update(
        employee_id=employee_id
    )