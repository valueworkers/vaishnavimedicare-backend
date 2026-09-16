from rest_framework.permissions import BasePermission, SAFE_METHODS
from .models import CustomUser


class IsMasterAdmin(BasePermission):
    """Allow only MASTER_ADMIN users to access."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )

    
    @property
    def is_vsre_staff(self):
        return self.user_type in [self.UserTypes.VSRE_STAFF]

class IsOwnerOrReadOnly(BasePermission):
    """
    MASTER_ADMIN and VSRE_OWNER can perform all operations.
    Any authenticated user can perform safe/read-only operations.
    """

    allowed_roles = {
        "MASTER_ADMIN",
        "VSRE_OWNER",
    }

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        # Read-only requests are allowed for all authenticated users
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True

        # Write operations are restricted to owners
        return user.user_type in self.allowed_roles
    
class IsOwner(BasePermission):
    """Allow only VSRE_OWNER."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and 
            request.user.is_owner
        )


class IsOwnerOrManager(BasePermission):
    """Allow both VSRE_OWNER and VSRE_MANAGER."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.is_manager or request.user.is_owner 
        )


class IsMasterAdminOrOwner(BasePermission):
    """Allow both VSRE_OWNER and VSRE_MANAGER."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.is_superuser or request.user.is_owner 
        )

class IsCreator(BasePermission):
    """Allow access only to objects created by the user."""

    def has_object_permission(self, request, view, obj):
        return obj.created_by == request.user


class CanManageEmployees(BasePermission):
    """
    Owner   -> manages every employee (manager or staff) in their hierarchy.
    Manager -> manages only the staff reporting directly to them.
    Others  -> no access.

    Object-level check replaces the old separate `IsCreator` permission:
    it verifies the target employee actually sits under the requester's
    hierarchy, not just that the requester holds a management role.
    """

    message = "You do not have permission to manage this employee."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.is_owner or user.is_manager)
        )

    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_superuser:
            return True

        hierarchy = getattr(obj, "hierarchy", None)
        if hierarchy is None:
            return False

        if user.is_owner:
            return hierarchy.owner_id == user.id

        if user.is_manager:
            return (
                hierarchy.parent_id == user.id
                and obj.user_type == CustomUser.UserTypes.VSRE_STAFF
            )

        return False
    