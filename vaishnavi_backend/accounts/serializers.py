from rest_framework import serializers
from django.contrib.auth import authenticate
from django.db import transaction
from venue_manager.models import Venue,Service,Resource
from .models import (
    CustomUser,
    ShiftSchedule,
    EmployeeProfile,
    UserHierarchy,
    PricingModel,
    UserPlan,
    StaffForHire,
    UserDocument,
    UserDocumentFile
)
from django.contrib.auth.password_validation import validate_password

# ---------------------- Entity mini Serializer ----------------------
class VenueMiniSerializer(serializers.ModelSerializer):
    locality = serializers.CharField(source="location.locality",read_only=True)
    # location
    class Meta:
        model = Venue
        fields = ["id", "name", "locality", "is_active"]

class ServiceMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["id", "name","city", "is_active"]

class ResourceMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resource
        fields = ["id", "name", "is_active"]

# ---------------------- User Profile Serializer ----------------------
class BaseUserSerializer(serializers.ModelSerializer):
    """Base serializer for all user types with shared profile fields."""
 
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=False)
    confirm_password = serializers.CharField(write_only=True, required=False)
 
    class Meta:
        model = CustomUser
        fields = [
            "id",
            "profile_pic",
            "first_name",
            "middle_name",
            "last_name",
            "email",
            "mobile_number",
            "alternate_phone_number",
            "emergency_contact_name",
            "emergency_contact_number",
            "user_type",
            "age",
            "gender",
            "permanent_address",
            "current_address",
            "city",
            "date_joined",
            "is_active",
            "is_deleted",
            "created_by",
            "password",
            "confirm_password",
        ]
        read_only_fields = ["id", "created_by"]
 
    # ---------------------- validation ----------------------
    def validate_email(self, value):
        if not value:
            return value
        qs = CustomUser.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
 
    def validate_mobile_number(self, value):
        qs = CustomUser.objects.filter(mobile_number=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )
        return value
 
    def validate(self, data):
        password = data.get("password")
        confirm_password = data.get("confirm_password")
 
        if self.instance is None and not password:
            raise serializers.ValidationError({"password": "This field is required."})
 
        if password or confirm_password:
            if password != confirm_password:
                raise serializers.ValidationError(
                    {"confirm_password": "Passwords do not match."}
                )
        return data
 
    # ---------------------- hierarchy ----------------------
    @staticmethod
    def _resolve_hierarchy(creator):
        """owner = top VSRE_OWNER of the tree, parent = whoever created the user."""
        if creator is None or creator.is_superuser:
            return None, None, 1
        if creator.is_owner:
            return creator, creator, 1
 
        creator_hierarchy = getattr(creator, "hierarchy", None)
        owner = getattr(creator_hierarchy, "owner", None)
        parent_level = getattr(creator_hierarchy, "level", 0) or 0
        return owner, creator, parent_level + 1
 
    # ---------------------- create ----------------------
    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        creator = request.user if request.user.is_authenticated else None
 
        password = validated_data.pop("password", None)
        validated_data.pop("confirm_password", None)
 
        validated_data["created_by"] = (
            creator if creator and (creator.is_owner or creator.is_manager) else None
        )
 
        user = CustomUser(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
 
        if user.is_owner or user.is_employee:
            owner, parent, level = self._resolve_hierarchy(creator)
            UserHierarchy.objects.create(
                user=user, parent=parent, owner=owner, level=level
            )
 
        return user
 
    # ---------------------- update ----------------------
    @transaction.atomic
    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        validated_data.pop("confirm_password", None)
 
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
 
        if password:
            instance.set_password(password)
 
        instance.save()
        return instance
 
 
    # ---------------------- validation ----------------------
    def validate_email(self, value):
        if not value:
            return value
        qs = CustomUser.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
 
    def validate_mobile_number(self, value):
        qs = CustomUser.objects.filter(mobile_number=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )
        return value
 
    def validate(self, data):
        password = data.get("password")
        confirm_password = data.get("confirm_password")
 
        if self.instance is None and not password:
            raise serializers.ValidationError({"password": "This field is required."})
 
        if password or confirm_password:
            if password != confirm_password:
                raise serializers.ValidationError(
                    {"confirm_password": "Passwords do not match."}
                )
        return data
 
    # ---------------------- hierarchy ----------------------
    @staticmethod
    def _resolve_hierarchy(creator):
        """owner = top VSRE_OWNER of the tree, parent = whoever created the user."""
        if creator is None or creator.is_superuser:
            return None, None, 1
        if creator.is_owner:
            return creator, creator, 1
 
        creator_hierarchy = getattr(creator, "hierarchy", None)
        owner = getattr(creator_hierarchy, "owner", None)
        parent_level = getattr(creator_hierarchy, "level", 0) or 0
        return owner, creator, parent_level + 1
 
    # ---------------------- create ----------------------
    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        creator = request.user if request.user.is_authenticated else None
 
        password = validated_data.pop("password", None)
        validated_data.pop("confirm_password", None)
 
        validated_data["created_by"] = (
            creator if creator and (creator.is_owner or creator.is_manager) else None
        )
 
        user = CustomUser(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
 
        if user.is_owner or user.is_employee:
            owner, parent, level = self._resolve_hierarchy(creator)
            UserHierarchy.objects.create(
                user=user, parent=parent, owner=owner, level=level
            )
 
        return user
 
    # ---------------------- update ----------------------
    @transaction.atomic
    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        validated_data.pop("confirm_password", None)
 
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
 
        if password:
            instance.set_password(password)
 
        instance.save()
        return instance

# ---------------------- Owner Serializer ----------------------
class OwnerSerializer(BaseUserSerializer):
    """Serializer for VSRE Owners."""
    owned_venues = VenueMiniSerializer(many=True, read_only=True)
    owned_services = ServiceMiniSerializer(many=True, read_only=True)
    owned_resources = ResourceMiniSerializer(many=True, read_only=True)
 
    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + [
            "owned_venues",
            "owned_services",
            "owned_resources",
        ]

 # ---------------------- Shift Schedule Serializer ----------------------

class ShiftScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftSchedule
        fields = [
            "id",
            "name",
            "start_time",
            "end_time",
            "is_overnight",
            "grace_minutes",
            "weekly_off_days",
            "is_active",
        ]
        read_only_fields = ["id"]

    def validate_weekly_off_days(self, value):
        """
        Validate that weekly_off_days contains valid weekday values.
        Monday = 0, Sunday = 6.
        """
        if not isinstance(value, list):
            raise serializers.ValidationError(
                "weekly_off_days must be a list."
            )

        if not all(
            isinstance(day, int) and 0 <= day <= 6
            for day in value
        ):
            raise serializers.ValidationError(
                "Each weekday must be an integer between 0 and 6."
            )

        if len(value) != len(set(value)):
            raise serializers.ValidationError(
                "Duplicate weekday values are not allowed."
            )

        return value

    def validate(self, attrs):
        """
        Validate shift timing.
        Overnight shifts may have an end time earlier than
        or equal to the start time.
        """
        start_time = attrs.get(
            "start_time",
            getattr(self.instance, "start_time", None)
        )
        end_time = attrs.get(
            "end_time",
            getattr(self.instance, "end_time", None)
        )
        is_overnight = attrs.get(
            "is_overnight",
            getattr(self.instance, "is_overnight", False)
        )

        if (
            start_time is not None
            and end_time is not None
            and not is_overnight
            and end_time <= start_time
        ):
            raise serializers.ValidationError({
                "end_time": (
                    "End time must be after start time, "
                    "or mark the shift as overnight."
                )
            })

        return attrs
 
# ----------------------- Employee Serializer ---------------
class EmployeeProfileSerializer(serializers.ModelSerializer):
    shift_detail = ShiftScheduleSerializer(source="shift", read_only=True)

    class Meta:
        model = EmployeeProfile
        fields = [
            "employee_id",
            "category",
            "designation",
            "grade",
            "cost_center",
            "department",
            "rehired_status",
            "vendor_name",
            "vendor_phone",
            "last_working_day",
            "termination_type",
            "termination_reason",
            "order_types",
            "skills",
            "target_percent",
            "qc_required",
            "pf_applicable",
            "pf_number",
            "uan_number",
            "esi_applicable",
            "esi_number",
            "esi_dispensary",
            "shift",
            "shift_detail",
            "shift_effective_from",
        ]
        extra_kwargs = {
            "shift": {"write_only": True, "required": False},
            "last_working_day": {"read_only": True},
            "termination_type": {"read_only": True},
            "termination_reason": {"read_only": True},
        }

    def validate(self, data):
        get = lambda field, default=None: data.get(
            field, getattr(self.instance, field, default)
        )

        category = get("category")
        if category != EmployeeProfile.EmployeeCategory.VENDOR and (
            get("vendor_name") or get("vendor_phone")
        ):
            raise serializers.ValidationError(
                {"vendor_name": "Vendor details apply only to the VENDOR category."}
            )

        if get("pf_applicable", False) and not (get("pf_number") or get("uan_number")):
            raise serializers.ValidationError(
                {"pf_number": "PF number or UAN is required when PF is applicable."}
            )

        if get("esi_applicable", False) and not get("esi_number"):
            raise serializers.ValidationError(
                {"esi_number": "ESI number is required when ESI is applicable."}
            )

        return data 

class EmployeeTerminationSerializer(serializers.Serializer):
    termination_type = serializers.ChoiceField(choices=EmployeeProfile.TerminationType.choices)
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    last_working_day = serializers.DateField(required=False)

class ReportsToMixin:
    """Shared `reports_to` resolution for employee-facing serializers."""
 
    def get_reports_to(self, user):
        hierarchy = getattr(user, "hierarchy", None)
        if not hierarchy or not hierarchy.parent:
            return None
        parent = hierarchy.parent
        parent_hierarchy = getattr(parent, "hierarchy", None)
        return {
            "id": parent.id,
            "name": parent.get_full_name(),
            "level": parent_hierarchy.level if parent_hierarchy else None,
        }
 
class AssignmentsMixin:
    """Shared managed_*/assigned_* resolution — manager sees "managed_",
    staff sees "assigned_" related sets on the same three entities."""
 
    def get_venues(self, user):
        qs = user.managed_venues.all() if user.is_manager else user.assigned_venues.all()
        return VenueMiniSerializer(qs, many=True).data
 
    def get_services(self, user):
        qs = user.managed_services.all() if user.is_manager else user.assigned_services.all()
        return ServiceMiniSerializer(qs, many=True).data
 
    def get_resources(self, user):
        qs = user.managed_resources.all() if user.is_manager else user.assigned_resource.all()
        return ResourceMiniSerializer(qs, many=True).data
 
class EmployeeSerializer(ReportsToMixin, AssignmentsMixin, BaseUserSerializer):
    """Write serializer for VSRE_MANAGER, LINE_MANAGER, VSRE_STAFF."""
 
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    employee_profile = EmployeeProfileSerializer(required=False)
    reports_to = serializers.SerializerMethodField()
    venues = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    resources = serializers.SerializerMethodField()
 
    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + [
            "employee_profile",
            "reports_to",
            "venues",
            "services",
            "resources",
        ]
 
    def validate_email(self, value):
        return value or None
 
    @transaction.atomic
    def create(self, validated_data):
        profile_data = validated_data.pop("employee_profile", {})
        user = super().create(validated_data)
        EmployeeProfile.objects.create(user=user, **profile_data)
        return user
 
    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop("employee_profile", None)
        user = super().update(instance, validated_data)
 
        if profile_data is not None:
            profile, _ = EmployeeProfile.objects.get_or_create(user=user)
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()
 
        return user
  
class EmployeeListSerializer(ReportsToMixin, AssignmentsMixin, serializers.ModelSerializer):
    """Read-only list/detail view — managers and staff share one shape."""
 
    reports_to = serializers.SerializerMethodField()
    venues = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    resources = serializers.SerializerMethodField()
    employee_profile = EmployeeProfileSerializer(read_only=True)
 
    class Meta:
        model = CustomUser
        fields = [
            "id",
            "profile_pic",
            "first_name",
            "middle_name",
            "last_name",
            "email",
            "mobile_number",
            "alternate_phone_number",
            "emergency_contact_name",
            "emergency_contact_number",
            "user_type",
            "age",
            "gender",
            "permanent_address",
            "current_address",
            "city",
            "date_joined",
            "is_active",
            "is_deleted",
            "created_by",
            "employee_profile",
            "reports_to",
            "venues",
            "services",
            "resources",
        ]

# ----------------------- BulkEmployeeUploadSerializer ---------------
class BulkEmployeeUploadSerializer(serializers.Serializer):
    """
    Validates the incoming multipart upload for POST /employees/bulk-upload/.
    Keeps the file-shape checks (extension, size) out of the view and in a
    single reusable, testable place; the *content* of the workbook (rows,
    field values) is still validated row-by-row by BulkEmployeeImporter,
    since that depends on live DB state (existing users, shifts, etc.)
    that a plain serializer field can't check.
    """

    file = serializers.FileField(required=True)

    ALLOWED_EXTENSIONS = (".xlsx", ".xlsm")
    MAX_FILE_SIZE_MB = 10

    def validate_file(self, value):
        name = value.name.lower()
        if not name.endswith(self.ALLOWED_EXTENSIONS):
            raise serializers.ValidationError(
                f"File must be one of: {', '.join(self.ALLOWED_EXTENSIONS)}."
            )

        max_bytes = self.MAX_FILE_SIZE_MB * 1024 * 1024
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f"File exceeds {self.MAX_FILE_SIZE_MB}MB limit."
            )

        return value

class BulkUploadRowResultSerializer(serializers.Serializer):
    """A single successful (created/updated) row in the response."""

    row = serializers.IntegerField()
    status = serializers.ChoiceField(choices=["created", "updated"])
    employee_id = serializers.CharField()
    mobile_number = serializers.CharField()
    full_name = serializers.CharField()

class BulkUploadRowErrorSerializer(serializers.Serializer):
    """A single failed row in the response."""

    row = serializers.IntegerField()
    errors = serializers.DictField(child=serializers.CharField())

class BulkUploadSummarySerializer(serializers.Serializer):
    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    failed = serializers.IntegerField()

class BulkUploadResponseSerializer(serializers.Serializer):
    """
    Documents the exact shape process_bulk_upload() returns, so this can be
    plugged straight into drf-spectacular / drf-yasg for schema generation,
    and so the view's return value can be spot-checked against it in tests.
    """

    summary = BulkUploadSummarySerializer()
    created = BulkUploadRowResultSerializer(many=True)
    updated = BulkUploadRowResultSerializer(many=True)
    failed = BulkUploadRowErrorSerializer(many=True)

# ----------------------- Customer Serializer ---------------
class CustomerSerializer(BaseUserSerializer):
    """Serializer for Customers — created by Owner."""
 
    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields  # inherits all base fields
 
    def validate(self, data):
        data = super().validate(data)
        if not self.instance:
            data["user_type"] = CustomUser.UserTypes.CUSTOMER
        return data
 
class CustomerListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            "id",
            "profile_pic",
            "first_name",
            "middle_name",
            "last_name",
            "mobile_number",
        ]

 # ---------------------- User Document Serializers ----------------------

