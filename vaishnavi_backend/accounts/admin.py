# admin.py
from django.contrib import admin
from django import forms
from django.utils import timezone
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.utils.html import format_html

from .models import CustomUser, UserHierarchy, PricingModel, UserPlan, StaffForHire


# -------------------------------------------------------------------
#                         USER FORMS
# -------------------------------------------------------------------
class CustomUserCreationForm(forms.ModelForm):
    """Form for creating new users in admin with password confirmation."""

    password1 = forms.CharField(
        label="Password", 
        widget=forms.PasswordInput(attrs={
            'class': 'vTextField',
            'placeholder': 'Enter password'
        })
    )
    password2 = forms.CharField(
        label="Confirm Password", 
        widget=forms.PasswordInput(attrs={
            'class': 'vTextField',
            'placeholder': 'Confirm password'
        })
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        # Add SimpleUI styling to form fields
        for field_name, field in self.fields.items():
            if hasattr(field, 'widget') and hasattr(field.widget, 'attrs'):
                field.widget.attrs.update({'class': 'vTextField'})

    class Meta:
        model = CustomUser
        fields = (
            "profile_pic",
            "email",
            "mobile_number",
            "first_name",
            "middle_name",
            "last_name",
            "gender",
            "user_type",
            "city",
            "category",
        )

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and CustomUser.objects.filter(email=email).exists():
            raise ValidationError("A user with this email already exists.")
        return email

    def clean_mobile_number(self):
        mobile_number = self.cleaned_data.get('mobile_number')
        if mobile_number and CustomUser.objects.filter(mobile_number=mobile_number).exists():
            raise ValidationError("A user with this mobile number already exists.")
        return mobile_number

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords do not match.")
            
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])

        if self.request and hasattr(self.request, 'user'):
            user.created_by = self.request.user

        if commit:
            user.save()
        return user


class CustomUserChangeForm(forms.ModelForm):
    """Form for updating users in admin. Password is read-only hash."""

    password = ReadOnlyPasswordHashField(
        help_text="Raw passwords are not stored, so there is no way to see this user's password. "
                  "You can change the password using <a href=\"../password/\">this form</a>."
    )

    class Meta:
        model = CustomUser
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add SimpleUI styling to form fields
        for field_name, field in self.fields.items():
            if hasattr(field, 'widget') and hasattr(field.widget, 'attrs'):
                if field_name == 'password':
                    field.widget.attrs.update({'class': 'vTextField', 'readonly': True})
                else:
                    field.widget.attrs.update({'class': 'vTextField'})

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email and CustomUser.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError("A user with this email already exists.")
        return email

    def clean_mobile_number(self):
        mobile_number = self.cleaned_data.get('mobile_number')
        if mobile_number and CustomUser.objects.filter(mobile_number=mobile_number).exclude(pk=self.instance.pk).exists():
            raise ValidationError("A user with this mobile number already exists.")
        return mobile_number


# -------------------------------------------------------------------
#                         INLINE ADMIN: USER PLAN
# -------------------------------------------------------------------
class UserPlanInline(admin.TabularInline):
    model = UserPlan
    extra = 0
    readonly_fields = ("end_date", "is_active", "days_remaining")
    fields = ("plan", "start_date", "end_date", "is_active", "days_remaining")
    show_change_link = True
    classes = ('collapse',)  # SimpleUI: Make inline collapsible

    def days_remaining(self, obj):
        if obj.end_date and obj.is_active:
            today = timezone.localtime().date()
            remaining = (obj.end_date - today).days
            return max(0, remaining)
        return 0
    days_remaining.short_description = "Days Remaining"


