from django.db import models, transaction
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.db.models import Q
from datetime import timedelta

# ------------------------USER MANAGER-------------------------------
class CustomUserManager(BaseUserManager):
    """Custom manager for CustomUser model with user_type-based filters."""

    def create_user(self, mobile_number,email=None, password=None, **extra_fields):
        if not mobile_number:
            raise ValueError("Mobile number must be provided.")

        email = self.normalize_email(email) if email else None
        user = self.model(email=email, mobile_number=mobile_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, mobile_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("user_type", CustomUser.UserTypes.MASTER_ADMIN)
        if not email:
            raise ValueError("Superuser must have an email.")
        return self.create_user(mobile_number,email, password, **extra_fields)

    # ---------------- Basic Filters ----------------
    def owners(self):
        return self.filter(user_type=CustomUser.UserTypes.VSRE_OWNER)

    def employees(self):
            return self.filter(
                user_type__in=[
                    CustomUser.UserTypes.VSRE_MANAGER,
                    CustomUser.UserTypes.LINE_MANAGER,
                    CustomUser.UserTypes.VSRE_STAFF,
                ]
            )
    def managers(self):
        return self.filter(
            user_type__in=[
                CustomUser.UserTypes.VSRE_MANAGER,
                CustomUser.UserTypes.LINE_MANAGER,
            ]
        )

    def staff(self):
        return self.filter(user_type=CustomUser.UserTypes.VSRE_STAFF)

    def customers(self):
        return self.filter(user_type=CustomUser.UserTypes.CUSTOMER)
        
    # ---------------- Hierarchy Queries ----------------
    def _get_user_ids(self, **filters):
        from .models import UserHierarchy
        return UserHierarchy.objects.filter(**filters).values_list("user_id", flat=True)
        
    def get_direct_managers_under_owner(self, owner):
        return self.filter(
            id__in=self._get_user_ids(
                owner=owner,
                level=1,
                user__user_type__in=[
                    CustomUser.UserTypes.VSRE_MANAGER,
                    CustomUser.UserTypes.LINE_MANAGER,
                ],
            )
        )

    def get_all_managers_under_owner(self, owner):
        return self.filter(
            id__in=self._get_user_ids(
                owner=owner,
                user__user_type__in=[
                    CustomUser.UserTypes.VSRE_MANAGER,
                    CustomUser.UserTypes.LINE_MANAGER,
                ],
            )
        )

    def get_managers_under_manager(self, manager):
        return self.filter(
            id__in=self._get_user_ids(
                parent=manager,
                user__user_type__in=[
                    CustomUser.UserTypes.VSRE_MANAGER,
                    CustomUser.UserTypes.LINE_MANAGER,
                ],
            )
        )

    def get_all_under_manager(self, manager):
        from .models import UserHierarchy
        return self.filter(
            id__in=UserHierarchy.objects.filter(
                Q(parent=manager) | Q(parent__hierarchy__parent=manager)
            ).values_list("user_id", flat=True)
        ).exclude(user_type=CustomUser.UserTypes.VSRE_OWNER)

    def get_staff_under_manager(self, manager):
        return self.filter(
            id__in=self._get_user_ids(
                parent=manager,
                user__user_type=CustomUser.UserTypes.VSRE_STAFF,
            )
        )

    def get_staff_under_owner(self, owner):
        return self.filter(
            id__in=self._get_user_ids(
                owner=owner,
                user__user_type=CustomUser.UserTypes.VSRE_STAFF,
            )
        )

    def get_entire_hierarchy_under_owner(self, owner):
        return {
            "owner": owner,
            "level1_managers": self.get_direct_managers_under_owner(owner),
            "all_managers": self.get_all_managers_under_owner(owner),
            "all_staff": self.get_staff_under_owner(owner),
        }

# ------------------------CUSTOM USER-------------------------------
class CustomUser(AbstractBaseUser, PermissionsMixin):
    """Identity, contact details and role. No employment fields."""
 
    class UserTypes(models.TextChoices):
        MASTER_ADMIN = "MASTER_ADMIN", "Master Admin"
        VSRE_OWNER = "VSRE_OWNER", "VSRE Owner"
        VSRE_MANAGER = "VSRE_MANAGER", "VSRE Manager"
        LINE_MANAGER = "LINE_MANAGER", "Line Manager"
        VSRE_STAFF = "VSRE_STAFF", "VSRE Staff"
        CUSTOMER = "CUSTOMER", "Customer"
 
    GENDER_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
        ("N", "Prefer not to say"),
    ]
 
    phone_regex = RegexValidator(
        regex=r"^\d{10}$", message="Phone number must be 10 digits"
    )
 
    profile_pic = models.ImageField(upload_to="profile_photos/", null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    mobile_number = models.CharField(
        max_length=10, unique=True, validators=[phone_regex]
    )
    alternate_phone_number = models.CharField(
        max_length=10, blank=True, null=True, validators=[phone_regex]
    )
    emergency_contact_name = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_number = models.CharField(
        max_length=15, blank=True, null=True, validators=[phone_regex]
    )
 
    first_name = models.CharField(max_length=30, verbose_name="Emp First Name")
    middle_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30, verbose_name="Emp Last Name")
 
    age = models.PositiveIntegerField(blank=True, null=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
 
    user_type = models.CharField(
        max_length=30, choices=UserTypes.choices, verbose_name="Emp Role"
    )

    permanent_address = models.TextField(blank=True, null=True)
    current_address = models.TextField(blank=True, null=True)
    
    city = models.CharField(max_length=100, db_index=True)
 
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
 
    date_joined = models.DateField(blank=True, null=True)
 
    created_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_users",
    )
 
    objects = CustomUserManager()
 
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "mobile_number"]
 
    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["user_type", "is_deleted"]),
        ]
 
    # ---------------- role helpers ----------------
    @property
    def is_owner(self):
        return self.user_type in [self.UserTypes.VSRE_OWNER, self.UserTypes.MASTER_ADMIN]
 
    @property
    def is_manager(self):
        return self.user_type in [
            self.UserTypes.VSRE_MANAGER,
            self.UserTypes.LINE_MANAGER,
        ]
 
    @property
    def is_vsre_staff(self):
        return self.user_type == self.UserTypes.VSRE_STAFF
 
    @property
    def is_customer(self):
        return self.user_type == self.UserTypes.CUSTOMER
 
    @property
    def is_employee(self):
        return self.is_manager or self.is_vsre_staff
 
    # ---------------- convenience ----------------
    @property
    def employee_id(self):
        """Kept so existing callers/templates don't break after the split."""
        profile = getattr(self, "employee_profile", None)
        return profile.employee_id if profile else None
 
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
 
    def soft_delete(self):
        self.is_active = False
        self.is_deleted = True
        self.save(update_fields=["is_active", "is_deleted"])
 
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.user_type})"
 
