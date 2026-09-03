from django.db import models
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

# ------------------------USER MODEL---------------------------------
class CustomUser(AbstractBaseUser, PermissionsMixin):
    """Core user model supporting multiple user_types and hierarchy."""

    class UserTypes(models.TextChoices):
        MASTER_ADMIN = "MASTER_ADMIN", "Master Admin"
        VSRE_OWNER = "VSRE_OWNER", "VSRE Owner"
        VSRE_MANAGER = "VSRE_MANAGER", "VSRE Manager"
        LINE_MANAGER = "LINE_MANAGER", "Line Manager"
        VSRE_STAFF = "VSRE_STAFF", "VSRE Staff"
        CUSTOMER = "CUSTOMER", "Customer"

    class EmployeeCategory(models.TextChoices):
        REGULAR = "REGULAR", "Regular"
        FULLTIME = "FULLTIME", "Fulltime"
        PARTTIME = "PARTTIME", "Parttime"
        VIRTUAL = "VIRTUAL", "Virtual"
        PPO = "PPO", "PPO"
        VENDOR = "VENDOR", "Vendor"
    

    GENDER_CHOICES = [
        ("M", "Male"),
        ("F", "Female"),
        ("O", "Other"),
        ("N", "Prefer not to say"),
    ]
    phone_regex = RegexValidator(
        regex=r'^\d{10}$',
        message="Phone number must be 10 digits"
    )
    profile_pic = models.ImageField(upload_to="profile_photos/",null=True,blank=True,)
    employee_id = models.CharField(max_length=20, unique=True, blank=True, null=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    mobile_number = models.CharField(max_length=10, unique=True, validators=[phone_regex])
    emergency_contact = models.CharField(max_length=15, blank=True, null=True)

    first_name = models.CharField(max_length=30)
    middle_name = models.CharField(max_length=30, blank=True, null=True)
    last_name = models.CharField(max_length=30)

    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    category = models.CharField(
        max_length=50, choices=EmployeeCategory, null=True, blank=True
    )
    user_type = models.CharField(max_length=30, choices=UserTypes.choices)
    address = models.TextField()
    city = models.CharField(max_length=100, db_index=True)  # Base/preferred location

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    date_joined = models.DateField(blank=True, null=True)
    last_working_day = models.DateField(blank=True, null=True)
    order_types = models.JSONField(blank=True, null=True)
    skills = models.JSONField(blank=True, null=True)
    target_percent = models.FloatField(blank=True, null=True)
    qc_required = models.BooleanField(default=False)
    created_by = models.ForeignKey("self",on_delete=models.SET_NULL,null=True,blank=True,related_name="created_users")
    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "mobile_number"]
    class Meta:
        ordering = ["id"]
    @property
    def is_owner(self):
        return self.user_type in [self.UserTypes.VSRE_OWNER, self.UserTypes.MASTER_ADMIN]
    
    @property
    def is_manager(self):
        return self.user_type in [self.UserTypes.VSRE_MANAGER, self.UserTypes.LINE_MANAGER]
    
    @property
    def is_vsre_staff(self):
        return self.user_type in [self.UserTypes.VSRE_STAFF]
    
    @property
    def is_customer(self):
        return self.user_type in [self.UserTypes.CUSTOMER]
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def soft_delete(self):
        self.is_active = False
        self.is_deleted = True
        self.save()
   
    def can_manage_entity(self, entity):
        """Check if user has permission to manage specific entity"""
        if self.is_superuser:
            return entity.all == self
        if self.is_owner:
            return entity.owner == self
        elif self.is_manager:
            return entity.manager == self
        else:  # staff
            return entity.is_vsre_staff == self
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.user_type})"

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