# -------------------------------------------------------------------
#                         USER ADMIN
# -------------------------------------------------------------------
@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    """Custom admin for the main user model."""

    form = CustomUserChangeForm
    add_form = CustomUserCreationForm

    # SimpleUI: Customize list display
    list_display = (
        "id",
        "email",
        "first_name",
        "last_name",
        "mobile_number",
        "user_type",
        "city",
        "is_active",
        "is_staff",
        "created_by",
        "date_joined"
    )
    list_filter = ("user_type", "is_active", "is_staff", "city", "date_joined")
    search_fields = (
        "email",
        "first_name",
        "last_name",
        "mobile_number",
        "employee_id",
    )
    ordering = ("-date_joined",)
    readonly_fields = ("date_joined", "last_login")
    list_select_related = ("created_by",)
    
    # SimpleUI: Enable data export
    list_per_page = 20
    show_full_result_count = True
    
    # SimpleUI: Custom actions appearance
    actions = ["activate_users", "deactivate_users"]
    actions_on_top = True
    actions_on_bottom = True

    fieldsets = (
        (None, {
            "fields": ("email","mobile_number", "password"),
            "classes": ("wide",)  # SimpleUI: wide fieldset
        }),
        (
            "Personal Details",
            {
                "fields": (
                    "profile_pic",
                    "first_name",
                    "middle_name",
                    "last_name",
                    "gender",
                    "emergency_contact",
                    "address",
                    "city",
                    "category",
                ),
                "classes": ("collapse",)  # SimpleUI: collapsible section
            },
        ),
        (
            "user_type & Permissions",
            {
                "fields": (
                    "user_type",
                    "created_by",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
                "classes": ("wide",)
            },
        ),
        (
            "Additional Data",
            {
                "fields": (
                    "employee_id",
                    "skills",
                    "order_types",
                    "target_percent",
                    "qc_required",
                ),
                "classes": ("collapse",)
            },
        ),
        ("Important Dates", {
            "fields": ("date_joined", "last_login", "last_working_day"),
            "classes": ("collapse",)
        }),
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
                    "middle_name",
                    "last_name",
                    "gender",
                    "city",
                    "user_type",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    inlines = (UserPlanInline,)

    def get_form(self, request, obj=None, **kwargs):
        """Pass request to the form for created_by field."""
        form = super().get_form(request, obj, **kwargs)
        if not obj:  # Only for add form
            form.request = request
        return form

    def save_model(self, request, obj, form, change):
        """Ensure essential fields are filled and user is saved."""
        if not obj.email:
            raise ValidationError("Email is required.")
        if not obj.mobile_number:
            raise ValidationError("Mobile number is required.")
        
        if not change and not obj.created_by:
            obj.created_by = request.user
            
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        """Optimize queryset with select_related."""
        return super().get_queryset(request).select_related("created_by")

    def activate_users(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(
            request, 
            f"Successfully activated {count} user(s).", 
            messages.SUCCESS
        )
    activate_users.short_description = "Activate selected users"

    def deactivate_users(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(
            request, 
            f"Successfully deactivated {count} user(s).", 
            messages.SUCCESS
        )
    deactivate_users.short_description = "Deactivate selected users"

    # SimpleUI: Customize display methods for better UI
    def get_user_type_color(self, obj):
        colors = {
            'ADMIN': 'red',
            'MANAGER': 'orange',
            'USER': 'blue',
            'STAFF': 'green',
        }
        return colors.get(obj.user_type, 'gray')
    get_user_type_color.short_description = 'Type Color'


# -------------------------------------------------------------------
#                         USER HIERARCHY ADMIN
# -------------------------------------------------------------------
@admin.register(UserHierarchy)
class UserHierarchyAdmin(admin.ModelAdmin):
    """Manage reporting relationships between users."""

    # SimpleUI: Custom list display
    list_display = ("id", "user", "parent", "owner", "level", "band", "department", "is_active_display")
    list_filter = ("owner", "level", "band", "department")
    search_fields = (
        "user__email",
        "user__first_name",
        "user__last_name",
        "owner__email",
        "parent__email",
    )
    raw_id_fields = ("user", "owner", "parent")
    readonly_fields = ("level",)
    list_select_related = ("user", "parent", "owner")
    
    # SimpleUI settings
    list_per_page = 20
    list_editable = ("band", "department")  # SimpleUI: Enable inline editing
    show_save_as_new = True

    fieldsets = (
        (None, {
            "fields": ("user", "parent", "owner"),
            "classes": ("wide",)
        }),
        ("Hierarchy Details", {
            "fields": ("level", "band", "department"),
            "classes": ("wide",)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "parent", "owner")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ["user", "parent", "owner"]:
            kwargs["queryset"] = CustomUser.objects.filter(is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # SimpleUI: Custom method for display
    def is_active_display(self, obj):
        if obj.user and obj.user.is_active:
            return '✅ Active'
        return '❌ Inactive'
    is_active_display.short_description = 'User Status'
    is_active_display.admin_order_field = 'user__is_active'


# -------------------------------------------------------------------
#                         PRICING MODEL ADMIN
# -------------------------------------------------------------------
@admin.register(PricingModel)
class PricingModelAdmin(admin.ModelAdmin):
    """Manage pricing plans and limits."""

    # SimpleUI: Enhanced list display
    list_display = (
        "name",
        "plan_type",
        "price_display",
        "duration_days",
        "is_active",
        "created_by",
        "created_at",
    )
    list_filter = ("plan_type", "is_active", "created_by", "created_at")
    search_fields = ("name", "description", "created_by__email")
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("created_by",)
    
    # SimpleUI settings
    list_per_page = 20
    list_editable = ("is_active",)
    save_as = True  # SimpleUI: Enable save as new
    
    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "name",
                    "description",
                    "plan_type",
                    "price",
                    "duration_days",
                    "is_active",
                ),
                "classes": ("wide",)
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",)
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by:
            obj.created_by = request.user
            
        try:
            obj.clean()
            super().save_model(request, obj, form, change)
        except ValidationError as e:
            self.message_user(request, f"Validation error: {e}", messages.ERROR)
            raise

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("created_by",)
        return self.readonly_fields

    # SimpleUI: Custom display methods
    def price_display(self, obj):
        return f"₹{obj.price}"
    price_display.short_description = 'Price'
    price_display.admin_order_field = 'price'

    def is_active_badge(self, obj):
        if obj.is_active:
            return '🟢 Active'
        return '🔴 Inactive'
    is_active_badge.short_description = 'Status'
    is_active_badge.admin_order_field = 'is_active'


# -------------------------------------------------------------------
#                         USER PLAN ADMIN
# -------------------------------------------------------------------
@admin.register(UserPlan)
class UserPlanAdmin(admin.ModelAdmin):
    """Manage active and expired user plans."""

    # SimpleUI: Enhanced list display
    list_display = (
        "user",
        "plan",
        "start_date",
        "end_date",
        "days_remaining_badge",
        "status_badge",
        "plan_type_display",
    )
    list_filter = ("plan__plan_type", "is_active", "plan", "start_date")
    search_fields = ("user__email", "user__first_name", "user__last_name", "plan__name")
    readonly_fields = ("end_date", "is_active", "days_remaining", "plan_type_display")
    actions = ["expire_plans", "activate_plans", "extend_plans"]
    raw_id_fields = ("user", "plan")
    list_select_related = ("user", "plan")
    
    # SimpleUI settings
    list_per_page = 20
    date_hierarchy = 'start_date'  # SimpleUI: Add date hierarchy
    show_save_as_new = True

    fieldsets = (
        (None, {
            "fields": ("user", "plan", "is_active"),
            "classes": ("wide",)
        }),
        ("Date Information", {
            "fields": ("start_date", "end_date", "days_remaining"),
            "classes": ("wide",)
        }),
        ("Plan Details", {
            "fields": ("plan_type_display",),
            "classes": ("collapse",)
        }),
    )

    def days_remaining(self, obj):
        if obj.end_date and obj.is_active:
            today = timezone.localtime().date()
            remaining = (obj.end_date - today).days
            return max(0, remaining)
        return 0
    days_remaining.short_description = "Days Remaining"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "plan")

    def save_model(self, request, obj, form, change):
        try:
            obj.clean()
            super().save_model(request, obj, form, change)
        except ValidationError as e:
            self.message_user(request, f"Validation error: {e}", messages.ERROR)
            raise

    # SimpleUI: Custom actions
    def expire_plans(self, request, queryset):
        count = 0
        for user_plan in queryset:
            if user_plan.is_active:
                user_plan.is_active = False
                user_plan.end_date = timezone.localtime().date()
                user_plan.save()
                count += 1
        
        self.message_user(
            request, 
            f"Successfully expired {count} plan(s).", 
            messages.SUCCESS
        )
    expire_plans.short_description = "🔄 Expire selected plans"

    def activate_plans(self, request, queryset):
        count = 0
        today = timezone.localtime().date()
        
        for user_plan in queryset:
            if not user_plan.is_active:
                user_plan.is_active = True
                
                if (user_plan.plan.plan_type == "SUBSCRIPTION" and 
                    (not user_plan.end_date or user_plan.end_date < today)):
                    user_plan.end_date = today + timezone.timedelta(
                        days=user_plan.plan.duration_days
                    )
                
                user_plan.save()
                count += 1
        
        self.message_user(
            request, 
            f"Successfully activated {count} plan(s).", 
            messages.SUCCESS
        )
    activate_plans.short_description = "✅ Activate selected plans"

    def extend_plans(self, request, queryset):
        """SimpleUI: Custom action to extend plans by 30 days"""
        count = 0
        for user_plan in queryset:
            if user_plan.is_active and user_plan.end_date:
                user_plan.end_date += timezone.timedelta(days=30)
                user_plan.save()
                count += 1
        
        self.message_user(
            request,
            f"Successfully extended {count} plan(s) by 30 days.",
            messages.SUCCESS
        )
    extend_plans.short_description = "📅 Extend plans by 30 days"

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_active:
            return self.readonly_fields + ("start_date",)
        return self.readonly_fields

    # SimpleUI: Custom display methods with badges
    def days_remaining_badge(self, obj):
        days = self.days_remaining(obj)
        if days == 0:
            return f"🔴 {days}d"
        elif days <= 7:
            return f"🟡 {days}d"
        else:
            return f"🟢 {days}d"
    days_remaining_badge.short_description = 'Days Left'
    days_remaining_badge.admin_order_field = 'end_date'

    def status_badge(self, obj):
        if obj.is_active:
            return '🟢 Active'
        return '🔴 Expired'
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'is_active'

    def plan_type_display(self, obj):
        plan_types = {
            'SUBSCRIPTION': '📅 Subscription',
            'ONE_TIME': '💰 One Time',
            'FREE': '🆓 Free',
        }
        return plan_types.get(obj.plan.plan_type, obj.plan.plan_type)
    plan_type_display.short_description = 'Plan Type'

@admin.register(StaffForHire)
class StaffForHireAdmin(admin.ModelAdmin):
    list_display = [
        "id", "staff_name", "vendor_name", "skills_display",
        "languages_display", "available_from", "services_display",
        "price", "is_active",  "is_available", "created_at",
    ]
    list_filter = ["is_active", "available_from",'is_available']
    search_fields = ["staff_name", "vendor_name"]
    readonly_fields = ["created_by", "created_at", "updated_at"]

    @admin.display(description="Skills")
    def skills_display(self, obj):
        return ", ".join(obj.skill) if obj.skill else "—"

    @admin.display(description="Languages")
    def languages_display(self, obj):
        return ", ".join(obj.language) if obj.language else "—"

    @admin.display(description="Available For")
    def services_display(self, obj):
        return ", ".join(obj.available_for) if obj.available_for else "—"