# ------------------------SHIFT SCHEDULE-----------------------------
class ShiftSchedule(models.Model):
    """
    A reusable duty-timing template (e.g. "Morning", "Night") that
    employees are assigned to. Kept separate from EmployeeProfile so
    the same shift can be shared across many employees and changed
    in one place.
    """
 
    class WeekDay(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"
 
    name = models.CharField(max_length=50, unique=True)  # e.g. "Morning", "Night"
    start_time = models.TimeField()
    end_time = models.TimeField()
    # True when end_time is on the following calendar day (e.g. 22:00 -> 06:00)
    is_overnight = models.BooleanField(default=False)
    grace_minutes = models.PositiveSmallIntegerField(default=0)
    weekly_off_days = models.JSONField(
        default=list, blank=True, help_text="List of WeekDay values, e.g. [5, 6]"
    )
    is_active = models.BooleanField(default=True)
 
    class Meta:
        ordering = ["start_time"]
 
    def clean(self):
        if not self.is_overnight and self.end_time <= self.start_time:
            raise ValidationError(
                {"end_time": "End time must be after start time, or mark the shift as overnight."}
            )
 
    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M})"
 
# ------------------------EMPLOYEE PROFILE-----------------------------
class EmployeeProfile(models.Model):
    """Employment record for managers and staff."""

    class TerminationType(models.TextChoices):
        VOLUNTARY = "VOLUNTARY", "Voluntary"       # resignation, retirement
        INVOLUNTARY = "INVOLUNTARY", "Involuntary"  # dismissal, layoff, contract end

    class EmployeeCategory(models.TextChoices):
        REGULAR = "REGULAR", "Regular"
        FULLTIME = "FULLTIME", "Fulltime"
        PARTTIME = "PARTTIME", "Parttime"
        VIRTUAL = "VIRTUAL", "Virtual"
        PPO = "PPO", "PPO"
        VENDOR = "VENDOR", "Vendor"
 
    class RehiredStatus(models.TextChoices):
        YES = "YES", "Yes"
        NO = "NO", "No"
 
    uan_regex = RegexValidator(
        regex=r"^\d{12}$", message="UAN must be exactly 12 digits."
    )
    esi_regex = RegexValidator(
        regex=r"^\d{10,17}$", message="ESI number must be 10 to 17 digits."
    )
 
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="employee_profile",
    )

    termination_type = models.CharField(
        max_length=20, choices=TerminationType.choices, blank=True, null=True
    )
    termination_reason = models.CharField(max_length=255, blank=True, null=True)
 
    employee_id = models.CharField(max_length=20, blank=True, null=True)
    category = models.CharField(
        max_length=50, choices=EmployeeCategory.choices, null=True, blank=True
    )
    designation = models.CharField(
        max_length=100, blank=True, null=True, help_text="Job title, e.g. 'Senior Technician'."
    )

    grade = models.CharField(max_length=20, blank=True, null=True)
    cost_center = models.CharField(max_length=50, blank=True, null=True)
    department = models.CharField(
        max_length=50, blank=True, null=True,
        help_text="Employee's HR department. Distinct from UserHierarchy.department, "
                   "which reflects org reporting structure.",
    )
    
    rehired_status = models.CharField(
        max_length=3, choices=RehiredStatus.choices, default=RehiredStatus.NO
    )
 
    # vendor-sourced employees only
    vendor_name = models.CharField(max_length=120, blank=True, null=True)
    vendor_phone = models.CharField(max_length=15, blank=True, null=True)
 
    last_working_day = models.DateField(blank=True, null=True, verbose_name="LWD")
 
    order_types = models.JSONField(blank=True, null=True)
    skills = models.JSONField(blank=True, null=True)
    target_percent = models.FloatField(blank=True, null=True)
    qc_required = models.BooleanField(default=False)
 
    # ---------------- statutory: Provident Fund ----------------
    pf_applicable = models.BooleanField(default=False)
    pf_number = models.CharField(max_length=30, blank=True, null=True)
    uan_number = models.CharField(
        max_length=12, blank=True, null=True, validators=[uan_regex],
        help_text="12-digit Universal Account Number",
    )
 
    # ---------------- statutory: Employee State Insurance ----------------
    esi_applicable = models.BooleanField(default=False)
    esi_number = models.CharField(
        max_length=17, blank=True, null=True, validators=[esi_regex]
    )
    esi_dispensary = models.CharField(max_length=120, blank=True, null=True)
 
    # ---------------- duty timing / shift ----------------
    shift = models.ForeignKey(
        ShiftSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    shift_effective_from = models.DateField(
        blank=True, null=True, help_text="Date this employee started on `shift`."
    )
 
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ["user_id"]
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["employee_id"]),
            models.Index(fields=["pf_number"]),
            models.Index(fields=["esi_number"]),
        ]
 
    def clean(self):
        if self.category != self.EmployeeCategory.VENDOR and (
            self.vendor_name or self.vendor_phone
        ):
            raise ValidationError(
                {"vendor_name": "Vendor details apply only to the VENDOR category."}
            )
        if self.pf_applicable and not (self.pf_number or self.uan_number):
            raise ValidationError(
                {"pf_number": "PF number or UAN is required when PF is applicable."}
            )
        if self.esi_applicable and not self.esi_number:
            raise ValidationError(
                {"esi_number": "ESI number is required when ESI is applicable."}
            )

        # termination_type is the source of truth for "terminated or not"
        if self.termination_type and not self.last_working_day:
            raise ValidationError(
                {"last_working_day": "LWD is required when a termination type is set."}
            )
        if self.last_working_day and not self.termination_type:
            raise ValidationError(
                {"termination_type": "Termination type is required when LWD is set."}
            )
        if self.termination_reason and not self.termination_type:
            raise ValidationError(
                {"termination_reason": "Termination reason requires a termination type."}
            )

        if (
            self.user.date_joined
            and self.last_working_day
            and self.last_working_day < self.user.date_joined
        ):
            raise ValidationError(
                {"last_working_day": "Last working day cannot precede the joining date."}
            )

    @property
    def is_currently_employed(self):
        return not self.termination_type

    @transaction.atomic
    def terminate(
        self,
        termination_type,
        reason=None,
        last_working_day=None
    ):
        """
        Mark this employee as terminated.

        termination_type: EmployeeProfile.TerminationType.VOLUNTARY / INVOLUNTARY
        reason: optional free text / choice, e.g. "Resignation", "Layoff"
        last_working_day: defaults to today if not given
        """
        if self.termination_type:
            raise ValidationError({"terminate":"Employee is already marked as terminated."})

        self.termination_type = termination_type
        self.termination_reason = reason
        self.last_working_day = last_working_day or timezone.now().date()
        self.user.is_deleted = True 

        self.full_clean()
        self.save(update_fields=[
            "termination_type",
            "termination_reason",
            "last_working_day",
            "updated_at",
        ])

        self.user.is_active = False
        self.user.is_deleted = True
        self.user.save(update_fields=["is_active","is_deleted"])

        return self

    @transaction.atomic
    def termination_revoke(self):
        """
        Reverse a termination — e.g. rehire, or a termination entered in error.
        """
        if not self.termination_type:
            raise ValidationError({"termination_revoke":"Employee is not currently terminated."})

        self.termination_type = None
        self.termination_reason = None
        self.last_working_day = None

        self.full_clean()
        self.save(update_fields=[
            "termination_type",
            "termination_reason",
            "last_working_day",
            "updated_at",
        ])

    
        self.user.is_active = True
        self.user.is_deleted = False
        self.user.save(using=self.user._state.db) if False else None
        self.user.save(update_fields=["is_active","is_deleted"])

        return self
    
    def __str__(self):
        return f"{self.employee_id or self.user_id} — {self.user.get_full_name()}"
    