# ----------------------- User Document Serializer ---------------
class UserDocumentFilesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDocumentFile
        fields = "__all__"

class UserDocumentSerializer(serializers.ModelSerializer):
    files = UserDocumentFilesSerializer(many=True, required=False)

    class Meta:
        model = UserDocument
        fields = "__all__"
        read_only_fields = ["uploaded_by"]

# ---------------------- UserHierarchy Serializer ----------------------
class UserHierarchySerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    parent_email = serializers.EmailField(source="parent.email", read_only=True)
    owner_email = serializers.EmailField(source="owner.email", read_only=True)

    class Meta:
        model = UserHierarchy
        fields = '__all__'
        read_only_fields = ('level',)

class ManagerHierarchySerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    level = serializers.IntegerField(source="hierarchy.level", read_only=True)
    parent_id = serializers.IntegerField(source="hierarchy.parent_id", read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "name",
            "email",
            "level",
            "parent_id",
        ]

    def get_name(self, obj):
        return obj.get_full_name()

# ---------------------- Registration Serializer ----------------------
class CustomerRegistrationSerializer(BaseUserSerializer):
    """Public registration for customers."""

    def create(self, validated_data):
        validated_data["user_type"] = "CUSTOMER"
        validated_data["created_by"] = None
        return super().create(validated_data)

