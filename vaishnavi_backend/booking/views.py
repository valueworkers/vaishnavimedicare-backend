from venue_manager.models import Venue, Service, Resource
from venue_manager.serializers import (
    VenueSerializer,
    ServiceSerializer,
    VenueDropdownSerializer,
    ServiceDropdownSerializer
)
import calendar
from datetime import date
from rest_framework.exceptions import ValidationError

from .utils import (
    DateParser, SecondaryOrderHelper,MonthAvailabilityChecker
)
from rest_framework import viewsets, permissions, status
from .serializers import *
from .constants import RAZORPAY_CLIENT
from .models import *
from .filters import EntityFilter
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.utils.dateparse import parse_datetime
from itertools import groupby
from django.db.models import Sum,Count,Q,Prefetch,F
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import razorpay, hmac, hashlib, json
from decimal import Decimal
from django.http import JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404



class PublicVenueViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Single API for:
      - GET /venues/          → list venues with filters
      - GET /venues/<id>/     → venue details
    """
    serializer_class = VenueSerializer
    permission_classes = [permissions.AllowAny]
    
    lookup_field = "pk"
    queryset = Venue.objects.filter(is_deleted=False, is_active=True).order_by("id")

    filterset_fields = {
        "location__city": ["iexact", "icontains"],
        "location__state": ["iexact", "icontains"],
        "capacity": ["gte", "lte", "exact"],
        "price_per_event": ["gte", "lte"],
        "rooms": ["gte", "lte"],
        "floors": ["gte", "lte"],
        "external_decorators_allow": ["iexact"],
        "external_caterers_allow": ["iexact"],
    }

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
    @action(detail=False, methods=["get"])
    def venue_dropdown(self,request):
        queryset = self.filter_queryset(self.get_queryset())
        return Response(VenueDropdownSerializer(queryset,many=True).data)

class PublicServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Single API for:
      - GET /services/          → list services with filters
      - GET /services/<id>/     → service details
    """
    serializer_class = ServiceSerializer
    permission_classes = [permissions.AllowAny]
    
    filterset_class = EntityFilter
    lookup_field = "pk"

    queryset = Service.objects.filter(is_deleted=False, is_active=True).order_by("id")

    filterset_fields = {
        "city": ["iexact", "icontains"],
    }

    search_fields = [
        "venue__name",
        "name",
        "description",
        "address",
        "city",
        "contact",
        "website",
        "tags",
        "quick_info"
    ]
    @action(detail=False, methods=["get"])
    def service_dropdown(self,request):
        queryset = self.filter_queryset(self.get_queryset())
        return Response(ServiceDropdownSerializer(queryset,many=True).data)

class ContactBookingViewSet(viewsets.ModelViewSet):
    queryset = ContactBooking.objects.select_related(
        'patient', 'booked_by', 'service'
    ).all()
    serializer_class = ContactBookingSerializer

    def perform_create(self, serializer):
        serializer.save(booked_by=self.request.user)

