from accounts.models import CustomUser
from rest_framework.exceptions import ValidationError

def validate_owner_permissions(user, managers, staff_members):
    for m in managers:
        if m.hierarchy.owner != user:
            raise PermissionError(f"Manager {m.id} does not belong to you")

    for s in staff_members:
        if s.hierarchy.owner != user:
            raise PermissionError(f"Staff {s.id} does not belong to you")


def validate_manager_permissions(user, entity, manager_ids, staff_members):
    if not entity.manager.filter(id=user.id).exists():
        raise PermissionError("You are not assigned as manager for this item")

    if manager_ids:
        raise PermissionError("Managers cannot assign other managers")

    for s in staff_members:
        if s.hierarchy.parent_id != user.id:
            raise PermissionError(f"Staff {s.id} does not report to you")
        
def validate_users_exist(manager_ids, staff_ids):
    # Managers check
    found_managers = set(
        CustomUser.objects.filter(id__in=manager_ids, user_type="VSRE_MANAGER")
        .values_list("id", flat=True)
    )
    missing_managers = set(manager_ids) - found_managers

    # Staff check
    found_staff = set(
        CustomUser.objects.filter(id__in=staff_ids, user_type="STAFF")
        .values_list("id", flat=True)
    )
    missing_staff = set(staff_ids) - found_staff

    # Build final error message
    error_parts = []
    if missing_managers:
        error_parts.append(f"Managers do not exist with IDs: {', '.join(map(str, missing_managers))}")

    if missing_staff:
        error_parts.append(f"Staff members do not exist with IDs: {', '.join(map(str, missing_staff))}")

    if error_parts:
        raise ValidationError({"Invalid": " | ".join(error_parts)})


def auto_assign_staff(manager_ids):
    return CustomUser.objects.filter(
        hierarchy__parent_id__in=manager_ids,
        user_type="VSRE_STAFF"
    )

