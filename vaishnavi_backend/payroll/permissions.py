from rest_framework.permissions import BasePermission
from rest_framework.permissions import SAFE_METHODS


class IsOwnerOrReadOnly(BasePermission):
    """Only owners and superusers may change attendance configuration."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or request.user.is_owner)
        )


class CanViewSalaryReport(BasePermission):
    """
    Object-level permission for salary reports.

    Accepts either a CustomUser instance or any object exposing a
    `.user` attribute (e.g. SalaryReport) as `obj`.

    - Superuser: can view anyone's report(s).
    - Owner: can view reports for users in their own hierarchy.
    - Everyone else: can only view their own report(s).
    """

    message = "You do not have permission to view this report."

    def has_permission(self, request, view):
        # Object-level checks only; require authentication at the view level.
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        target_user = getattr(obj, "user", obj)
        request_user = request.user

        if request_user.is_superuser:
            return True

        if request_user.is_owner:
            owner_id = getattr(getattr(target_user, "hierarchy", None), "owner_id", None)
            return owner_id == request_user.id

        return target_user.id == request_user.id
