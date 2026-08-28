# views.py
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.contrib.auth.hashers import check_password 
from rest_framework import viewsets,generics,status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated,AllowAny
from .permissions import IsVSREOwner,IsCreator,IsVSREOwnerOrManager,IsMasterAdmin
from .models import CustomUser, UserHierarchy, PricingModel, UserPlan,StaffForHire
from .serializers import *
from .utils import send_otp,PasswordResetOTP
import uuid

# ---------------------- User registration ViewSet ----------------------
class CustomerRegistrationView(generics.CreateAPIView):
    serializer_class = CustomerRegistrationSerializer
    permission_classes = [AllowAny]

class VSREOwnerRegistrationView(generics.CreateAPIView):
    serializer_class = VSREOwnerRegistrationSerializer
    permission_classes = [AllowAny]

# ---------------------- User Authentication ViewSet ----------------------
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = UserLoginSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.validated_data['user']
            if not user.is_active:
                return Response(
                    {'error': 'Account pending approval by Master Admin.'},
                    status=status.HTTP_403_FORBIDDEN
                )

            user.last_login = timezone.localtime()
            user.save()

            refresh = RefreshToken.for_user(user)
            return Response({
                'message': f'Login successful as {user.user_type}',
                'user': BaseUserSerializer(user).data,
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token)
                }
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh_token')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            return Response({'message': 'Logout successful'}, status=status.HTTP_200_OK)
        except Exception:
            return Response({'error': 'Invalid token or logout failed'}, status=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if not check_password(serializer.validated_data['old_password'], user.password):
                return Response(
                    {"old_password": "Current password is incorrect."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            return Response({"message": "Password changed successfully."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ---------------------- Password Reset via OTP ----------------------
class RequestPasswordResetOTPView(APIView):
    """
    Step 1: User submits their email.
    Generates a 6-digit OTP, saves it (invalidating any previous unused OTPs),
    and sends it via email.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RequestOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]
        channel = serializer.validated_data["channel"]
        user = CustomUser.objects.get(email=email)
        
        # Generate and store new OTP
        raw_otp = PasswordResetOTP.generate(user)
        
        # send_otp(channel=channel, user=user, raw_otp=raw_otp)
    
        return Response(
            {"message": f"OTP on {channel} sent successfully"},
            status=status.HTTP_200_OK,
        )

class VerifyOTPView(APIView):
    """
    Step 2 — POST { email, otp }
    Validates the OTP. On success returns a short-lived reset_token
    that Step 3 requires.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email    = serializer.validated_data["email"]
        raw_otp  = serializer.validated_data["otp"]

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return Response({"error": "Invalid Email."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reset_token = PasswordResetOTP.verify(user, raw_otp)
        except PasswordResetOTP.TooManyAttempts:
            return Response(
                {"error": "Too many incorrect attempts. Please request a new OTP."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except PasswordResetOTP.ExpiredOTP:
            return Response(
                {"error": "OTP has expired. Please request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PasswordResetOTP.InvalidOTP:
            return Response({"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)


        return Response({"reset_token": str(reset_token)}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    """
    Step 3 — POST { reset_token, new_password, confirm_password }
    Validates the token, changes the password, invalidates the record.
    """
    permission_classes = [AllowAny]
    throttle_scope     = "otp_verify"

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        reset_token  = serializer.validated_data["reset_token"]
        new_password = serializer.validated_data["new_password"]

        try:
            user_id  = PasswordResetOTP.consume_reset_token(reset_token)
        except PasswordResetOTP.InvalidOTP:
            return Response(
                {"error": "Invalid or already used reset token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        
        user = CustomUser.objects.get(id=user_id)
        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response(
            {"message": "Password reset successful."},
            status=status.HTTP_200_OK,
        )

# ---------------------- User Profile ViewSet -------------------------
class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self, user):
        if user.is_owner:
            return OwnerSerializer
        elif user.is_manager:
            return ManagerSerializer
        elif user.is_vsre_staff:
            return StaffSerializer
        return CustomerSerializer
    
    def get(self, request):
        serializer_class = self.get_serializer_class(request.user)
        serializer = serializer_class(instance=request.user, context={'request': request})
        return Response(serializer.data)

    def put(self, request):
        serializer_class = self.get_serializer_class(request.user)
        serializer = serializer_class(
            instance=request.user,
            data=request.data,
            partial=True,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ---------------------- User management ViewSet -------------------------
class OwnerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OwnerSerializer
    
    permission_classes = [IsAuthenticated]
    filterset_fields = ["is_active", "city"]
    search_fields = ["email", "first_name", "last_name", "mobile_number"]


    def get_queryset(self):
        """Fetch all VSRE Owners."""
        request_user = self.request.user
        queryset = CustomUser.objects.owners()
        
        if request_user.is_superuser:
            return queryset
        
        if request_user.is_owner:
            return queryset.filter(hierarchy__owner=request_user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context
    
    def perform_create(self, serializer):
        # create user first
        user = serializer.save(
            user_type=CustomUser.UserTypes.VSRE_OWNER,
            
        )
        return user
    
    def list(self, request, *args, **kwargs):
        owners = self.filter_queryset(self.get_queryset())

        # Use CustomUserManager methods for counts
        data = []
        for owner in owners:
            managers = CustomUser.objects.get_all_managers_under_owner(owner)
            staff = CustomUser.objects.get_staff_under_owner(owner)

            data.append({
                "id": owner.id,
                "first_name": owner.first_name,
                "last_name": owner.last_name,
                "email": owner.email,
                "mobile_number": owner.mobile_number,
                "city": owner.city,
                "manager_count": managers.count(),
                "staff_count": staff.count(),
            })

        page = self.paginate_queryset(data)
        if page is not None:
            return self.get_paginated_response(page)

        return Response(data)

    # ----------------------------------------------------------------------
    # RETRIEVE: Detailed hierarchy of a specific owner
    # ----------------------------------------------------------------------
    def retrieve(self, request, *args, **kwargs):
        owner = self.get_object()

        # Use manager’s hierarchy helper
        hierarchy = CustomUser.objects.get_entire_hierarchy_under_owner(owner)

        managers = hierarchy["all_managers"]
        staff = hierarchy["all_staff"]

        data = OwnerSerializer(owner).data
        data.update({
            "manager_count": managers.count(),
            "staff_count": staff.count(),
            "managers": [
                {
                    "id": m.id,
                    "name": f"{m.first_name} {m.last_name}".strip(),
                    "email": m.email,
                    "staff_count": CustomUser.objects.get_staff_under_manager(m).count(),
                }
                for m in managers
            ],
        })

        return Response(data)

class ManagerViewSet(viewsets.ModelViewSet):
    """
    Allows VSRE_OWNER to manage their own VSRE_MANAGER users.
    """
    serializer_class = ManagerSerializer
    
    permission_classes = [ IsVSREOwner, IsCreator]
    filterset_fields = ["is_active", "city", "category"]
    search_fields = [
        "first_name",
        "middle_name",
        "last_name",
        "employee_id",
        "mobile_number",
        "email",
        "emergency_contact",
        "category",
        "skills"
    ]

    def get_queryset(self):
        """Return only managers created by this owner."""
        request_user = self.request.user
        queryset = CustomUser.objects.managers()
        
        if request_user.is_superuser:
            return queryset
        
        if request_user.is_owner:
            return queryset.filter(hierarchy__owner=request_user)
        
        if request_user.is_manager:
            return queryset.filter(hierarchy__parent=request_user)
        
    def get_serializer_class(self):
        if self.action == "list":
            return ManagerListSerializer
        return ManagerSerializer
       
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def perform_create(self, serializer):
        # create user first
        user = serializer.save(
            user_type=CustomUser.UserTypes.VSRE_MANAGER,
            
        )
        return user
    
    def perform_destroy(self, instance):
        if hasattr(instance, "soft_delete"):
            instance.soft_delete()
        else:
            instance.delete()

class StaffViewSet(viewsets.ModelViewSet):
    """
    Allows both VSRE_OWNER and VSRE_MANAGER to manage their own VSRE_STAFF users.
    """
    serializer_class = StaffSerializer
    
    permission_classes = [IsAuthenticated,IsCreator,IsVSREOwnerOrManager]
    filterset_fields = ["is_active", "city", "category"]
    search_fields = [
        "first_name",
        "middle_name",
        "last_name",
        "employee_id",
        "mobile_number",
        "email",
        "emergency_contact",
        "category",
        "skills"
    ]

    def get_queryset(self):
        """
        Return only staff created by the logged-in owner/manager.
        """
        return CustomUser.objects.filter(
            created_by=self.request.user,
            hierarchy__owner=self.request.user,
            user_type=CustomUser.UserTypes.VSRE_STAFF,
            is_deleted= False,
        )
    def get_serializer_class(self):
        if self.action == "list":
            return StaffListSerializer
        return StaffSerializer
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def perform_create(self, serializer):
        # create user first
        user = serializer.save(user_type=CustomUser.UserTypes.VSRE_STAFF)
        return user
    
    def perform_destroy(self, instance):
        
        if hasattr(instance, "soft_delete"):
            instance.soft_delete()
        # else:
        #     instance.delete()

class CustomerViewSet(viewsets.ModelViewSet):
    """
    list:   GET  /customers/
    create: POST /customers/
    retrieve: GET  /customers/<id>/
    update: PUT  /customers/<id>/
    partial_update: PATCH /customers/<id>/
    destroy: DELETE /customers/<id>/
    """
    search_fields= [
        "first_name",
        "middle_name",
        "last_name",
        "email",
        "mobile_number",
        "emergency_contact",
        "address",
        "city"
    ]
    filterset_fields = {
        "gender":["exact", "icontains"],
        "address":["exact", "icontains"],
        "city":["exact", "icontains"],
        "date_joined":["gte", "lte", "exact"],
        "is_active":["exact"],
        "created_by":["exact"],
    }
    ordering_fields = [
        "first_name",
        "middle_name",
        "last_name",
        "email",
        "mobile_number",
        "emergency_contact",
        "address",
        "city",
        "gender",
        "address",
        "city",
        "date_joined",
        "is_active",
        "created_by",
        ]
    ordering = ["first_name"]

    
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, IsVSREOwner]

    def get_queryset(self):
        return CustomUser.objects.filter(
            user_type=CustomUser.UserTypes.CUSTOMER,
            is_deleted=False,
        ).order_by("-id")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"message": "Customer created successfully.", "data": serializer.data},
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(
            {"message": "Customer updated successfully.", "data": serializer.data}
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete()
        return Response(
            {"message": "Customer deleted successfully."},
            status=status.HTTP_200_OK,
        )

class ParentAssignmentView(APIView):
    """
    GET    → Get current parent + assignable parents
    POST   → Assign parent
    DELETE → Remove parent
    """

    def get(self, request, user_id=None):
        try:
            child = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            child = request.user
        # --------------------------
        # CURRENT PARENT
        # --------------------------
        try:
            hierarchy = child.hierarchy
            parent = hierarchy.parent

            current_parent = {
                "id": parent.id,
                "name": parent.get_full_name(),
                "level": parent.hierarchy.level,
            } if parent else None

        except UserHierarchy.DoesNotExist:
            current_parent = None

        # --------------------------
        # ASSIGNABLE PARENTS (Dropdown)
        # --------------------------
        managers = CustomUser.objects.filter(
            hierarchy__owner=request.user,
            user_type__in=["VSRE_MANAGER", "LINE_MANAGER"]
        ).exclude(id__in=[user_id, parent.id])

        assignable = [
            {
                "id": m.id,
                "name": m.get_full_name(),
                "level": m.hierarchy.level,
            }
            for m in managers
        ]

        return Response({
            "current_parent": current_parent,
            "assignable_parents": assignable
        })

    # ---------------------------------------------------
    def post(self, request, user_id):
        """Assign a parent to a user"""
        child = get_object_or_404(CustomUser, id=user_id)
        parent_id = request.data.get("parent_id")

        if not parent_id:
            return Response({"error": "parent_id is required"}, status=400)

        # Check valid parent
        parent = get_object_or_404(
            CustomUser,
            id=parent_id,
            user_type__in=["VSRE_MANAGER", "LINE_MANAGER"],
        )

        hierarchy, _ = UserHierarchy.objects.get_or_create(
            user=child,
            defaults={"owner": request.user},
        )

        # prevent circular assignment
        if parent == child:
            return Response({"error": "A user cannot be their own parent"}, status=400)

        hierarchy.parent = parent
        hierarchy.save()

        return Response({
            "message": "Parent assigned successfully",
            "reports_to": {
                "id": parent.id,
                "name": parent.get_full_name(),
                "level": parent.hierarchy.level,
            },
        })

    # ---------------------------------------------------
    def delete(self, request, user_id):
        """Unassign parent"""
        child = get_object_or_404(CustomUser, id=user_id)

        hierarchy = get_object_or_404(UserHierarchy, user=child)

        hierarchy.parent = None
        hierarchy.level = 0
        hierarchy.save()

        return Response({"message": "Parent removed"})

class StaffForHireViewSet(viewsets.ModelViewSet):
    """
    for 3rd-party staff hire listings.

    Endpoints  /accounts/staff-for-hire/
    ────────────────────────────────────────────────
    GET    /                   list
    POST   /                   create
    GET    /{id}/              retrieve
    PUT    /{id}/              full update
    PATCH  /{id}/              partial update
    DELETE /{id}/              soft-delete (is_active → False)
    POST   /bulk-hire/         bulk-hire 

    Query params
    ────────────────────────────────────────────────
    ?staff_name=<text>
    ?vendor_name=<text>
    ?available_from=<date>
    ?available_for=<service>      JSON contains filter
    ?price__gte=&price__lte=
    ?is_active=true|false
    ?search=<staff_name / vendor_name>
    ?ordering=price,-available_from,created_at
    """

    queryset = StaffForHire.objects.select_related("created_by").all()

    filterset_fields = {
        "staff_name": ["exact", "icontains"],
        "vendor_name": ["exact", "icontains"],
        "vendor_name": ["exact", "icontains"],
        "available_from": ["gte", "lte", "exact"],
        "price": ["gte", "lte"],
        "is_active": ["exact"],
        "is_available": ["exact"],
    }
    search_fields = ["staff_name", "vendor_name","available_for","language","skill"]
    ordering_fields = ["price", "available_from", "created_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return StaffForHireListSerializer
        return StaffForHireDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # ?available_for=Nursing  →  JSON contains filter
        service = self.request.query_params.get("available_for")
        if service:
            qs = qs.filter(available_for__contains=[service])

        user = self.request.user
        # Owners / master admins see all; everyone else sees only active listings
        if hasattr(user, "is_owner") and user.is_owner:
            return qs
        return qs.filter(is_active=True)

    # Soft-delete instead of hard-delete
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        return Response({"detail": "Listing deactivated."}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="bulk-hire")
    def bulk_hire(self, request):
        staff_list = request.data.get("staff_list", [])

        if not isinstance(staff_list, list) or not staff_list:
            return Response(
                {"error": "staff_list must be a non-empty list"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        staffs = StaffForHire.objects.filter(
            id__in=staff_list,
            # is_active=True,
            # is_available=True
        )

        created = 0
        updated = 0
        failed = []

        for item in staffs:

            if not item.email:
                failed.append({"id": item.id, "error": "Email required"})
                continue

            name_parts = item.staff_name.strip().split()

            defaults = {
                "first_name": name_parts[0] if len(name_parts) > 0 else "",
                "middle_name": " ".join(name_parts[1:-1]) if len(name_parts) > 2 else "",
                "last_name": name_parts[-1] if len(name_parts) > 1 else "",
                "mobile_number": item.mobile_number,
                "gender": getattr(item, 'gender', 'N'),
                "address": getattr(item, 'address', ''),
                "city": getattr(item, 'city', ''),
                "user_type": CustomUser.UserTypes.VSRE_STAFF,
                "category": CustomUser.EmployeeCategory.VENDOR,
                "skills": item.skill or [],
                "created_by": request.user,
            }

            try:
                user, is_created = CustomUser.objects.update_or_create(
                    email=item.email,
                    defaults=defaults
                )
                
                UserHierarchy.objects.update_or_create(
                    user = user,
                    defaults = {
                        "parent" : request.user,
                        "owner" : request.user
                    }
                )
                if is_created:
                    user.set_unusable_password()
                    user.save()
                    created += 1
                else:
                    updated += 1

                item.is_available = False
                item.save(update_fields=["is_available"])

            except Exception as e:
                failed.append({
                    "id": item.id,
                    "error": str(e)
                })

        return Response({
            "created": created,
            "updated": updated,
            "failed": failed
        })

class UserDocumentViewSet(viewsets.ModelViewSet):
    """
    list:     GET    /user-documents/
    create:   POST   /user-documents/
    retrieve: GET    /user-documents/<pk>/
    update:   PUT    /user-documents/<pk>/
    partial:  PATCH  /user-documents/<pk>/
    destroy:  DELETE /user-documents/<pk>/
    """

    serializer_class = UserDocumentSerializer
    
    search_fields = [
        'title',
        'remarks',
        'uploaded_by__first_name',
        'uploaded_by__last_name',
        'uploaded_by__email',
        'user__first_name',
        'user__last_name',
        'user__email',
        'user__phone',
        'user__employee_id',
    ]

    filterset_fields = {
        'user': ['exact'],
        'title': ['exact', 'icontains'],
        'uploaded_by': ['exact'],
        'created_at': ['date', 'gte', 'lte'],
        'updated_at': ['date', 'gte', 'lte'],
    }

    ordering_fields = [
        'title',
        'created_at',
        'updated_at',
        'uploaded_by',
        'user',
    ]
    ordering = ['-created_at']
    

    def get_queryset(self):
        return (
            UserDocument.objects
            .select_related("uploaded_by")
            .prefetch_related("files")
        )

    def perform_create(self, serializer):
        document = serializer.save(
            uploaded_by=self.request.user,
        )
        files = self.request.FILES.getlist("files")
        UserDocumentFile.objects.bulk_create([
            UserDocumentFile(document=document, file=f) for f in files
        ])

    def perform_update(self, serializer):
        document = serializer.save()
        files = self.request.FILES.getlist("files")

        if files:
            UserDocumentFile.objects.bulk_create([
                UserDocumentFile(document=document, file=f) for f in files
            ])

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        for file_obj in instance.files.all():
            if file_obj.file:
                file_obj.file.delete(save=False)
        self.perform_destroy(instance)
        return Response(
            {"detail": "Document deleted successfully."},
            status=status.HTTP_204_NO_CONTENT,
        )

# ---------------------- PricingModel ViewSet ----------------------
class PricingModelViewSet(viewsets.ModelViewSet):
    queryset = PricingModel.objects.select_related("created_by")
    serializer_class = PricingModelSerializer
    filterset_fields = ['plan_type', 'is_active']
    search_fields = ['name', 'description', 'created_by__email']

# ---------------------- UserPlan ViewSet ----------------------
class UserPlanViewSet(viewsets.ModelViewSet):
    queryset = UserPlan.objects.select_related("user", "plan")
    serializer_class = UserPlanSerializer
    filterset_fields = ['is_active', 'plan__plan_type']
    search_fields = ['user__email', 'plan__name']

    @action(detail=True, methods=['post'])
    def expire(self, request, pk=None):
        plan = self.get_object()
        plan.is_active = False
        plan.end_date = timezone.localtime()
        plan.save()
        return Response({"detail": "Plan expired."})

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        plan = self.get_object()
        plan.is_active = True
        if (
            plan.plan.plan_type == "SUBSCRIPTION"
            and (not plan.end_date or plan.end_date < timezone.localtime())
        ):
            plan.end_date = plan.start_date + timezone.timedelta(days=plan.plan.duration_days)
        plan.save()
        return Response({"detail": "Plan activated."})

