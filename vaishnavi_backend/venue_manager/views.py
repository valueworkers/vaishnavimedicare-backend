from rest_framework import viewsets, views,status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from .permissions import EntityAccessPermission,CanAssignUsers
from .serializers import *
from accounts.models import CustomUser
from accounts.serializers import (
    VenueMiniSerializer,
    ServiceMiniSerializer,
    ResourceMiniSerializer
)
from .models import *
from .validations import *

# VENUE VIEWSET
class VenueViewSet(viewsets.ModelViewSet):
    serializer_class = VenueSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Venue.objects.select_related("owner", "location").prefetch_related(
            "manager", "staff", "photos"
        ).filter(is_deleted=False)
    
    # FILTERS (use related location fields)
    filterset_fields = {
        "location": ["exact"],
        "location__city": ["iexact", "icontains"],
        "location__state": ["iexact", "icontains"],
        "is_active": ["exact"],
        "is_deleted": ["exact"],
        "manager": ["exact"],
        "staff": ["exact"],
        "capacity": ["gte", "lte", "exact"],
        "price_per_event": ["gte", "lte"],
        "rooms": ["gte", "lte"],
        "floors": ["gte", "lte"],
        "external_decorators_allow": ["exact"],
        "external_caterers_allow": ["exact"],
    }
    
    # SEARCH (use related location fields)
    search_fields = [
        "name",
        "description",
        "location__building_name",
        "location__address_line1",
        "location__address_line2",
        "location__locality",
        "location__city",
        "location__state",
    ]

    # QUERYSET BASED ON USER ROLE   
    def get_queryset(self):
        user = self.request.user
        qs = self.queryset.order_by("-created_at")

        if user.is_superuser:
            return qs
        if user.is_owner:
            return qs.filter(owner=user)
        elif user.is_manager:
            return qs.filter(manager=user)
        elif user.is_vsre_staff:
            return qs.filter(staff=user)
    
    # CREATE → OWNER ONLY    
    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_owner:
            raise PermissionDenied("Only owners can create venues.")
        serializer.save(owner=user, is_active=True)

    
    # SOFT DELETE
    def perform_destroy(self, instance):
        if hasattr(instance, "soft_delete"):
            instance.soft_delete()
        else:
            instance.delete()

# SERVICE VIEWSET
class ServiceViewSet(viewsets.ModelViewSet):
    serializer_class = ServiceSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    filterset_fields = {
        "is_active": ["exact"],
        "service_type": ["exact"],
        "venue": ["exact"],
        "venue__location": ["exact"],
        "manager": ["exact"],
        "staff": ["exact"],
        # "tags": ["icontains"],
    }

    search_fields = [
        "name",
        "description",
        "address",
        "contact",
    ]

    
    # FILTER SERVICES BASED ON user_type
    
    def get_queryset(self):
        user = self.request.user

        if user.is_superuser:
            return Service.objects.all()
        
        if user.is_owner:
            return Service.objects.filter(owner=user, is_deleted=False)

        if user.is_manager:
            return Service.objects.filter(manager=user, is_deleted=False)

        if user.is_vsre_staff: 
            return Service.objects.filter(staff=user, is_deleted=False)

    # CREATE WITH OWNER
    def perform_create(self, serializer):
        user = self.request.user
        if not user.is_owner:
            raise PermissionDenied("Only owners can create services.")
        serializer.save(owner=user, is_active=True)

    # SOFT DELETE   
    def perform_destroy(self, instance):
        if hasattr(instance, "soft_delete"):
            instance.soft_delete()
        else:
            instance.delete()
    
    @action(detail=False, methods=["get"])
    def service_dropdown(self,request):
        queryset = self.filter_queryset(self.get_queryset())
        return Response(ServiceDropdownSerializer(queryset,many=True).data)
    
    @action(detail=True, methods=["get"])
    def venues(self,request,pk):
        queryset = self.get_object()
        return Response(ServiceDropdownSerializer(queryset).data)
    

class EntityAssignUsersAPI(views.APIView):
    permission_classes = [IsAuthenticated, CanAssignUsers]

    # ENTITY → (Model, MiniSerializer)
    ENTITY_MODELS = {
        "venue": (Venue, VenueMiniSerializer),
        "service": (Service, ServiceMiniSerializer),
        "resource": (Resource, ResourceMiniSerializer),
    }

    # -------------------------------------------------------
    # POST → Assign managers + staff to entity
    # -------------------------------------------------------
    def post(self, request, entity_type):
        user = request.user
        entity_id = request.data.get("entity_id", None)
        # Detect entity + serializer
        meta = self.ENTITY_MODELS.get(entity_type)
        if not meta:
            return Response({"error": "Invalid entity type"}, status=400)

        model, _ = meta

        entity = get_object_or_404(model, id=entity_id)

        # Extract data
        manager_ids = request.data.get("manager_ids", [])
        staff_ids = request.data.get("staff_ids", [])

        # Pre-fetch
        managers = CustomUser.objects.filter(
            id__in=manager_ids,
            user_type__in=["VSRE_MANAGER", "LINE_MANAGER"]
        )
        staff_members = CustomUser.objects.filter(
            id__in=staff_ids,
            user_type="VSRE_STAFF"
        )

        # Permission checks
        try:
            validate_users_exist(manager_ids, staff_ids)
            if user.is_owner:
                validate_owner_permissions(user, managers, staff_members)

            elif user.is_manager:
                validate_manager_permissions(user, entity, manager_ids, staff_members)

            else:
                raise PermissionError("Not allowed")

        except PermissionError as e:
            return Response({"error": str(e)}, status=403)

        # Assign managers
        if manager_ids:
            entity.manager.set(managers)

            # Auto-assign staff under these managers
            auto_staff = auto_assign_staff(manager_ids)
            staff_members = (staff_members | auto_staff).distinct()

        # Assign staff
        entity.staff.set(staff_members)
        entity.save()

        return Response({
            "message": f"Users assigned successfully to {entity_type}",
            "entity_id": entity.id,
            "assigned_managers": managers.values("id", "first_name", "last_name"),
            "assigned_staff": staff_members.values("id", "first_name", "last_name"),
        })

    # -------------------------------------------------------
    # GET → Show assigned + assignable entities for a user
    # -------------------------------------------------------
    def get(self, request, entity_type):
        request_user = request.user

        # Detect entity + serializer
        meta = self.ENTITY_MODELS.get(entity_type)
        if not meta:
            return Response({"error": "Invalid entity type"}, status=400)

        model, MiniSerializer = meta

        qs = model.objects.filter(is_active=True)

        if request_user.is_owner:
            qs = qs.filter(owner=request_user)

        elif request_user.is_manager:
            qs = qs.filter(managers=request_user)

        else:
            return Response({"error": "Not allowed"}, status=403)

        assignable_data = MiniSerializer(qs, many=True).data

        return Response({
            "entity_type": entity_type,
            "assignable_entities": assignable_data,
        })
