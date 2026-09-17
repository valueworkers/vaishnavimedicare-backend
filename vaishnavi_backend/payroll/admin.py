from django.contrib import admin

from .models import (
    SalaryStructure,
    SalaryReport,
    SalaryTransaction,
)


# ============================================================
# Salary Transaction
# ============================================================

@admin.register(SalaryTransaction)
class SalaryTransactionAdmin(admin.ModelAdmin):
    """
    Uses only fields that actually exist on SalaryTransaction.
    Add fields here later after checking the model definition.
    """

    list_display = (
        "__str__",
    )


# ============================================================
# Custom Filters
# ============================================================

class MonthFilter(admin.SimpleListFilter):
    title = "Month"
    parameter_name = "month"

    def lookups(self, request, model_admin):
        return [
            (str(i), str(i))
            for i in range(1, 13)
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(
                effective_from__month=self.value()
            )
        return queryset


class YearFilter(admin.SimpleListFilter):
    title = "Year"
    parameter_name = "year"

    def lookups(self, request, model_admin):
        years = (
            SalaryStructure.objects
            .values_list(
                "effective_from__year",
                flat=True,
            )
            .distinct()
            .order_by("-effective_from__year")
        )

        return [
            (str(year), str(year))
            for year in years
            if year
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(
                effective_from__year=self.value()
            )

        return queryset


class UserFilter(admin.SimpleListFilter):
    title = "User"
    parameter_name = "user"

    def lookups(self, request, model_admin):
        users = (
            SalaryStructure.objects
            .values_list(
                "user__id",
                "user__first_name",
                "user__last_name",
            )
            .distinct()
            .order_by(
                "user__first_name",
                "user__last_name",
            )
        )

        return [
            (
                user_id,
                f"{first_name} {last_name}".strip(),
            )
            for user_id, first_name, last_name in users
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(
                user__id=self.value()
            )

        return queryset


# ============================================================
# Salary Structure
# ============================================================

@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "change_type",
        "amount",
        "pf_amount",
        "esi_amount",
        "final_salary",
        "effective_from",
    )

    list_filter = (
        MonthFilter,
        YearFilter,
        UserFilter,
        "change_type",
        "effective_from",
    )

    search_fields = (
        "user__first_name",
        "user__last_name",
        "=user__email",
    )

    date_hierarchy = "effective_from"

    ordering = (
        "-effective_from",
        "-pk",
    )

    # Calculated fields are read-only.
    # PF and ESI remain manually editable.
    readonly_fields = (
        "final_salary",
    )

    fieldsets = (
        (
            "Employee Information",
            {
                "fields": (
                    "user",
                ),
            },
        ),
        (
            "Salary Details",
            {
                "fields": (
                    "change_type",
                    "amount",
                    "pf_amount",
                    "esi_amount",
                    "final_salary",
                ),
            },
        ),
        (
            "Effective Period",
            {
                "fields": (
                    "effective_from",
                ),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user")
        )


# ============================================================
# Salary Report
# ============================================================

@admin.register(SalaryReport)
class SalaryReportAdmin(admin.ModelAdmin):
    """
    SalaryReport is treated as a read-only financial record.
    """

    list_display = (
        "user",
        "start_date",
        "end_date",
        "total_payable_amount",
        "paid_amount",
        "remaining_payment",
        "advance_amount",
        "final_salary",
    )

    list_filter = (
        "start_date",
        "end_date",
    )

    search_fields = (
        "=user__email",
        "user__first_name",
        "user__last_name",
    )

    ordering = (
        "-start_date",
    )

    readonly_fields = (
        "user",
        "start_date",
        "end_date",
        "daily_rate",
        "total_payable_amount",
        "paid_amount",
        "remaining_payment",
        "final_salary",
        "advance_amount",
    )

    fieldsets = (
        (
            "Employee",
            {
                "fields": (
                    "user",
                ),
            },
        ),
        (
            "Salary Period",
            {
                "fields": (
                    "start_date",
                    "end_date",
                ),
            },
        ),
        (
            "Salary Calculation",
            {
                "fields": (
                    "daily_rate",
                    "total_payable_amount",
                    "paid_amount",
                    "remaining_payment",
                    "final_salary",
                    "advance_amount",
                ),
            },
        ),
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