# ------------------------USER DOCUMENTS-----------------------------
class UserDocument(models.Model):
    """
    Acts as a document group or folder for a specific staff member or manager.
    """
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="documents"
    )
    title = models.CharField(max_length=255, blank=True, null=True)
    uploaded_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_user_documents"
    )
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.title}"

class UserDocumentFile(models.Model):
    """
    Stores the actual files related to a specific UserDocument entry.
    """
    document = models.ForeignKey(
        UserDocument,
        on_delete=models.CASCADE,
        related_name="files"
    )
    file = models.FileField(upload_to="staff_documents/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document.title} - {self.file.name}"
    
# ------------------------USER HIERARCHY-----------------------------
class UserHierarchy(models.Model):
    """Defines the organizational hierarchy between users."""

    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="hierarchy",
        help_text="User associated with this hierarchy record.",
    )
    parent = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subordinates",
        help_text="Immediate supervisor (owner or manager).",
    )
    owner = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="organization_users",
        null=True,
        blank=True,
        limit_choices_to={"user_type": "VSRE_OWNER"},
        help_text="Top-level owner for this user hierarchy.",
    )

    department = models.CharField(max_length=50, null=True, blank=True)
    band = models.CharField(max_length=20, blank=True, null=True)
    level = models.PositiveIntegerField(default=0, help_text="Hierarchy depth (Owner=0, Manager=1, etc.)")
    
    
    class Meta:
        verbose_name = "User Hierarchy"
        verbose_name_plural = "User Hierarchies"

    def __str__(self):
        # build parent and child display
        if self.parent and hasattr(self.parent, 'hierarchy'):
            parent_level = self.parent.hierarchy.level
            parent_label = f"{self.parent} (Level {parent_level})"
        else:
            parent_label = "No Parent"

        user_label = f"{self.user} (Level {self.level})"
        return f"{parent_label} → {user_label}"

    def save(self, *args, **kwargs):
        """Automatically compute and update hierarchy level before saving."""
        if self.parent and hasattr(self.parent, 'hierarchy'):
            self.level = self.parent.hierarchy.level + 1
        else:
            self.level = 0  # top-level (Owner)
        super().save(*args, **kwargs)