class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all()
    serializer_class = PatientSerializer
    
    # Simple filtering
    filterset_fields = [
        "gender",
        "blood_group",
        "registered_by",
        "registration_date",
        "is_registration_fees_paid",
        "is_deleted",
        "is_active",
    ]

    # Search 
    search_fields = [
        "id",
        "registered_by__first_name",
        "registered_by__first_name",
        "registered_by__email",
        "registered_by__mobile_number",
        "patient_id",
        "first_name",
        "last_name",
        "email",
        "phone",
        "address",
        "emergency_contact",
        "emergency_phone",
        "emergency_contact_2",
        "emergency_phone_2",
        "registration_date",
    ]

    # Ordering
    ordering_fields = [
        "registration_date",
        "first_name",
        "age",
        "registration_fee",
    ]

    ordering = ['-registration_date']

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.is_owner:
            return Patient.objects.filter(is_deleted=False)
        
        # Manager/Staff/customer → only their own patients
        return Patient.objects.filter(registered_by=user, is_deleted=False)
    
    def perform_create(self, serializer):
        """
        Set registered_by = request.user automatically
        """
        serializer.save(registered_by=self.request.user,is_active=True)

    def perform_destroy(self, instance):
        if hasattr(instance, "soft_delete"):
            instance.soft_delete()
        else:
            instance.delete()

    @action(detail=True, methods=["patch"], url_path="active-status")
    def active_status(self, request, pk=None):
        """
        PATCH /patients/{id}/active-status/
        Body: {"is_active": true}  or  {"is_active": false}
        """
        patient = self.get_object()
        is_active = request.data.get("is_active")

        if is_active is None or not isinstance(is_active, bool):
            return Response(
                {"detail": "'is_active' (boolean) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        patient.is_active = is_active
        patient.save(update_fields=["is_active", "updated_at"])

        return Response(
            {
                "status": patient.is_active,
            },
            status=status.HTTP_200_OK,
        )
    
    @action(detail=False, methods=["get"])
    def patient_dropdown(self, request):
        queryset = self.filter_queryset(self.get_queryset())

        queryset = queryset.select_related("registered_by").only(
            "id", "first_name", "last_name", "phone",
            "registered_by__id", "registered_by__first_name", "registered_by__last_name",
        )

        data = [
            {
                "id": obj.id,
                "name": obj.get_full_name(),
                "phone": obj.phone,
                "registered_by": obj.registered_by.get_full_name() if obj.registered_by_id else None,
            }
            for obj in queryset
        ]

        return Response(data, status=status.HTTP_200_OK)


class PatientDocumentViewSet(viewsets.ModelViewSet):
    """
    list:     GET    /patients/documents/
    create:   POST   /patients/documents/
    retrieve: GET    /patients/documents/<pk>/
    update:   PUT    /patients/documents/<pk>/
    partial:  PATCH  /patients/documents/<pk>/
    destroy:  DELETE /patients/documents/<pk>/
    """

    serializer_class = PatientDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]
    
    search_fields = [
        'title',
        'remarks',
        'uploaded_by__first_name',
        'uploaded_by__last_name',
        'uploaded_by__email',
        'patient__first_name',
        'patient__last_name',
        'patient__email',
        'patient__phone',
        'patient__patient_id',
    ]

    filterset_fields = {
        'patient': ['exact'],
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
        'patient',
    ]
    ordering = ['-created_at']
    

    def get_queryset(self):
        return (
            PatientDocument.objects
            .select_related("uploaded_by")
            .prefetch_related("files")
        )

    def perform_create(self, serializer):
        document = serializer.save(
            uploaded_by=self.request.user,
        )
        files = self.request.FILES.getlist("files")
        PatientDocumentFile.objects.bulk_create([
            PatientDocumentFile(document=document, file=f) for f in files
        ])

    def perform_update(self, serializer):
        document = serializer.save()
        files = self.request.FILES.getlist("files")
        if files:
            PatientDocumentFile.objects.bulk_create([
                PatientDocumentFile(document=document, file=f) for f in files
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

class LocationViewSet(viewsets.ModelViewSet):
    serializer_class = LocationSerializer

    filterset_fields = ["location_type","user__first_name","user__email","user__mobile_number", "city", "state"]
    search_fields = [
        "user__first_name",
        "user__email",
        "user__mobile_number",
        "building_name",
        "address_line1",
        "locality",
        "city",
        "state",
        "postal_code",
    ]
    
    def get_queryset(self):
        user = self.request.user

        # Admin → see all locations
        if user.is_superuser:
            qs = Location.objects.all()
        else:
            qs = Location.objects.filter(user=user)

        return qs.order_by("-id")
    
    def perform_create(self, serializer):
        # Automatically set the user to the requesting user
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        # Ensure user cannot be changed on update
        serializer.save(user=self.request.user)

class PackageViewSet(viewsets.ModelViewSet):
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    filterset_fields = ['package_type', 'is_active', 'owner', 'content_type__model']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'price', 'name', 'registration_fees']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return PackageCreateSerializer
        return PackageSerializer

    def get_queryset(self):
        user = self.request.user
        # Owners can only see their own packages, staff can see all
        if user.is_superuser:
            return Package.objects.all()
        elif user.is_owner:
            return Package.objects.filter(owner=user)
        elif user.is_vsre_staff:
            return Package.objects.filter(owner=user.hierarchy.owner)
        return Package.objects.none()

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer):
        if not self.request.user.is_owner:
            return Response(
                {'detail': 'You do not have permission to update this package.'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer.save()

    def perform_destroy(self, instance):
        if not self.request.user.is_owner:
            return Response(
                {'detail': 'You do not have permission to delete this package.'},
                status=status.HTTP_403_FORBIDDEN
            )
        instance.delete()

    @action(detail=False, methods=['get'])
    def by_type(self, request):
        """Filter packages by type"""
        pkg_type = request.query_params.get('type')
        if not pkg_type:
            return Response(
                {'error': 'type parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        packages = self.get_queryset().filter(package_type=pkg_type)
        serializer = self.get_serializer(packages, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_belongs_to(self, request):
        """
        Examples:

        /booking/packages/by_belongs_to/?entity=venue
            -> returns all venues (id, name)

        /booking/packages/by_belongs_to/?entity=venue&id=3
            -> returns packages of venue 3
        """

        content_type_name = request.query_params.get("entity")
        object_id = request.query_params.get("id")

        if not content_type_name:
            return Response(
                {"error": "content_type is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ENTITY_MAP = {
            "venue": Venue,
            "service": Service,
            "resource": Resource,
        }

        content_type_name = content_type_name.lower()

        if content_type_name not in ENTITY_MAP:
            return Response(
                {"error": "content_type must be venue, service, or resource"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Model = ENTITY_MAP[content_type_name]

        # CASE 1 → Only content_type → return entities (Service + Venue)
        if not object_id:
            queryset = Model.objects.filter(owner=request.user)

            data = queryset.values("id", "name")

            return Response(data)

        # CASE 2 → content_type + object_id → return packages
        try:
            obj = Model.objects.get(
                id=object_id,
            )
        except Model.DoesNotExist:
            return Response(
                {"error": f"{content_type_name.title()} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # GenericRelation
        packages = obj.packages.all()

        serializer = PackageSerializer(packages, many=True)
        return Response(serializer.data)

class OrderViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing primary orders.

    Handles:
    - Creating venue bookings with full-range OR specific date/slot selection
    - Adding service bookings as TernaryOrders
    - Cancelling orders (cascades to Secondary & Ternary)
    - Rescheduling orders (regenerates sub-orders)
    """

    search_fields = [
        'patient__id',
        'patient__patient_id',
        'patient__phone',
        'patient__phone',
        'patient__email',
        'patient__first_name',
        'patient__last_name',
        'user__first_name',
        'user__last_name',
        'booking_entity',
        'status'
    ]
    filterset_fields = {
        'patient': ['exact'],
        'package': ['exact'],
        'booking_type': ['exact'],
        'status': ['exact'],
    }
    ordering_fields = ['user', 'patient', 'created_at', 'start_datetime', 'end_datetime','total_bill']
    ordering = ['-created_at']

    # ── Queryset ───────────────────────────────────────────────────────────────
    def get_queryset(self):
        queryset = (
            PrimaryOrder.objects.select_related(
                'patient', 'venue', 'service', 'package', 'user'
            )
            .prefetch_related(
                Prefetch(
                    'secondary_orders',
                    queryset=SecondaryOrder.objects.exclude(
                        status__in=(BookingStatus.LOBBY, BookingStatus.HOLD)
                    ).prefetch_related('ternary_orders')
                )
            )
            .exclude(status__in=(BookingStatus.LOBBY, BookingStatus.HOLD))
        )

        user = self.request.user
        if user.is_customer:
            queryset = queryset.filter(user=user)

        now = timezone.now()

        if start_date := self.request.query_params.get('start_date'):
            queryset = queryset.filter(start_datetime__gte=start_date)

        if end_date := self.request.query_params.get('end_date'):
            queryset = queryset.filter(start_datetime__lte=end_date)

        if self.request.query_params.get('upcoming'):
            queryset = queryset.filter(start_datetime__gt=now)

        if self.request.query_params.get('ongoing'):
            queryset = queryset.filter(start_datetime__lte=now, end_datetime__gte=now)

        # REMOVED: duplicate 'upcoming' filter block that was here

        if self.request.query_params.get('past_order'):
            queryset = queryset.filter(end_datetime__lt=now)

        service_id = self.request.query_params.get('service_id')
        if service_id:
            queryset = queryset.filter(service=service_id)

        return queryset


    # ── Serializer ─────────────────────────────────────────────────────────────
    def get_serializer_class(self):
        if self.action in ('create', 'update'):
            return PrimaryOrderCreateSerializer
        return PrimaryOrderSerializer

    # ── Create ─────────────────────────────────────────────────────────────────
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data
        validated['user'] = request.user
        raw_dates = validated.get('raw_dates', [])
        package = validated['package']

        parsed_dates = None
        try:
            if raw_dates:
                parsed_dates = DateParser.parse_dates(package.period, raw_dates)
                start_dt, end_dt = DateParser.extract_datetime_bounds(package.period, parsed_dates)
                validated['start_datetime'] = start_dt
                validated['end_datetime'] = end_dt
        except ValidationError as e:
            return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)

        validated['status'] = BookingStatus.LOBBY
               
        primary_order = serializer.save()
        patient = primary_order.patient

        secondary_status = BookingStatus.LOBBY 

        if not patient.is_registration_fees_paid and package.registration_fees > 0:
            SecondaryOrder.objects.create(
                primary_order=primary_order,
                start_datetime=primary_order.start_datetime,
                end_datetime=primary_order.start_datetime,
                subtotal=package.registration_fees,
                is_registration_fee=True,
                status=secondary_status or auto_update_status(
                    primary_order.start_datetime, primary_order.start_datetime
                ),
            )

        try:
            
            if parsed_dates is not None:
                primary_order.generate_secondary_from_random_dates(
                    parsed_dates,
                    secondary_status=secondary_status
                )
            else:
                primary_order.generate_secondary_full_range_dates(
                    secondary_status=secondary_status
                )
        except ValidationError as e:
            return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            PrimaryOrderSerializer(primary_order).data,
            status=status.HTTP_201_CREATED,
        )

    # ── Update ─────────────────────────────────────────────────────────────────
    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """
        Update PrimaryOrder and regenerate SecondaryOrders if schedule changes.
        """
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        validated = serializer.validated_data
        raw_dates = request.data.get("dates")
        package = validated.get('package', instance.package)
        is_customer = request.user.is_customer

        # Detect what changed — drives secondary regeneration
        package_changed = 'package' in validated and validated['package'] != instance.package
        dates_changed = bool(raw_dates) or 'start_datetime' in request.data or 'end_datetime' in request.data
        needs_regeneration = dates_changed or package_changed

        # Parse dates ONCE and reuse
        parsed_dates = None
        try:
            if raw_dates:
                parsed_dates = DateParser.parse_dates(package.period, raw_dates)
                start_dt, end_dt = DateParser.extract_datetime_bounds(package.period, parsed_dates)
                validated["start_datetime"] = start_dt
                validated["end_datetime"] = end_dt
        except ValidationError as e:
            return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)

        # Primary status is always auto
        if needs_regeneration and parsed_dates is None:
            start_dt = validated.get('start_datetime', instance.start_datetime)
            end_dt = validated.get('end_datetime', instance.end_datetime)
            validated['status'] = auto_update_status(start_dt, end_dt)

        primary_order = serializer.save()

        # Secondary status depends on who is updating
        secondary_status = BookingStatus.LOBBY if is_customer else None  # None = auto inside generator

        if needs_regeneration:
            try:
                primary_order.secondary_orders.all().delete()

                if parsed_dates is not None:
                    primary_order.generate_secondary_from_random_dates(
                        parsed_dates,
                        secondary_status=secondary_status,
                    )
                    primary_order.status = auto_update_status(
                        primary_order.start_datetime,
                        primary_order.end_datetime,
                    )
                    primary_order.save(update_fields=["status"])
                else:
                    primary_order.generate_secondary_full_range_dates(
                        secondary_status=secondary_status,
                    )
            except ValidationError as e:
                return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            PrimaryOrderSerializer(primary_order).data,
            status=status.HTTP_200_OK
        )
    # ── Add service (TernaryOrder) ──────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def add_service(self, request, pk=None):
        """
        Add a service as a TernaryOrder under the appropriate SecondaryOrder.

        Payload:
        {
            "venue": 13,
            "service": 5,
            "package": 2,
            "start_datetime": "2026-02-05T10:00:00Z",
            "end_datetime": "2026-02-05T11:00:00Z",
            "discount_amount": "100.00",
            "premium_amount": "50.00"
        }
        """
        primary_order = self.get_object()
        user = request.user

        # # Permission Check
        # if not PermissionHelper.can_modify_order(user, primary_order):
        #     return Response(
        #         {"detail": "You do not have permission to modify this order."},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        if primary_order.status == BookingStatus.CANCELLED:
            return Response(
                {"message": "Cannot add a service to a cancelled order."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = TernaryOrderCreateSerializer(
            data=request.data,
            context={"primary_order": primary_order}
        )
        serializer.is_valid(raise_exception=True)

        start_dt = serializer.validated_data['start_datetime']
        end_dt = serializer.validated_data['end_datetime']

        # Resolve the matching SecondaryOrder - FIX: Use helper method with proper exception
        try:
            secondary_order = SecondaryOrderHelper.get_matching_secondary_order(
                primary_order, start_dt, end_dt
            )
        except SecondaryOrder.DoesNotExist as e:
            return Response(
                {"message": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        ternary_order = serializer.save(secondary_order=secondary_order)

        # Recalculate subtotals up the chain
        secondary_order.recalculate_subtotal()
        primary_order.recalculate_total()

        response_serializer = TernaryOrderSerializer(ternary_order)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    # ── Reschedule Order ───────────────────────────────────────────────────────
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def reschedule_order(self, request, pk=None):
        """
        Reschedule a PrimaryOrder with new dates/package.
        
        Two modes:
        - Full range: start_datetime + end_datetime
        - Specific dates: dates (list for DAILY, dict for HOURLY)
        """
        primary_order = self.get_object()
        user = request.user

        # FIX: Add missing permission check
        if not PermissionHelper.can_modify_order(user, primary_order):
            return Response(
                {"detail": "You do not have permission to modify this order."},
                status=status.HTTP_403_FORBIDDEN
            )

        new_package_id = request.data.get("package")
        discount_amount = Decimal(request.data.get("discount_amount", "0"))
        premium_amount = Decimal(request.data.get("premium_amount", "0"))
        raw_dates = request.data.get("dates")

        # Determine package & period type        
        package = primary_order.package
        if new_package_id:
            from .models import Package
            package = Package.objects.get(id=new_package_id)

        period_type = package.period

        try:
            # MODE 1: Specific Dates / Slots
            if raw_dates:
                try:
                    parsed = DateParser.parse_dates(period_type, raw_dates)
                    new_start, new_end = DateParser.extract_datetime_bounds(period_type, parsed)
                except ValidationError as e:
                    return Response(e.message_dict, status=status.HTTP_400_BAD_REQUEST)

                primary_order.reschedule(
                    new_start,
                    new_end,
                    new_package_id,
                    discount_amount,
                    premium_amount,
                )

                # Delete auto-generated ones
                primary_order.secondary_orders.all().delete()

                # Generate specific ones
                primary_order.generate_secondary_from_random_dates(parsed)

            # MODE 2: Full Range
            else:
                new_start_raw = request.data.get("start_datetime")
                new_end_raw = request.data.get("end_datetime")

                if not new_start_raw or not new_end_raw:
                    raise ValidationError(
                        {"detail": "'start_datetime' and 'end_datetime' are required."}
                    )

                new_start = parse_datetime(new_start_raw)
                new_end = parse_datetime(new_end_raw)

                if not new_start or not new_end:
                    raise ValidationError(
                        {"detail": "Invalid datetime format."}
                    )

                if timezone.is_naive(new_start):
                    new_start = timezone.make_aware(new_start)
                if timezone.is_naive(new_end):
                    new_end = timezone.make_aware(new_end)

                primary_order.reschedule(
                    new_start,
                    new_end,
                    new_package_id,
                    discount_amount,
                    premium_amount,
                )

        except ValidationError:
            raise
        except Exception as e:
            return Response(
                {"detail": f"Invalid input: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PrimaryOrderSerializer(primary_order)
        return Response(serializer.data)

    # ── Reschedule Service ─────────────────────────────────────────────────────
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def reschedule_service(self, request, pk=None):
        """
        Reschedule a single TernaryOrder and recalculate parent totals.

        Payload:
        {
            "ternary_order_id": 5,
            "start_datetime": "2026-02-10T10:00:00Z",
            "end_datetime": "2026-02-10T12:00:00Z",
            "package": 2,               # optional
            "discount_amount": 0.0,     # optional
            "premium_amount": 0.0       # optional
        }
        """
        primary_order = self.get_object()
        user = request.user

        # Add permission check for consistency
        if not PermissionHelper.can_modify_order(user, primary_order):
            return Response(
                {"detail": "You do not have permission to modify this order."},
                status=status.HTTP_403_FORBIDDEN
            )

        ternary_order_id = request.data.get('ternary_order_id')
        new_start = request.data.get('start_datetime')
        new_end = request.data.get('end_datetime')
        new_package = request.data.get('package')
        discount_amount = request.data.get('discount_amount', Decimal('0'))
        premium_amount = request.data.get('premium_amount', Decimal('0'))

        if not new_start or not new_end:
            return Response(
                {"message": "'start_datetime' and 'end_datetime' are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            ternary_order = TernaryOrder.objects.get(
                id=ternary_order_id,
                secondary_order__primary_order=primary_order
            )
        except TernaryOrder.DoesNotExist:
            return Response(
                {"message": "Service (TernaryOrder) not found under this order."},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            new_start_dt = parse_datetime(new_start)
            new_end_dt = parse_datetime(new_end)

            if not new_start_dt or not new_end_dt:
                raise ValueError("Invalid datetime format.")

            with transaction.atomic():
                ternary_order.start_datetime = new_start_dt
                ternary_order.end_datetime = new_end_dt

                if new_package:
                    ternary_order.package_id = new_package
                    ternary_order.status = BookingStatus.MODIFIED
                else:
                    ternary_order.status = BookingStatus.RESCHEDULED
                
                # FIX: Changed 'target' to 'ternary_order' (was undefined variable)
                ternary_order.status_locked = True

                if discount_amount is not None:
                    ternary_order.discount_amount = discount_amount
                if premium_amount is not None:
                    ternary_order.premium_amount = premium_amount
                
                ternary_order.save()

                ternary_order.secondary_order.recalculate_subtotal()
                primary_order.recalculate_total()

        except ValidationError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError) as e:
            return Response(
                {"message": f"Invalid input: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = TernaryOrderSerializer(ternary_order)
        return Response(serializer.data)

    # ── Status Change ──────────────────────────────────────────────────────────
    @action(detail=True, methods=['patch'])
    @transaction.atomic
    def change_status(self, request, pk=None):
        """
        Manually change the status of a PrimaryOrder and optionally cascade to children.

        Payload:
        {
            "status": "CONFIRMED",
            "secondary_order_id": 3,  # optional — targets a specific SecondaryOrder
            "ternary_order_id": 5     # optional — targets a specific TernaryOrder
        }
        """
        primary_order = self.get_object()
        user = request.user

        # Add permission check
        if user.is_customer:
            return Response(
                {"detail": "You do not have permission to modify this order."},
                status=status.HTTP_403_FORBIDDEN
            )

        secondary_order_id = request.data.get('secondary_order_id')
        ternary_order_id = request.data.get('ternary_order_id')
        new_status = request.data.get('status')

        if not new_status:
            return Response(
                {"error": "Status is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if new_status not in BookingStatus.values:
            return Response(
                {"error": "Invalid status."},
                status=status.HTTP_400_BAD_REQUEST
            )

        target = primary_order

        if secondary_order_id:
            try:
                target = SecondaryOrder.objects.get(
                    id=secondary_order_id,
                    primary_order=primary_order
                )
            except SecondaryOrder.DoesNotExist:
                return Response(
                    {"error": "Invalid secondary_order_id."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        if ternary_order_id:
            try:
                target = TernaryOrder.objects.get(
                    id=ternary_order_id,
                    secondary_order__primary_order=primary_order
                )
            except TernaryOrder.DoesNotExist:
                return Response(
                    {"error": "Invalid ternary_order_id."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        with transaction.atomic():
            target.status = new_status
            target.status_locked = True
            target.save(update_fields=['status', 'status_locked'])

            # Use helper for consistent cascade logic
            SecondaryOrderHelper.cascade_status_change(
                primary_order,
                new_status,
                specific_secondary_id=secondary_order_id,
                specific_ternary_id=ternary_order_id
            )

        return Response({
            "message": "Status updated successfully.",
            "order_id": target.id,
            "new_status": new_status
        }, status=status.HTTP_200_OK)

    # ── Info Endpoints ────────────────────────────────────────────────────────
    @action(detail=False, methods=['get'])
    def by_venue(self, request):
        """List all venue PrimaryOrders with nested secondary/ternary data."""
        queryset = self.get_queryset().filter(booking_entity=BookingEntity.VENUE)
        serializer = PrimaryOrderSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def by_service(self, request):
        """List all service PrimaryOrders."""
        queryset = self.get_queryset().filter(booking_entity=BookingEntity.SERVICE)
        serializer = PrimaryOrderSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def order_info(self, request, pk=None):
        """Full breakdown of a PrimaryOrder including all secondary and ternary orders."""
        primary_order = self.get_object()
        serializer = PrimaryOrderSerializer(primary_order)
        return Response(serializer.data)

class LobbyOrderViewSet(viewsets.ModelViewSet):
    search_fields = [
        'patient__first_name',
        'patient__last_name',
        'user__first_name',
        'user__last_name',
        'booking_entity',
        'status'
    ]
    filterset_fields = {
        'patient': ['exact'],
        'package': ['exact'],
        'booking_type': ['exact'],
        'status': ['exact'],
    }
    ordering_fields = ['user', 'patient', 'created_at', 'start_datetime', 'end_datetime']
    ordering = ['-created_at']
    
    def get_queryset(self):
        return (
            PrimaryOrder.objects.filter(
                secondary_orders__status__in=(BookingStatus.LOBBY, BookingStatus.HOLD)
            )
            .select_related(
                'patient', 'venue', 'service', 'package', 'user'
            )
            .prefetch_related(
                Prefetch(
                    'secondary_orders',
                    queryset=SecondaryOrder.objects.filter(
                        status__in=(BookingStatus.LOBBY, BookingStatus.HOLD)
                    ).prefetch_related('ternary_orders')
                )
            )
            .distinct()
        )
    
    def get_serializer_class(self):
        if self.action == 'bulk_action':
            return SecondaryBulkActionSerializer
        return PrimaryOrderSerializer


    @action(detail=True, methods=["post"], url_path="bulk-action")
    @transaction.atomic
    def bulk_action(self, request, pk=None):

        primary_order = self.get_object()

        BULK_ALLOWED_ACTIONS = {
            "APPROVE": BookingStatus.BOOKED,
            "REJECT":  BookingStatus.CANCELLED,
            "HOLD":    BookingStatus.HOLD,
        }

        serializer = SecondaryBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ids    = serializer.validated_data.get("ids", None)
        action = serializer.validated_data.get("action", None)
        notify = serializer.validated_data.get("notify_customer", False)
        reason = serializer.validated_data.get("reason", "")

        new_status = BULK_ALLOWED_ACTIONS[action]

        # --- Bulk update --------------------------------------------------

        secondary_qs = SecondaryOrder.objects.filter(
            id__in=ids,
            primary_order=primary_order,
        ).select_for_update()   # lock rows inside the atomic block

        if not secondary_qs.exists():
            return Response(
                {"detail": "No matching secondary orders found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        if action == "APPROVE":
            for order in secondary_qs:
                order.status = auto_update_status(order.start_datetime, order.end_datetime)
                order.save(update_fields=["status"])
            primary_order.status = auto_update_status(
                primary_order.start_datetime, primary_order.end_datetime
            )
            primary_order.save(update_fields=["status"])
        else:
            secondary_qs.update(
                status=new_status,
                updated_at=timezone.now(),
            )

        if notify:
            pass
            # send sms mail or whatsapp text

        primary_order.refresh_from_db()
        return Response(
            PrimaryOrderSerializer(primary_order).data,
            status=status.HTTP_200_OK,
        )

class TotalInvoiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing invoices.
        
    Handles:
    - Manual invoice creation for specific periods
    - Retrieving invoice details and payments
    - Manual recalculation endpoints
    """
  
    queryset = TotalInvoice.objects.select_related(
        'secondary_order__primary_order__venue__location',
        'secondary_order__primary_order__service',
        'secondary_order__primary_order__package',
        'ternary_order__venue__location',
        'ternary_order__service',
        'ternary_order__package',
        'user',
        'patient',
    ).prefetch_related('payments')

    serializer_class = TotalInvoiceSerializer
    search_fields = [
        'invoice_number',
        'patient__id',
        'patient__patient_id',
        'patient__phone',
        'patient__phone',
        'patient__email',
        'patient__first_name',
        'patient__last_name',
        'user__first_name',
        'user__last_name',
        'status'
    ]
    
    filterset_fields = {
        'patient': ['exact'],
        'period_start': ['gte'],
        'period_end': ['lte'],
        'secondary_order__primary_order__booking_type': ['exact'],
        'ternary_order__booking_type': ['exact'],
        'status': ['exact'],
    }

    ordering_fields = [
        'user', 'patient', 'created_at', 'period_start', 'period_end',
        'issued_date', 'status', 'total_amount'
    ]
    ordering = ['-created_at']
    
      # ── Constants ──────────────────────────────────────────────────────────────

    FY_START_MONTH = 4

    # ── FY helpers ─────────────────────────────────────────────────────────────

    def _get_fy_range(self, fy_year):
        """
        FY2025 = Apr 2024 → Mar 2025
        Returns (start_year, start_month, end_year, end_month)
        """
        return (fy_year - 1, self.FY_START_MONTH, fy_year, self.FY_START_MONTH - 1)

    def _current_fy(self):
        today = date.today()
        return today.year if today.month < self.FY_START_MONTH else today.year + 1

    def _cy_to_fy(self, cy_year, cy_month):
        return cy_year + 1 if cy_month >= self.FY_START_MONTH else cy_year

    # ── Filter parsers ─────────────────────────────────────────────────────────

    def _parse_filters(self, request):
        """
        Parse year / month / year_type from query params.
        month=0 → all months.
        """
        year_param      = request.query_params.get("year")
        month_param     = request.query_params.get("month")
        year_type_param = request.query_params.get("year_type", "CY").upper()

        if year_type_param not in ("CY", "FY"):
            raise ValidationError("year_type must be 'CY' or 'FY'.")

        if not year_param:
            year = self._current_fy() if year_type_param == "FY" else date.today().year
        else:
            try:
                year = int(year_param)
            except ValueError:
                raise ValidationError("Year must be a valid integer.")

        if month_param:
            try:
                month = int(month_param)
            except ValueError:
                raise ValidationError("Month must be a valid integer between 1 and 12.")
            if not 1 <= month <= 12:
                raise ValidationError("Month must be between 1 and 12.")
        else:
            month = 0

        return year, month, year_type_param

    def _apply_period_filter(self, queryset):
        year, month, year_type = self._parse_filters(self.request)

        if year_type == "FY":
            start_year, start_month, end_year, end_month = self._get_fy_range(year)
            if month == 0:
                queryset = queryset.filter(
                    period_end__gte=date(start_year, start_month, 1),
                    period_end__lte=date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
                )
            else:
                cy_year = start_year if month >= self.FY_START_MONTH else end_year
                queryset = queryset.filter(
                    period_end__year=cy_year,
                    period_end__month=month
                )
        else:
            # CY
            if month == 0:
                queryset = queryset.filter(period_end__year=year)
            else:
                queryset = queryset.filter(
                    period_end__year=year,
                    period_end__month=month
                )

        return queryset


    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        # Filter by customer
        if user.is_customer:
            queryset = queryset.filter(Q(patient__registered_by=user)|Q(user=user))

        return self._apply_period_filter(queryset)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        allowed_ordering = {
            'registration_date', '-registration_date',
            'total_invoice_amount', '-total_invoice_amount',
            'total_paid', '-total_paid',
            'total_balance', '-total_balance',
            'patient_name', '-patient_name',
        }
        ordering_param = request.query_params.get('ordering')

        groups = (
            queryset
            .values('user_id', 'patient_id')
            .annotate(
                total_invoice_amount=Sum('total_amount'),
                total_paid=Sum('paid_amount'),
                total_balance=Sum('remaining_amount'),
                patient_name=F('patient__first_name'),  # only if you want to order by name
            )
        )
        if ordering_param in allowed_ordering:
            groups = groups.order_by(ordering_param)
        else:
            groups = groups.order_by('user_id', 'patient_id')

        page = self.paginate_queryset(list(groups))
        active_groups = page if page is not None else list(groups)

        if not active_groups:
            grouped_data = []
        else:
            pair_filter = Q()
            for g in active_groups:
                pair_filter |= Q(user_id=g['user_id'], patient_id=g['patient_id'])

            invoices = (
                queryset
                .filter(pair_filter)
                .select_related('user', 'patient')
                .order_by('user_id', 'patient_id')
            )

            invoices_by_pair = {}
            for inv in invoices:
                invoices_by_pair.setdefault((inv.user_id, inv.patient_id), []).append(inv)

            grouped_data = []
            for g in active_groups:
                pair = (g['user_id'], g['patient_id'])
                invoices_list = invoices_by_pair.get(pair, [])
                if not invoices_list:
                    continue
                first_invoice = invoices_list[0]
                user = first_invoice.user
                patient = first_invoice.patient

                grouped_data.append({
                    "user_id": user.id,
                    "user_name": user.get_full_name(),
                    "patient_id": patient.id,
                    "patient_name": patient.get_full_name(),
                    "patient_registration_date": patient.registration_date,
                    "patient_phone": patient.phone,
                    "total_invoice_amount": str(g['total_invoice_amount']),
                    "total_paid": str(g['total_paid']),
                    "total_balance": str(g['total_balance']),
                    "invoices": self.serializer_class(invoices_list, many=True).data
                })

        if page is not None:
            return self.get_paginated_response(grouped_data)
        return Response(grouped_data)

 
    @action(detail=True, methods=['get'])
    def recalculate(self, request, pk=None):
        """
        Manually recalculate invoice totals based on current bookings and payments.
        """
        invoice = self.get_object()
        invoice.recalculate_payments()
        
        serializer = TotalInvoiceSerializer(invoice)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def add_payment(self, request, pk=None):
        """
        Add a payment to an invoice.
        When method='WALLET', balance is debited from the customer's wallet atomically.
        """
        from django.db import transaction as db_transaction
        from wallet.models import Wallet

        invoice = self.get_object()

        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        method = data.get('method')

        with db_transaction.atomic():
            if method == PaymentMethod.WALLET:
                wallet = Wallet.objects.select_for_update().get_or_create(user=invoice.user)[0]
                amount = data['amount']
                if not wallet.can_debit(amount):
                    return Response(
                        {'error': f'Insufficient wallet balance. Available: {wallet.balance}, Required: {amount}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                txn = wallet.debit(
                    amount=amount,
                    source_type='ORDER_PAYMENT',
                    reference_id=str(invoice.id),
                    description=f'Payment for invoice {invoice.invoice_number}',
                )
                data = {**data, 'reference': txn.transaction_id, 'is_verified': True}

            payment = Payment.objects.create(
                invoice=invoice,
                patient=invoice.patient,
                **data
            )
            invoice.recalculate_payments()

        payment_serializer = PaymentSerializer(payment)
        return Response(payment_serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def initiate_razorpay(self, request, pk=None):
        """
        Create a Razorpay order for a specific invoice.
        Returns order details needed to open the checkout popup.
        """
        invoice = self.get_object()

        # Don't allow payment on already-paid invoices
        if invoice.status == InvoiceStatus.PAID:
            return Response(
                {'error': 'Invoice is already fully paid.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Use remaining_amount so partial payments work correctly
        amount_paise = int(invoice.remaining_amount * 100)

        if amount_paise <= 0:
            return Response(
                {'error': 'No outstanding balance on this invoice.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order = RAZORPAY_CLIENT.order.create({
            'amount':          amount_paise,
            'currency':        'INR',
            'payment_capture': 1,
            'notes': {
                'invoice_number': invoice.invoice_number,
                'invoice_id':     str(invoice.id),
                'patient':        invoice.patient.get_full_name() if invoice.patient else '',
            }
        })

        return Response({
            'order_id':       order['id'],
            'amount':         amount_paise,
            'currency':       'INR',
            'key_id':         settings.RAZORPAY_KEY_ID,
            'invoice_number': invoice.invoice_number,
            'patient_name':   invoice.patient.get_full_name() if invoice.patient else '',
        })

    @action(detail=True, methods=['post'])
    def verify_razorpay(self, request, pk=None):
        """
        Verify Razorpay signature and record the payment on the invoice.
        On success, creates a verified Payment and recalculates the invoice.
        """
        invoice = self.get_object()

        razorpay_order_id   = request.data.get('razorpay_order_id')
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_signature  = request.data.get('razorpay_signature')

        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            return Response(
                {'error': 'razorpay_order_id, razorpay_payment_id and razorpay_signature are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # HMAC-SHA256 signature verification — never skip this
        msg      = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
        expected = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode(),
            msg, hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, razorpay_signature):
            return Response(
                {'error': 'Payment verification failed. Invalid signature.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch actual amount charged from Razorpay (source of truth)
        rz_payment = RAZORPAY_CLIENT.payment.fetch(razorpay_payment_id)
        amount_paid = Decimal(rz_payment['amount']) / 100  # paise → rupees

        with transaction.atomic():
            payment = Payment.objects.create(
                invoice     = invoice,
                patient     = invoice.patient,
                amount      = amount_paid,
                method      = PaymentMethod.RAZORPAY,
                reference   = razorpay_payment_id,  # overrides the auto-generated PAY-xxx
                is_verified = True,                 # signature verified above
            )
            invoice.recalculate_payments()

        serializer = PaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get invoice summary statistics for the current user."""
        queryset = self.filter_queryset(self.get_queryset())
        total_stats = queryset.aggregate(
            generated_invoices=Count('id'),
            total_amount=Sum('total_amount'),
            paid_amount=Sum('paid_amount'),
            remaining_amount=Sum('remaining_amount'),
            unpaid_count=Count('id', filter=Q(status=InvoiceStatus.UNPAID)),
            partially_paid_count=Count('id', filter=Q(status=InvoiceStatus.PARTIALLY_PAID)),
            paid_count=Count('id', filter=Q(status=InvoiceStatus.PAID))
        )
        
        serializer = InvoiceSummarySerializer(total_stats)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def overdue(self, request):
        """Get all overdue invoices (due_date passed and status not PAID)."""
        today = timezone.now().date()
        overdue_invoices = self.get_queryset().filter(
            due_date__lt=today,
            status__in=['UNPAID', 'PARTIALLY_PAID']
        )
        
        serializer = self.serializer_class(overdue_invoices, many=True)
        return Response(serializer.data)
        
    @action(detail=False, methods=['get'])
    def dropdown(self, request):
        """
        Returns a lightweight list of invoices for use in dropdown/select inputs.
        Supports ?patient=, ?status=, ?search= for filtering.
        """
        queryset = TotalInvoice.objects.select_related(
            'patient'
        ).order_by('-created_at').exclude(status=InvoiceStatus.PAID)

        queryset = self.filter_queryset(queryset)

        serializer = InvoiceDropdownSerializer(queryset, many=True)
        return Response(serializer.data)

class PaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing payments.
        
    Handles:
    - Recording payments
    - Verifying/unverifying payments
    - Tracking payment methods
    """
    search_fields = [
        "reference",
        "method",
        "invoice__id",
        "invoice__invoice_number",
        "patient__first_name",
        "patient__last_name",
        "patient__phone",
        "patient__id",
    ]
    filterset_fields = {
        'invoice_id': ['exact'],
        'is_verified': ['exact'],
        'method': ['exact'],
        'paid_date': ['month', 'year'],
    }
    ordering_fields = ['created_at', 'amount', 'paid_date']
    ordering = ['-created_at']
    
    def get_queryset(self):
        """Get payments for invoices belonging to current user"""
        queryset = Payment.objects.select_related('invoice', 'patient')
        user = self.request.user

        is_mapped = self.request.query_params.get("is_mapped")

        if is_mapped is not None:
            is_mapped = is_mapped.lower() == "true"

            if is_mapped:
                queryset = queryset.filter(
                    patient__isnull=False,
                    invoice__isnull=False,
                )
            else:
                queryset = queryset.filter(
                    Q(patient__isnull=True) |
                    Q(invoice__isnull=True)
                )
                    
        if user.is_customer:
            queryset = queryset.filter(Q(patient__registered_by=user)|Q(user=user))
    
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'create':
            return PaymentCreateSerializer
        return PaymentSerializer
    
    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Create a new payment.
        Invoice status is automatically recalculated.
        """
        invoice_id = request.data.get('invoice_id')
        
        try:
            invoice = TotalInvoice.objects.get(
                id=invoice_id
            )
        except TotalInvoice.DoesNotExist:
            return Response(
                {'error': 'Invoice not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        payment = Payment.objects.create(
            invoice=invoice,
            patient=invoice.patient,
            **serializer.validated_data
        )
                
        output_serializer = PaymentSerializer(payment)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)
    
    @transaction.atomic
    @action(detail=False, methods=['post'], url_path='create-unmapped')
    def create_unmapped_payment(self, request, *args, **kwargs):
        """
        Create an unmapped payment entry.
        Invoice and patient are optional.
        """

        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        invoice = None
        patient = None

        invoice_id = request.data.get('invoice_id')
        patient_id = request.data.get('patient_id')

        # Optional invoice lookup
        if invoice_id:
            try:
                invoice = TotalInvoice.objects.get(id=invoice_id)
                patient = invoice.patient
            except TotalInvoice.DoesNotExist:
                return Response(
                    {'error': 'Invoice not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Optional patient lookup if invoice is not provided
        elif patient_id:
            try:
                patient = Patient.objects.get(id=patient_id)
            except Patient.DoesNotExist:
                return Response(
                    {'error': 'Patient not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

        payment = Payment.objects.create(
            invoice=invoice,
            patient=patient,
            **serializer.validated_data
        )

        output_serializer = PaymentSerializer(payment)

        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=False, methods=['get'], url_path='unmapped-payments')
    def unmapped_payments(self, request):
        """Get all verified payments."""
        queryset = self.get_queryset().filter(
            Q(invoice__isnull=True) | Q(patient__isnull=True)
        )
        queryset = self.filter_queryset(queryset)

        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=['post'], url_path='upfront-payment')
    @transaction.atomic
    def upfront_payment(self, request):
        """
        Accept one lump-sum payment for an entire PrimaryOrder.
        Creates invoices (if not exist) for each SecondaryOrder,
        then splits and maps the payment across them.

        Payload:
        {
            "primary_order_id": 12,
            "amount": "30000",
            "method": "CASH",
            "reference": "REC-2026-001",
            "paid_date": "2026-06-05"
        }
        """
        primary_order_id = request.data.get('primary_order_id')

        if not primary_order_id:
            return Response(
                {'error': 'primary_order_id is required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Validate payment fields via existing serializer ────────────────────
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        amount = validated['amount']
        
        # ── Fetch PrimaryOrder ─────────────────────────────────────────────────
        try:
            primary_order = PrimaryOrder.objects.prefetch_related(
                'secondary_orders'
            ).get(id=primary_order_id)
        except PrimaryOrder.DoesNotExist:
            return Response({'error': 'PrimaryOrder not found.'}, status=status.HTTP_404_NOT_FOUND)

        secondary_orders = primary_order.secondary_orders.exclude(
            status=BookingStatus.CANCELLED
        )

        if not secondary_orders.exists():
            return Response(
                {'error': 'No active secondary orders found for this order.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Get or create invoices per SecondaryOrder ──────────────────────────
        invoices = []
        for secondary in secondary_orders:
            invoice, created = TotalInvoice.objects.get_or_create(
                secondary_order=secondary,
                period_start=secondary.start_datetime,
                period_end=secondary.end_datetime,
                defaults={
                    "patient":          primary_order.patient,
                    "user":             primary_order.user,
                    "subtotal":         secondary.subtotal,
                    "status":           InvoiceStatus.UNPAID
                },
            )

            if not created:
                invoice.subtotal         = secondary.subtotal
                invoice.total_amount     = (
                    invoice.subtotal +
                    invoice.premium_amount +
                    invoice.tax_amount -
                    invoice.discount_amount
                )
                invoice.remaining_amount = max(
                    invoice.total_amount - (invoice.paid_amount or Decimal("0.00")),
                    Decimal("0.00"),
                )
                invoice.save(
                    update_fields=["subtotal", "total_amount", "remaining_amount"]
                )
                
            if invoice.status != InvoiceStatus.PAID:
                invoices.append(invoice)

        if not invoices:
            return Response(
                {'error': 'All invoices for this order are already fully paid.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Validate amount doesn't exceed total remaining ─────────────────────
        total_remaining = sum(inv.remaining_amount for inv in invoices)

        if amount > total_remaining:
            return Response(
                {
                    'error': f'Payment amount {amount} exceeds total outstanding balance {total_remaining}.',
                    'total_remaining': str(total_remaining),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Split and map payment across invoices ──────────────────────────────
        remaining_pot = amount
        created_payments = []

        for invoice in invoices:
            if remaining_pot <= 0:
                break

            amount_for_this = min(invoice.remaining_amount, remaining_pot)
            remaining_pot -= amount_for_this

            payment = Payment.objects.create(
                invoice=invoice,
                patient=invoice.patient,
                **{**validated, 'amount': amount_for_this}  # override amount per invoice
            )
            invoice.recalculate_payments()
            created_payments.append(payment)

        return Response(
            {
                'message': f'{len(created_payments)} payments created successfully.',
                'total_paid': str(amount),
                'payments': PaymentSerializer(created_payments, many=True).data,
            },
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=['patch'], url_path='bulk-map-payments')
    def bulk_map_payments(self, request):
        """
        Bulk map unmapped payments to invoices and patients.

        - Multiple payments can be mapped to the same invoice in one request.
        - Each entry supports an optional `amount` field for partial mapping.
        If provided, only that amount is mapped; the remainder becomes a new
        unmapped payment entry.
        - If the total of mapped payments still exceeds the invoice's remaining
        balance, the excess is trimmed from the last entries first.
        - Trimmed portions are created as new unmapped payment entries.
        """
        data = request.data

        if not isinstance(data, list) or not data:
            return Response(
                {"detail": "Payload must be a non-empty list."},
                status=status.HTTP_400_BAD_REQUEST
            )

        payment_ids = [item.get("id")      for item in data if item.get("id")]
        patient_ids = [item.get("patient") for item in data if item.get("patient")]
        invoice_ids = [item.get("invoice") for item in data if item.get("invoice")]

        # ── Fetch all referenced objects in bulk ───────────────────────────────
        payments = {p.id: p for p in self.get_queryset().filter(id__in=payment_ids)}
        patients = set(Patient.objects.filter(id__in=patient_ids).values_list("id", flat=True))
        invoices = {inv.id: inv for inv in TotalInvoice.objects.filter(id__in=invoice_ids)}

        # ── Validate all IDs exist before touching the DB ──────────────────────
        errors = {}
        missing_payments = set(payment_ids) - payments.keys()
        missing_patients = set(patient_ids) - patients
        missing_invoices = set(invoice_ids) - invoices.keys()

        if missing_payments: errors["payments_not_found"] = sorted(missing_payments)
        if missing_patients: errors["patients_not_found"] = sorted(missing_patients)
        if missing_invoices: errors["invoices_not_found"] = sorted(missing_invoices)

        # ── Validate custom amounts ────────────────────────────────────────────
        amount_errors = {}
        for item in data:
            raw_amount = item.get("amount")
            if raw_amount is None:
                continue
            payment = payments.get(item.get("id"))
            if not payment:
                continue  # already caught above
            try:
                requested = Decimal(str(raw_amount))
            except Exception:
                amount_errors[item.get("id")] = "Invalid amount format."
                continue
            if requested <= 0:
                amount_errors[item.get("id")] = "Amount must be greater than zero."
            elif requested > payment.amount:
                amount_errors[item.get("id")] = (
                    f"Requested amount {requested} exceeds payment amount {payment.amount}."
                )
        if amount_errors:
            errors["invalid_amounts"] = amount_errors

        if errors:
            return Response(errors, status=status.HTTP_404_NOT_FOUND)

        # ── Group request entries by invoice ───────────────────────────────────
        invoice_payment_map = {}
        for item in data:
            payment = payments.get(item.get("id"))
            invoice = invoices.get(item.get("invoice"))
            if not payment or not invoice:
                continue
            group = invoice_payment_map.setdefault(invoice.id, {"invoice": invoice, "entries": []})
            group["entries"].append((item, payment))

        # ── Process & write ────────────────────────────────────────────────────
        updated_payments = []
        new_payments     = []

        def _make_unmapped_copy(payment: Payment, amount: Decimal) -> Payment:
            """Return a new unsaved Payment with no invoice/patient (unmapped remainder)."""
            return Payment(
                amount=amount,
                method=payment.method,
                paid_date=payment.paid_date,
                reference=payment.reference,
                is_verified=payment.is_verified,
                patient=None,
                invoice=None,
            )

        with transaction.atomic():
            for invoice_id, group in invoice_payment_map.items():
                invoice = group["invoice"]
                entries = group["entries"]

                # ── Apply per-entry custom amounts first ───────────────────────
                # If a custom amount is requested, split off the remainder as a
                # new unmapped payment before the invoice-cap logic runs.
                for item, payment in entries:
                    raw_amount = item.get("amount")
                    if raw_amount is None:
                        continue
                    requested = Decimal(str(raw_amount))
                    remainder = payment.amount - requested
                    if remainder > 0:
                        new_payments.append(_make_unmapped_copy(payment, amount=remainder))
                    payment.amount = requested  # trim in-place for cap logic below

                # ── Invoice-cap: trim excess from last entries first ───────────
                total_of_entries    = sum(p.amount for _, p in entries)
                remaining_to_create = total_of_entries - invoice.remaining_amount

                if remaining_to_create > 0:
                    cut = remaining_to_create
                    for item, payment in reversed(entries):
                        if cut <= 0:
                            break
                        deduct         = min(payment.amount, cut)
                        payment.amount -= deduct
                        cut            -= deduct
                        new_payments.append(_make_unmapped_copy(payment, amount=deduct))

                # ── Map trimmed (or untouched) entries to the invoice ──────────
                for item, payment in entries:
                    if payment.amount <= 0:
                        continue
                    payment.patient_id = item.get("patient")
                    payment.invoice_id = invoice_id
                    updated_payments.append(payment)

            Payment.objects.bulk_update(updated_payments, ["patient", "invoice", "amount"])
            Payment.objects.bulk_create(new_payments)

            affected_invoice_ids = {item.get("invoice") for item in data if item.get("invoice")}
            transaction.on_commit(lambda: [
                inv.recalculate_payments()
                for inv in TotalInvoice.objects.filter(id__in=affected_invoice_ids)
            ])

        return Response(
            {
                "message": f"{len(updated_payments)} payments mapped successfully.",
                **({"remainder_payments_created": len(new_payments)} if new_payments else {}),
            },
            status=status.HTTP_200_OK
        )

class PatientMonthAvailabilityView(APIView):
    """
    Returns a day-by-day availability calendar for a patient + service
    for the requested month.

    GET params / POST body:
        patient_id        int   required
        service_id        int   required
        month             int   required  (1-12)
        year              int   required  (e.g. 2026)
        exclude_order_id  int   optional  — skip a PrimaryOrder (reschedule)

    ── Example request ──────────────────────────────────────────────────────────
    GET /api/bookings/availability/?patient_id=42&service_id=7&month=6&year=2025
    """

    def get(self, request, *args, **kwargs):
        return self._handle(request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request.data)

    # ── Shared handler ─────────────────────────────────────────────────────────

    def _handle(self, data):
        req_ser = MonthAvailabilityRequestSerializer(data=data)
        if not req_ser.is_valid():
            return Response(
                {"errors": req_ser.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        v = req_ser.validated_data

        # 404 if patient or service don't exist — prevents silent empty results
        patient = get_object_or_404(Patient, pk=v["patient_id"])
        service = get_object_or_404(Service, pk=v["service_id"])

        checker = MonthAvailabilityChecker(
            patient_id       = patient.pk,
            service_id       = service.pk,
            month            = v["month"],
            year             = v["year"],
            exclude_order_id = v.get("exclude_order_id"),
        )

        result   = checker.check()
        resp_ser = MonthAvailabilityResponseSerializer(result)
        return Response(resp_ser.data, status=status.HTTP_200_OK)

@csrf_exempt
def razorpay_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    payload   = request.body
    signature = request.headers.get('X-Razorpay-Signature', '')

    try:
        RAZORPAY_CLIENT.utility.verify_webhook_signature(
            payload.decode(),
            signature,
            settings.RAZORPAY_WEBHOOK_SECRET,
        )
    except Exception:
        return JsonResponse({'error': 'Invalid webhook signature'}, status=400)

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON payload'}, status=400)

    if event.get('event') == 'payment.captured':
        entity     = event['payload']['payment']['entity']
        payment_id = entity['id']
        invoice_id = entity.get('notes', {}).get('invoice_id')

        if not invoice_id:
            return JsonResponse({'status': 'skipped - no invoice_id in notes'})

        if Payment.objects.filter(reference=payment_id).exists():
            return JsonResponse({'status': 'already recorded'})

        try:
            invoice = TotalInvoice.objects.get(id=invoice_id)
        except TotalInvoice.DoesNotExist:
            return JsonResponse({'error': 'Invoice not found'}, status=404)

        amount_paid = Decimal(entity['amount']) / 100

        with transaction.atomic():
            Payment.objects.create(
                invoice     = invoice,
                patient     = invoice.patient,
                amount      = amount_paid,
                method      = PaymentMethod.RAZORPAY,
                reference   = payment_id,
                is_verified = True,
            )
            invoice.recalculate_payments()

    return JsonResponse({'status': 'ok'})