class OwnerRegistrationSerializer(BaseUserSerializer):
    """Public registration for VSRE owners (requires approval)."""

    def create(self, validated_data):
        request = self.context.get("request")
        validated_data["user_type"] = "VSRE_OWNER"
        validated_data["created_by"] = None
        return super().create(validated_data)

class UserLoginSerializer(serializers.Serializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        username = data.get("username")
        password = data.get("password")
        user = authenticate(request=self.context.get("request"), username=username, password=password)
        if not user:
            raise serializers.ValidationError("Invalid email or password.")
        data["user"] = user
        return data

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

class RequestOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    channel = serializers.CharField()

    def validate_email(self, value):
        if not CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("No account found with this email.")
        return value
    
    def validate_channel(self, value):
        if value not in ("sms","whatsapp","email"):
            raise serializers.ValidationError("Channel is not valid")
        return value
    
class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp   = serializers.CharField(max_length=6, min_length=6)

class ResetPasswordSerializer(serializers.Serializer):
    reset_token      = serializers.UUIDField()
    new_password     = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

# ---------------------- PricingModel Serializer ----------------------
class PricingModelSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True)

    class Meta:
        model = PricingModel
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def create(self, validated_data):
        request = self.context.get('request')
        if request and not validated_data.get('created_by'):
            validated_data['created_by'] = request.user
        return super().create(validated_data)


