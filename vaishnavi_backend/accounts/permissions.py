from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsMasterAdmin(BasePermission):
    """Allow only MASTER_ADMIN users to access."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.is_superuser
        )

    
    @property
    def is_vsre_staff(self):
        return self.user_type in [self.UserTypes.VSRE_STAFF]

class IsVSREOwner(BasePermission):
    """Allow only VSRE_OWNER."""
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and 
            request.user.is_owner
        )


class IsVSREOwnerOrManager(BasePermission):
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
