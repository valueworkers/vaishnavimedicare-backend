from rest_framework.exceptions import ValidationError
from accounts.models import CustomUser

MANAGER_TYPES = ("VSRE_MANAGER", "LINE_MANAGER")


def validate_employees_exist(employee_ids, employees):
    found = set(employees.values_list("id", flat=True))
    missing = set(employee_ids) - found

    if missing:
        raise ValidationError({
            "Invalid": f"Employees do not exist with IDs: {', '.join(map(str, missing))}"
        })


def validate_owner_permissions(user, employees):
    for e in employees:
        if e.hierarchy.owner != user:
            raise PermissionError(f"Employee {e.id} does not belong to you")


def validate_manager_permissions(user, entity, employees):
    if not entity.manager.filter(id=user.id).exists():
        raise PermissionError("You are not assigned as manager for this item")

    for e in employees:
        if e.user_type in MANAGER_TYPES:
            raise PermissionError("Managers cannot assign other managers")
        if e.hierarchy.parent_id != user.id:
            raise PermissionError(f"Employee {e.id} does not report to you")


def auto_assign_staff(manager_ids):
    return CustomUser.objects.filter(
        hierarchy__parent_id__in=manager_ids,
        user_type="VSRE_STAFF",
    )