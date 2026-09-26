from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import (
    CustomUser,
    EmployeeProfile,
    PricingModel,
    ShiftSchedule,
    StaffForHire,
    UserDocument,
    UserDocumentFile,
    UserHierarchy,
    UserPlan,
)


# =====================================================================
#  CUSTOM USER
# =====================================================================
@admin.register(CustomUser)
class CustomUserAdmin(DjangoUserAdmin):
    """
    Subclasses Django's UserAdmin for the familiar change-password /
    permissions UI, but overrides every fieldset — CustomUser has no
    `username`, and uses `email` as USERNAME_FIELD.
    """

    model = CustomUser
    ordering = ["id"]

    list_display = [
        "id",
        "get_emp_name",
        "email",
        "mobile_number",
        "get_emp_role",
        "city",
        "is_active",
        "is_deleted",
    ]
    list_filter = ["user_type", "is_active", "is_deleted", "gender", "city"]

    # Required so this model can be a target of autocomplete_fields elsewhere.
    search_fields = [
        "first_name",
        "last_name",
        "email",
        "mobile_number",
        "employee_profile__employee_id",
    ]
    autocomplete_fields = ["created_by"]

    fieldsets = (
        (None, {"fields": ("email", "mobile_number", "password")}),
        (
            "Personal info",
            {
                "fields": (
                    "profile_pic",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "age",
                    "permanent_address",
                    "current_address",
                    "gender",
                    "alternate_phone_number",
                    "emergency_contact_name",
                    "emergency_contact_number",
                    "city",
                )
            },
        ),
        (
            "Role & status",
            {
                "fields": (
                    "user_type",
                    "date_joined",
                    "is_active",
                    "is_deleted",
                    "created_by",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "mobile_number",
                    "first_name",
                    "last_name",
                    "user_type",
                    "gender",
                    "permanent_address",
                    "current_address",
                    "city",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    readonly_fields = ["last_login"]

    @admin.display(description="Emp Name")
    def get_emp_name(self, obj):
        return obj.get_full_name()

    @admin.display(description="Emp Role")
    def get_emp_role(self, obj):
        return obj.get_user_type_display()


# =====================================================================
#  SHIFT SCHEDULE
# =====================================================================
@admin.register(ShiftSchedule)
class ShiftScheduleAdmin(admin.ModelAdmin):
    list_display = ["name", "start_time", "end_time", "is_overnight", "is_active"]
    list_filter = ["is_overnight", "is_active"]
    search_fields = ["name"]


# =====================================================================
#  EMPLOYEE PROFILE
# =====================================================================
@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = [
        "employee_id",
        "user",
        "designation",
        "category",
        "grade",
        "department",
        "shift",
        "termination_reason",
        "termination_type",
        "user_date_joined",
        "last_working_day",
    ]
    list_filter = [
        "category",
        "department",
        "termination_reason",
        "termination_type",
        "rehired_status",
        "pf_applicable",
        "esi_applicable",
        "qc_required",
        "shift",
    ]
    search_fields = [
        "employee_id",
        "designation",
        "cost_center",
        "user__first_name",
        "user__last_name",
        "user__email",
        "pf_number",
        "uan_number",
        "esi_number",
    ]
    autocomplete_fields = ["user", "shift"]
    fieldsets = (
        (None, {"fields": ("user", "employee_id", "category", "designation", )}),
        ("Org placement", {"fields": ("department", "cost_center", "grade")}),
        ("Employment dates", {"fields": ("user_date_joined", "last_working_day", "rehired_status","termination_reason","termination_type")}),
        ("Shift", {"fields": ("shift", "shift_effective_from")}),
        ("Vendor", {"fields": ("vendor_name", "vendor_phone")}),
        ("Work profile", {"fields": ("order_types", "skills", "target_percent", "qc_required")}),
        ("Provident Fund", {"fields": ("pf_applicable", "pf_number", "uan_number")}),
        ("ESI", {"fields": ("esi_applicable", "esi_number", "esi_dispensary")}),
        
    )
    readonly_fields =["user_date_joined"]

    @admin.display(description="Date Joined", ordering="user__date_joined")
    def user_date_joined(self, obj):
        return obj.user.date_joined

# =====================================================================
#  HIERARCHY
# =====================================================================
@admin.register(UserHierarchy)
class UserHierarchyAdmin(admin.ModelAdmin):
    list_display = ["user", "parent", "owner", "level", "department", "band"]
    list_filter = ["level", "department"]
    search_fields = [
        "user__first_name",
        "user__last_name",
        "user__email",
        "parent__first_name",
        "parent__last_name",
        "owner__first_name",
        "owner__last_name",
    ]
    autocomplete_fields = ["user", "parent", "owner"]
    readonly_fields = ["level"]


# =====================================================================
#  DOCUMENTS
# =====================================================================
class UserDocumentFileInline(admin.TabularInline):
    model = UserDocumentFile
    extra = 0


@admin.register(UserDocument)
class UserDocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "uploaded_by", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["title", "user__first_name", "user__last_name", "user__email"]
    autocomplete_fields = ["user", "uploaded_by"]
    inlines = [UserDocumentFileInline]


# =====================================================================
#  PRICING
# =====================================================================
@admin.register(PricingModel)
class PricingModelAdmin(admin.ModelAdmin):
    list_display = ["name", "plan_type", "price", "duration_days", "is_active"]
    list_filter = ["plan_type", "is_active"]
    search_fields = ["name"]
    autocomplete_fields = ["created_by"]


@admin.register(UserPlan)
class UserPlanAdmin(admin.ModelAdmin):
    list_display = ["user", "plan", "start_date", "end_date", "is_active"]
    list_filter = ["is_active", "plan"]
    search_fields = ["user__first_name", "user__last_name", "user__email"]
    autocomplete_fields = ["user", "plan"]


# =====================================================================
#  STAFF FOR HIRE (3rd party)
# =====================================================================
@admin.register(StaffForHire)
class StaffForHireAdmin(admin.ModelAdmin):
    list_display = [
        "staff_name",
        "vendor_name",
        "email",
        "mobile_number",
        "price",
        "available_from",
        "is_active",
        "is_available",
    ]
    list_filter = ["is_active", "is_available", "vendor_name"]
    search_fields = ["staff_name", "vendor_name", "email", "mobile_number"]
    autocomplete_fields = ["created_by"]