from rest_framework.permissions import BasePermission, SAFE_METHODS

class EntityAccessPermission(BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.user.can_manage_entity(obj)

class CanAssignUsers(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_owner or request.user.is_manager or request.user.is_superuser
        )
