from rest_framework import serializers
from django.contrib.auth import authenticate
from venue_manager.models import Venue,Service,Resource
from .models import CustomUser, UserHierarchy, PricingModel, UserPlan,StaffForHire,UserDocument,UserDocumentFile
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
            "emergency_contact",
            "user_type",
            "gender",
            "address",
            "city",
            "date_joined",
            "is_active",
            "is_deleted",
            "created_by",
            "password",
            "confirm_password"
        ]
        read_only_fields = ["id", "user_type","created_by",'last_working_day']

    # ---------------------- Validation ----------------------
    def validate(self, data):
        password = data.get("password")
        confirm_password = data.get("confirm_password")

        if password or confirm_password:
            if password != confirm_password:
                raise serializers.ValidationError("Passwords do not match.")
        return data

# ---------------------- Create ----------------------
    def create(self, validated_data):
        request = self.context["request"]
        creator = request.user if request.user.is_authenticated else None

        # Remove unwanted fields
        password = validated_data.pop("password", None)
        validated_data.pop("confirm_password", None)

        # Assign creator only for owner / manager
        if creator and (creator.is_owner or creator.is_manager):
            validated_data["created_by"] = creator
        else:
            validated_data["created_by"] = None

        # Create user
        user = CustomUser(**validated_data)
        if password:
            user.set_password(password)
        user.save()

        # ====================================================
        #  HIERARCHY CREATION (Owner / Manager / Staff only)
        # ====================================================
        if user.is_owner or user.is_manager or user.is_vsre_staff:

            # Resolve owner safely
            if creator and (creator.is_superuser or creator.is_owner or creator.is_manager):
                owner = creator
            elif creator:
                owner = getattr(creator.hierarchy, "owner", None)
            else:
                owner = None

            UserHierarchy.objects.create(
                user=user,
                parent=owner,
                owner=owner,
            )

        return user
# ---------------------- Update ----------------------
    def update(self, instance, validated_data):
        request = self.context["request"]
        password = validated_data.pop("password", None)
        validated_data.pop("confirm_password", None)

        # Normal updates
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance

# ----------------------- User Minimul list serializers ---------------
class ManagerListSerializer(serializers.ModelSerializer):
    reports_to = serializers.SerializerMethodField()
    managed_venues = VenueMiniSerializer(many=True, read_only=True)
    managed_services = ServiceMiniSerializer(many=True, read_only=True)
    managed_resources = ResourceMiniSerializer(many=True, read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "profile_pic",
            "first_name",
            "middle_name",
            "last_name",
            "employee_id",
            "mobile_number",
            "email",
            "emergency_contact",
            "category",
            "skills",
            "is_active",
            "reports_to",
            "managed_venues",
            "managed_services",
            "managed_resources",
        ]

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

class StaffListSerializer(serializers.ModelSerializer):
    reports_to = serializers.SerializerMethodField()
    assigned_venues = VenueMiniSerializer(many=True, read_only=True)
    assigned_services = ServiceMiniSerializer(many=True, read_only=True)
    assigned_resource = ResourceMiniSerializer(many=True, read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "profile_pic",
            "first_name",
            "middle_name",
            "last_name",
            "employee_id",
            "mobile_number",
            "email",
            "emergency_contact",
            "category",
            "skills",
            "is_active",
            "reports_to",
            "assigned_venues",
            "assigned_venues",
            "assigned_services",
            "assigned_resource",
        ]

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

# ---------------------- User user_type Profile Serializer ----------------------
class OwnerSerializer(BaseUserSerializer):
    """Serializer for VSRE Owners."""
    owned_venues = VenueMiniSerializer(many=True, read_only=True)
    owned_service = ServiceMiniSerializer(many=True, read_only=True)
    owned_resoure = ResourceMiniSerializer(many=True, read_only=True)
    
    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + ["owned_venues", "owned_service","owned_resoure"]

class ManagerSerializer(BaseUserSerializer):
    reports_to = serializers.SerializerMethodField()
    managed_venues = VenueMiniSerializer(many=True, read_only=True)
    managed_services = ServiceMiniSerializer(many=True, read_only=True)
    managed_resources = ResourceMiniSerializer(many=True, read_only=True)

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + [
            "employee_id",
            "category",
            "skills",
            "qc_required",
            "last_working_day",
            "reports_to",
            "managed_venues",
            "managed_services",
            "managed_resources",
        ]

    def get_reports_to(self, user):
        hierarchy = getattr(user, "hierarchy", None)
        if not hierarchy:
            return None

        parent = hierarchy.parent
        if not parent:
            return None

        parent_hierarchy = getattr(parent, "hierarchy", None)
        parent_level = parent_hierarchy.level if parent_hierarchy else None

        return {
            "id": parent.id,
            "name": parent.get_full_name(),
            "level": parent_level
        }

class StaffSerializer(BaseUserSerializer):
    """Serializer for VSRE Staff."""
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    reports_to = serializers.SerializerMethodField()
    
    assigned_venues = VenueMiniSerializer(many=True, read_only=True)
    assigned_services = ServiceMiniSerializer(many=True, read_only=True)
    assigned_resource = ResourceMiniSerializer(many=True, read_only=True)

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + [
            "employee_id",
            "category",
            "skills",
            "target_percent",
            "order_types",
            "last_working_day",
            "reports_to",
            "assigned_venues",
            "assigned_services",
            "assigned_resource",
        ]
    def validate_email(self, value):
        # Coerce blank string to None so the unique constraint never sees ""
        return value or None
     
    def get_reports_to(self, user):
        hierarchy = getattr(user, "hierarchy", None)
        if not hierarchy:
            return None

        parent = hierarchy.parent
        if not parent:
            return None

        parent_hierarchy = getattr(parent, "hierarchy", None)
        parent_level = parent_hierarchy.level if parent_hierarchy else None

        return {
            "id": parent.id,
            "name": parent.get_full_name(),
            "level": parent_level
        }

class CustomerSerializer(BaseUserSerializer):
    """Serializer for Customers — created by Owner."""

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields  # inherits all base fields

    def validate(self, data):
        data = super().validate(data)
        # Enforce user_type on create
        if not self.instance:
            data["user_type"] = CustomUser.UserTypes.CUSTOMER
        return data
    
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

class VSREOwnerRegistrationSerializer(BaseUserSerializer):
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