# ------------------------PRICING MODEL------------------------------
class PricingModel(models.Model):
    """Represents available pricing plans for owners."""

    PLAN_TYPES = [
        ("PAY_PER_USE", "Pay Per Use"),
        ("SUBSCRIPTION", "Subscription"),
        ("CUSTOM", "Custom Deal"),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPES)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    duration_days = models.PositiveIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_pricing_plans",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.plan_type == "SUBSCRIPTION" and not self.duration_days:
            raise ValidationError("Subscription plans must define duration_days.")
        if self.plan_type != "SUBSCRIPTION" and self.duration_days:
            raise ValidationError("Only subscription plans can include duration_days.")
        if self.plan_type == "CUSTOM" and self.price == 0:
            raise ValidationError("Custom plans must specify a negotiated price.")

    def __str__(self):
        return f"{self.name} ({self.get_plan_type_display()})"

# ------------------------USER PLAN----------------------------------
class UserPlan(models.Model):
    """Assigns a pricing plan to a VSRE Owner."""

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="user_plans"
    )
    plan = models.ForeignKey(PricingModel, on_delete=models.CASCADE)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def clean(self):
        if self.user.user_type not in [
            CustomUser.UserTypes.VSRE_OWNER,
            CustomUser.UserTypes.MASTER_ADMIN,
        ]:
            raise ValidationError("Only VSRE Owners or Master Admins can have plans.")

    def save(self, *args, **kwargs):
        self.clean()

        if self.plan.plan_type == "SUBSCRIPTION":
            self.end_date = self.start_date + timedelta(days=self.plan.duration_days)
            self.is_active = self.start_date <= timezone.localtime() <= self.end_date
        else:
            self.end_date = None
            self.is_active = True

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} → {self.plan.name} ({self.plan.get_plan_type_display()})"

# ------------------------STAFF FOR HIRE (3RD PARTY)-----------------
class StaffForHire(models.Model):
    # ── Staff (the person being hired) ────────────────────────────────────────
    staff_name = models.CharField(max_length=500)
    email = models.EmailField(unique=True)
    mobile_number = models.CharField(max_length=15, unique=True)

    # ── Vendor (agency / supplier name — plain text) ──────────────────────────
    vendor_name = models.CharField(max_length=120)

    # ── Availability ──────────────────────────────────────────────────────────
    available_from = models.DateField()

    available_for = models.JSONField(
        blank=True,
        null=True
    )

    # ── Skills & Language ─────────────────────────────────────────────────────
    language = models.JSONField(blank=True,null=True)

    skill = models.JSONField(blank=True,null=True)

    # ── Pricing ───────────────────────────────────────────────────────────────
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    # ── Meta ──────────────────────────────────────────────────────────────────
    is_active = models.BooleanField(default=True)
    is_available = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_hire_listings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Staff for Hire"
        verbose_name_plural = "Staff for Hire"
        # Prevent the same staff member from being listed twice by the same vendor
        unique_together = [("staff_name", "vendor_name")]

    def __str__(self):
        return (
            f"{self.staff_name} | {self.vendor_name} "
        )    