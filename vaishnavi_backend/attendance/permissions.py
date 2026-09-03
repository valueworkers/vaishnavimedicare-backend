from rest_framework.permissions import BasePermission, SAFE_METHODS


class IsSuperUserOrOwnerOrReadOnly(BasePermission):
    """
    Superusers and Owners have full access.
    All other users: read-only
    """

    def has_permission(self, request, view):
        # Read-only access for everyone
        if request.method in SAFE_METHODS:
            return True

        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.is_owner)
        )
