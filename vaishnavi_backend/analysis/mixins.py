from accounts.models import CustomUser
from attendance.models import Attendance


class PermissionScopeMixin:
    """
    Provides get_attendance_queryset() and get_user_queryset() scoped
    to the requesting user's role.

    Roles:
        - Superuser  → full access to all records
        - Owner      → access to their own staff/managers via hierarchy
        - Everyone else (staff/manager) → own records only
    """

    ALLOWED_USER_TYPES = ["VSRE_MANAGER", "LINE_MANAGER", "VSRE_STAFF"]

    def get_user_queryset(self, request):
        """
        Returns a scoped CustomUser queryset based on the requesting user's role.
        Use this wherever you need to list or look up employees.
        """
        user = request.user
        base_qs = CustomUser.objects.filter(
            user_type__in=self.ALLOWED_USER_TYPES,
        )

        if user.is_superuser:
            return base_qs

        if user.is_owner:
            return base_qs.filter(hierarchy__owner=user)

        # Staff / manager → only themselves
        return base_qs.filter(pk=user.pk)

    def get_attendance_queryset(self, request):
        """
        Returns a scoped Attendance queryset based on the requesting user's role.
        Use this as the base queryset before applying any further filters.
        """
        user = request.user

        if user.is_superuser:
            return Attendance.objects.all()

        if user.is_owner:
            return Attendance.objects.filter(user__hierarchy__owner=user)

        # Staff / manager → only their own attendance
        return Attendance.objects.filter(user=user)