# ---------------------- UserPlan Serializer ----------------------
class UserPlanSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = UserPlan
        fields = '__all__'
        read_only_fields = ('is_active', 'end_date')

# ---------------------- Staff For Hire Serializer -----------------
class StaffForHireListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list / search responses."""

    class Meta:
        model = StaffForHire
        fields = [
            "id",
            "staff_name",
            "email",
            "mobile_number",
            "vendor_name",
            "available_from",
            "available_for",
            "language",
            "skill",
            "price",
            "is_active",
            "is_available",
        ]

class StaffForHireDetailSerializer(serializers.ModelSerializer):
    """Full serializer for create / retrieve / update."""

    class Meta:
        model = StaffForHire
        fields = [
            "id",
            "staff_name",
            "email",
            "mobile_number",
            "vendor_name",
            "available_from",
            "available_for",
            "language",
            "skill",
            "price",
            "is_active",
            "is_available",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]

    def validate_available_for(self, value):
        if value is not None:
            if not isinstance(value, list):
                raise serializers.ValidationError("available_for must be a list of service names.")
            if not all(isinstance(s, str) for s in value):
                raise serializers.ValidationError("Each entry in available_for must be a string.")
        return value

    def validate_language(self, value):
        if value is not None:
            if not isinstance(value, list):
                raise serializers.ValidationError("language must be a list of strings.")
            if not all(isinstance(s, str) for s in value):
                raise serializers.ValidationError("Each entry in language must be a string.")
        return value

    def validate_skill(self, value):
        if value is not None:
            if not isinstance(value, list):
                raise serializers.ValidationError("skill must be a list of strings.")
            if not all(isinstance(s, str) for s in value):
                raise serializers.ValidationError("Each entry in skill must be a string.")
        return value

    def create(self, validated_data):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        return super().create(validated_data)
