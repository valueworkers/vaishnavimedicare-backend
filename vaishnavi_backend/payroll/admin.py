from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Q
from .models import SalaryStructure, SalaryReport,SalaryTransaction


admin.site.register(SalaryTransaction)
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
            return queryset.filter(effective_from__month=self.value())
        return queryset


class YearFilter(admin.SimpleListFilter):
    title = "Year"
    parameter_name = "year"

    def lookups(self, request, model_admin):
        years = SalaryStructure.objects.values_list(
            "effective_from__year", flat=True
        ).distinct()
        return [(y, y) for y in years if y]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(effective_from__year=self.value())
        return queryset


class UserFilter(admin.SimpleListFilter):
    title = "User"
    parameter_name = "user"

    def lookups(self, request, model_admin):
        users = (
            SalaryStructure.objects.values_list("user__id", "user__first_name", "user__last_name")
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

@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "salary_type",
        "change_type",
        "amount",
        "final_salary",
        "effective_from",
        "created_at",
    )

    list_filter = (
        MonthFilter,
        YearFilter,
        UserFilter,
        "salary_type",
        "change_type",
        "effective_from",
        "created_at",
    )

    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    date_hierarchy = "effective_from"

    readonly_fields = (
        "final_salary",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        ("Employee Information", {
            "fields": ("user",)
        }),
        ("Salary Details", {
            "fields": (
                "salary_type",
                "change_type",
                "amount",
                "final_salary",
            )
        }),
        ("Effective Period", {
            "fields": ("effective_from",)
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("user")
    from django.contrib import admin

@admin.register(SalaryReport)
class SalaryReportAdmin(admin.ModelAdmin):
    """
    Admin configuration for SalaryReport
    Read-only financial audit record
    """

    # -------------------- List View --------------------
    list_display = (
        "user",
        "start_date",
        "end_date",
        "total_payable_amount",
        "paid_amount",
        "remaining_payment",
        "advance_amount",
        "final_salary",
        "created_at",
    )

    list_filter = (
        "start_date",
        "end_date",
        "created_at",
    )

    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
    )

    ordering = ("-start_date",)

    # -------------------- Read-only Fields --------------------
    readonly_fields = (
        "remaining_payment",
        "created_at",
        "updated_at",
        "final_salary",
        "advance_amount",
    )

    # -------------------- Fieldsets --------------------
    fieldsets = (
        ("Employee", {
            "fields": ("user",),
        }),
        ("Salary Period", {
            "fields": (
                "start_date",
                "end_date",
            ),
        }),
        ("Salary Calculation", {
            "fields": (
                "daily_rate",
                "total_payable_amount",
                "paid_amount",
                "remaining_payment",
                "final_salary",
                "advance_amount",
            ),
        }),
        ("Audit", {
            "fields": (
                "created_at",
                "updated_at",
            ),
        }),
    )

    # -------------------- Admin Protections --------------------
    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
