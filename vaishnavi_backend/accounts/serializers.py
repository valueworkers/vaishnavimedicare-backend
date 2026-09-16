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
    class Meta:
        model = Venue
        fields = ["id", "name", "is_active"]

class ServiceMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["id", "name", "is_active"]

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
            "address",
            "city",
            "date_joined",
            "is_active",
            "is_deleted",
            "created_by",
            "password",
            "confirm_password",
        ]
        read_only_fields = ["id", "user_type", "created_by"]
 
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
 
    def validate(self, data):
        is_overnight = data.get(
            "is_overnight", getattr(self.instance, "is_overnight", False)
        )
        start = data.get("start_time", getattr(self.instance, "start_time", None))
        end = data.get("end_time", getattr(self.instance, "end_time", None))
        if not is_overnight and start and end and end <= start:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time, or mark the shift as overnight."}
            )
        return data
 
# ----------------------- Employee Serializer ---------------
class EmployeeProfileSerializer(serializers.ModelSerializer):
    shift_detail = ShiftScheduleSerializer(source="shift", read_only=True)
 
    class Meta:
        model = EmployeeProfile
        fields = [
            "employee_id",
            "category",
            "designation",
            "status",
            "grade",
            "cost_center",
            "department",
            "permanent_address",
            "current_address",
            "rehired_status",
            "vendor_name",
            "vendor_phone",
            "date_joined",
            "last_working_day",
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
        extra_kwargs = {"shift": {"write_only": True, "required": False}}
 
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
 
        joined, last_day = get("date_joined"), get("last_working_day")
        if joined and last_day and last_day < joined:
            raise serializers.ValidationError(
                {"last_working_day": "Last working day cannot precede the joining date."}
            )
 
        if get("pf_applicable", False) and not (get("pf_number") or get("uan_number")):
            raise serializers.ValidationError(
                {"pf_number": "PF number or UAN is required when PF is applicable."}
            )
 
        if get("esi_applicable", False) and not get("esi_number"):
            raise serializers.ValidationError(
                {"esi_number": "ESI number is required when ESI is applicable."}
            )
 
        if get("status") == EmployeeProfile.Status.TERMINATED and not last_day:
            raise serializers.ValidationError(
                {"last_working_day": "LWD is required when status is Terminated."}
            )
        return data
 
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
            "mobile_number",
            "email",
            "alternate_phone_number",
            "emergency_contact_name",
            "emergency_contact_number",
            "age",
            "user_type",
            "is_active",
            "employee_profile",
            "reports_to",
            "venues",
            "services",
            "resources",
        ]

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
