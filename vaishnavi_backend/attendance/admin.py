from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum
from django.utils.timezone import now
from django.urls import reverse
from .models import AttendanceStatus, Attendance


# ------------------------------------------
# Attendance Status Admin
# ------------------------------------------
@admin.register(AttendanceStatus)
class AttendanceStatusAdmin(admin.ModelAdmin):
    list_display = (
        "owner",
        "label",
        "code",
        "is_active",   # must be here for list_editable
    )

    list_editable = ("is_active",)  # allowed now
    list_filter = ("owner", "is_active")
    search_fields = ("label", "code", "owner__email")
    ordering = ("owner", "label")
    list_per_page = 25
 
# ------------------------------------------
# Custom Filters
# ------------------------------------------
class MonthFilter(admin.SimpleListFilter):
    title = "Month"
    parameter_name = "month"

    def lookups(self, request, model_admin):
        return [(i, i) for i in range(1, 13)]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(date__month=self.value())
        return queryset


class YearFilter(admin.SimpleListFilter):
    title = "Year"
    parameter_name = "year"

    def lookups(self, request, model_admin):
        years = queryset_years = Attendance.objects.values_list(
            "date__year", flat=True
        ).distinct()
        return [(y, y) for y in years if y]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(date__year=self.value())
        return queryset


class UserFilter(admin.SimpleListFilter):
    title = "User"
    parameter_name = "user"

    def lookups(self, request, model_admin):
        users = (
            Attendance.objects.values_list("user__id", "user__first_name", "user__last_name")
            .distinct()
            .order_by("user__first_name", "user__last_name")
        )
        return [
            (user_id, f"{first_name} {last_name}".strip())
            for user_id, first_name, last_name in users
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(user__id=self.value())
        return queryset


# =====================================================
# Attendance Admin
# =====================================================
@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "date",
        "status",
        "formatted_duration",
        "created_at",
    )

    list_filter = (
        UserFilter,
        "status",
        MonthFilter,
        YearFilter,
    )

    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    ordering = ("-date",)
    date_hierarchy = "date"
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
    list_select_related = ("user", "status")
    list_per_page = 30

    actions = ("mark_present", "mark_absent")

    # ----------------------------
    # Display helpers
    # ----------------------------
    @admin.display(description="Duration (hrs)")
    def formatted_duration(self, obj):
        if obj.duration:
            return round(obj.duration.total_seconds() / 3600, 2)
        return 0

    # ----------------------------
    # Bulk Actions
    # ----------------------------
    @admin.action(description="Mark selected as Present")
    def mark_present(self, request, queryset):
        status = AttendanceStatus.objects.filter(code="P", is_active=True).first()
        if status:
            queryset.update(status=status)

    @admin.action(description="Mark selected as Absent")
    def mark_absent(self, request, queryset):
        status = AttendanceStatus.objects.filter(code="A", is_active=True).first()
        if status:
            queryset.update(status=status)

    # ----------------------------
    # Permissions
    # ----------------------------
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
