from rest_framework import serializers
from django.db import transaction
from .models import *
from .constants import *
from django.contrib.contenttypes.models import ContentType
import datetime
from django.utils import timezone


class LocationSerializer(serializers.ModelSerializer):
    full_address = serializers.SerializerMethodField(read_only=True)
    user_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Location
        fields = [
            "id",
            "user",
            "user_name",
            "location_type",
            "building_name",
            "address_line1",
            "address_line2",
            "locality",
            "city",
            "state",
            "postal_code",
            "full_address",
        ]
        read_only_fields = ["user"]

    def get_full_address(self, obj):
        return obj.full_address()

    def get_user_name(self, obj):
        return obj.user.get_full_name() if obj.user else None

class PatientSerializer(serializers.ModelSerializer):
    name_registered_by = serializers.CharField(
        source="registered_by.get_full_name", read_only=True
    )
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = Patient
        fields = "__all__"
        read_only_fields = [
            "id",
            "patient_id",
            "name_registered_by",
            "registered_by",
            "registration_date",
            
        ]

class PatientDocumentFilesSerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientDocumentFile
        fields = "__all__"

class PatientDocumentSerializer(serializers.ModelSerializer):
    files = PatientDocumentFilesSerializer(many=True, required=False)

    class Meta:
        model = PatientDocument
        fields = "__all__"
        read_only_fields = ["uploaded_by"]


class PatientMiniSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id",
            "patient_id",
            "name",
            "email",
            "phone",
            "age",
            "emergency_contact",
            "emergency_phone",
        ]

class PackageCreateSerializer(serializers.ModelSerializer):
    belongs_to_type = serializers.CharField(write_only=True)

    class Meta:
        model = Package
        fields = [
            "name",
            "description",
            "package_type",
            "period",
            "price",
            "registration_fees",
            "is_active",
            "object_id",
            "belongs_to_type",
        ]
        read_only_fields=[
            "package_type"
        ]
        extra_kwargs = {
            'period': {'required': True},
        }


    def validate(self, attrs):
        model_name = attrs.pop("belongs_to_type", None)

        if not model_name:
            raise serializers.ValidationError(
                {"belongs_to_type": "This field is required."}
            )

        try:
            content_type = ContentType.objects.get(
                model=model_name.lower()
            )
            attrs["content_type"] = content_type
        except ContentType.DoesNotExist:
            raise serializers.ValidationError(
                {"belongs_to_type": "Invalid model name."}
            )

        return attrs

class PackageSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(
        source="owner.get_full_name",
        read_only=True
    )
    belongs_to_type = serializers.CharField(
        source="content_type.model",
        read_only=True
    )

    class Meta:
        model = Package
        fields = [
            "id",
            "owner",
            "owner_name",
            "name",
            "description",
            "package_type",
            "period",
            "price",
            "registration_fees",
            "is_active",
            "object_id",
            "belongs_to_type",
        ]

        read_only_fields = [
            "id",
            "owner",
            "object_id",
            "belongs_to_type",
        ]

class ContactBookingSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.get_full_name",read_only=True)
    mobile_number = serializers.CharField(source="booked_by.mobile_number",read_only=True)
    service_name = serializers.CharField(source="service.name",read_only=True)

    class Meta:
        model = ContactBooking
        fields = "__all__"
        read_only_fields = ['id', 'created_at', 'updated_at','booked_by']

    def validate(self, data):
        start = data.get("start_datetime")
        end = data.get("end_datetime")

        if start and end and start >= end:
            raise serializers.ValidationError("End time must be after start time.")

        return data

class TernaryOrderCreateSerializer(serializers.ModelSerializer):
    """
    Create a TernaryOrder (service) under a SecondaryOrder.
    `secondary_order` is injected by the ViewSet via save().
    `primary_order` context is passed for date-range validation.
    """

    class Meta:
        model = TernaryOrder
        fields = [
            'venue',
            'service',
            'package',
            'client_address',
            'start_datetime',
            'end_datetime',
            'discount_amount',
            'premium_amount',
        ]
        extra_kwargs = {
            'venue': {'required': True},
            'service': {'required': True},
            'package': {'required': True},
            'client_address':  {'required': False},

        }

    def validate(self, attrs):
        primary_order = self.context.get('primary_order')

        if not primary_order:
            raise serializers.ValidationError(
                {"primary_order": "Primary order context is missing."}
            )

        start_datetime = attrs.get('start_datetime')
        end_datetime   = attrs.get('end_datetime')

        if start_datetime and end_datetime:
            if start_datetime >= end_datetime:
                raise serializers.ValidationError(
                    {"start_datetime": "Start datetime must be before end datetime."}
                )

            if (
                start_datetime < primary_order.start_datetime
                or end_datetime > primary_order.end_datetime
            ):
                raise serializers.ValidationError(
                    {
                        "start_datetime": (
                            "Service dates must fall within the primary order range "
                            f"({primary_order.start_datetime} - {primary_order.end_datetime})."
                        )
                    }
                )

        return attrs

class TernaryOrderSerializer(serializers.ModelSerializer):
    """Read serializer for a single TernaryOrder (service line item)."""

    venue_name = serializers.CharField(
        source='venue.name',
        read_only=True,
        allow_null=True,
    )
    service_name = serializers.CharField(
        source='service.name',
        read_only=True,
        allow_null=True,
    )
    package_name = serializers.CharField(
        source='package.name',
        read_only=True,
        allow_null=True,
    )
    location_locality = serializers.CharField(
        source='venue.location.locality',
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = TernaryOrder
        fields = [
            'id',
            'order_id',
            'booking_entity',
            'booking_type',
            'venue',
            'venue_name',
            'service',
            'service_name',
            'package',
            'package_name',
            'location_locality',
            'client_address',
            'start_datetime',
            'end_datetime',
            'discount_amount',
            'premium_amount',
            'subtotal',
            'status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'order_id', 'subtotal', 'created_at', 'updated_at']

class SecondaryOrderSerializer(serializers.ModelSerializer):
    """Read serializer for a SecondaryOrder (one period/month slot)."""

    ternary_orders = TernaryOrderSerializer(many=True, read_only=True)
   
    service_name = serializers.SerializerMethodField()
    package_name = serializers.SerializerMethodField()
    location_locality = serializers.SerializerMethodField()

    class Meta:
        model = SecondaryOrder
        fields = [
            'id',
            'order_id',
            'service_name',
            'package_name',
            'location_locality',
            'start_datetime',
            'end_datetime',
            'subtotal',
            'status',
            'is_registration_fee',
            'ternary_orders',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id','service_name','package_name','location_locality', 'order_id', 'subtotal', 'created_at', 'updated_at']
    
    def get_location_locality(self, obj):
        primary_order = obj.primary_order        
        if primary_order.venue:
            return primary_order.venue.location.locality
        return None
    
    def get_service_name(self, obj):
        if obj.is_registration_fee:
            return "Registration Fees"        
        elif obj.primary_order.service:
            return obj.primary_order.service.name
        else: return None
        
    
    def get_package_name(self, obj):
        if obj.is_registration_fee:
            return "Registration Fees"
        elif obj.primary_order.package:
            return obj.primary_order.package.name
        else: return None
    
class PrimaryOrderSerializer(serializers.ModelSerializer):
    """
    Full read serializer for PrimaryOrder with nested SecondaryOrders
    and their TernaryOrders.
    """

    secondary_orders = SecondaryOrderSerializer(many=True, read_only=True)

    venue_name = serializers.CharField(
        source='venue.name',
        read_only=True,
        allow_null=True,
    )
    service_name = serializers.CharField(
        source='service.name',
        allow_null=True,
    )
    package_name = serializers.CharField(
        source='package.name',
        allow_null=True,
    )
    patient      = PatientMiniSerializer(read_only=True)
    user_email   = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = PrimaryOrder
        fields = [
            'id',
            'order_id',
            'booking_entity',
            'booking_type',
            'status',
            # relations
            'patient',
            'user',
            'user_email',
            'venue',
            'venue_name',
            'service',
            'service_name',
            'package',
            'package_name',
            'client_address',
            # financials
            'total_bill',
            # dates
            'start_datetime',
            'end_datetime',
            'raw_dates',
            'auto_continue',
            'discount_amount',
            'premium_amount',
            # nested
            'secondary_orders',
            # timestamps
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'order_id',
            'total_bill',
            'booking_entity',
            'booking_type',
            'created_at',
            'updated_at'
        ]

    def validate(self, data):
        start_datetime = data.get('start_datetime')
        end_datetime   = data.get('end_datetime')

        if start_datetime and end_datetime:
            if start_datetime >= end_datetime:
                raise serializers.ValidationError(
                    "Start datetime must be before end datetime."
                )

        return data

class PrimaryOrderCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer for creating a PrimaryOrder.

    'dates' is an optional write-only field:
      - DAILY  → list of "YYYY-MM-DD" strings
      - HOURLY → dict of {"YYYY-MM-DD": ["HH:MM:SS", ...]}

    When 'dates' is provided, 'start_datetime' / 'end_datetime' are optional
    because the model derives them from the date list.
    When 'dates' is absent, both datetime fields are required.
    """

    class Meta:
        model = PrimaryOrder
        fields = [
            'patient',
            'venue',
            'service',
            'package',
            'booking_type',
            'client_address',
            'start_datetime',
            'start_datetime',
            'end_datetime',
            'discount_amount',
            'premium_amount',
            'auto_continue',
            'raw_dates',
        ]
        extra_kwargs = {
            'service':         {'required': False},
            'venue':           {'required': False},
            'start_datetime':  {'required': False},
            'end_datetime':    {'required': False},
            'client_address':  {'required': False},
            'discount_amount':  {'required': False},
            'premium_amount':    {'required': False},
        }

    def validate(self, data):
        data["booking_entity"] = BookingEntity.SERVICE

        errors = {}
        has_dates = 'raw_dates' in data
        start = data.get('start_datetime')
        end = data.get('end_datetime')

        if not has_dates:
            if not start:
                errors["start_datetime"] = "Required when 'dates' is not provided."
            if not end:
                errors["end_datetime"] = "Required when 'dates' is not provided."

        if start and end and start >= end:
            errors["non_field_errors"] = "Start datetime must be before end datetime."

        if errors:
            raise serializers.ValidationError(errors)

        return data

class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model"""
    patient_name = serializers.CharField(
        source="patient.get_full_name",
        read_only=True,
        default=None
    )
    patient_phone_number = serializers.CharField(
        source="patient.phone",
        read_only=True,
        default=None
    )
    is_mapped = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ['id', 'reference','created_at','updated_at',]

    def get_is_mapped(self, obj):
        return True if obj.patient and obj.invoice else False


class PaymentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating payments"""

    class Meta:
        model = Payment
        fields = [
            'amount',
            'method',
            'reference',
            'paid_date',
            'is_verified',
        ]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Payment amount must be greater than zero."
            )
        return value

class TotalInvoiceSerializer(serializers.ModelSerializer):
    """
    Unified serializer for TotalInvoice list and detail views.
    'booking' now refers to a PrimaryOrder.
    """

    payments = PaymentSerializer(many=True, read_only=True)
    booking = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TotalInvoice
        fields = [
            'id',
            'invoice_number',
            'period_start',
            'period_end',
            'subtotal',
            'discount_amount',
            'premium_amount',
            'tax_amount',
            'total_amount',
            'paid_amount',
            'remaining_amount',
            'status',
            'due_date',
            'issued_date',
            'created_at',
            'updated_at',
            
            'booking',
            'payments',
        ]
        read_only_fields = [
            'id',
            'invoice_number',
            'total_amount',
            'remaining_amount',
            'paid_amount',
        ]

    def validate_discount_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("Discount amount cannot be negative.")
        return value

    def validate_tax_amount(self, value):
        if value < 0:
            raise serializers.ValidationError("Tax amount cannot be negative.")
        return value
    
    def get_booking(self, obj):
        """Extract booking details from secondary or ternary order"""

        secondary = obj.secondary_order
        ternary = obj.ternary_order

        if not secondary and not ternary:
            return None

        # Case 1: Secondary Order
        if secondary:
            booking_obj = secondary.primary_order

            return {
                "order_id": booking_obj.order_id,
                "venue": booking_obj.venue.name if booking_obj.venue else None,
                "locality": booking_obj.venue.location.locality if booking_obj.venue else None,
                "location": booking_obj.venue.location.full_address() if booking_obj.venue else None,
                "service":  secondary.booking_service,
                "package":  secondary.booking_package
            }

        # Case 2: Ternary Order
        if ternary:
            secondary = ternary.secondary_order
            booking_obj = secondary.primary_order if secondary else None

            if not booking_obj:
                return None

            return {
                "order_id": booking_obj.order_id,
                "venue": booking_obj.venue.name if booking_obj.venue else None,
                "locality": booking_obj.venue.location.locality if booking_obj.venue else None,
                "location": booking_obj.venue.location.full_address() if booking_obj.venue else None,
                "service":  ternary.booking_service,
                "package":  ternary.booking_package
            }

class InvoiceSummarySerializer(serializers.Serializer):
    """Serializer for invoice summary / statistics"""

    generated_invoices        = serializers.IntegerField()
    total_amount          = serializers.DecimalField(max_digits=12, decimal_places=2)
    paid_amount           = serializers.DecimalField(max_digits=12, decimal_places=2)
    remaining_amount      = serializers.DecimalField(max_digits=12, decimal_places=2)
    unpaid_count          = serializers.IntegerField()
    partially_paid_count  = serializers.IntegerField()
    paid_count            = serializers.IntegerField()

class InvoiceDropdownSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source="patient.get_full_name",read_only=True)

    class Meta:
        model = TotalInvoice
        fields = [
            'id',
            'invoice_number',
            'patient',
            'patient_name',
            'period_start',
            'period_end',
            'total_amount',
            

        ]
        
class SecondaryBulkActionSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        error_messages={"min_length": "At least one id is required."}
    )
    action = serializers.ChoiceField(choices=list(("APPROVE","REJECT","HOLD")))
    
    reason = serializers.CharField(
        required=False,
        max_length=500
    )
    notify_customer = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether to notify customer of Action"
    )

# ── Request ────────────────────────────────────────────────────────────────────
class MonthAvailabilityRequestSerializer(serializers.Serializer):
    patient_id       = serializers.IntegerField(min_value=1)
    service_id       = serializers.IntegerField(min_value=1)
    month            = serializers.IntegerField(min_value=1, max_value=12)
    year             = serializers.IntegerField(min_value=2000, max_value=2100)
    exclude_order_id = serializers.IntegerField(required=False, allow_null=True)

    def validate(self, data):
        today = timezone.now().date()
        try:
            first_of_month = datetime.date(data["year"], data["month"], 1)
        except ValueError:
            raise serializers.ValidationError("Invalid month/year combination.")

        if first_of_month < today.replace(year=today.year - 2):
            raise serializers.ValidationError(
                "Cannot query availability more than 2 years in the past."
            )
        if first_of_month > today.replace(year=today.year + 5):
            raise serializers.ValidationError(
                "Cannot query availability more than 5 years in the future."
            )
        return data


# ── Nested booking detail (one entry per SecondaryOrder on a day) ─────────────
class BookingDetailSerializer(serializers.Serializer):
    secondary_order_id = serializers.IntegerField()
    order_id           = serializers.CharField()
    start_datetime     = serializers.DateTimeField()
    end_datetime       = serializers.DateTimeField()
    status             = serializers.CharField()
    service_name       = serializers.CharField()
    package_name       = serializers.CharField()
    primary_order_id   = serializers.CharField()
    booking_type       = serializers.CharField()


# ── One entry per calendar day ─────────────────────────────────────────────────
class DayAvailabilitySerializer(serializers.Serializer):
    date         = serializers.DateField()
    is_available = serializers.BooleanField()
    is_past      = serializers.BooleanField()
    bookings     = BookingDetailSerializer(many=True)


# ── Top-level response ─────────────────────────────────────────────────────────
class MonthAvailabilityResponseSerializer(serializers.Serializer):
    patient_id     = serializers.IntegerField()
    service_id     = serializers.IntegerField()
    month          = serializers.IntegerField()
    year           = serializers.IntegerField()
    month_label    = serializers.CharField()     # e.g. "June 2025"
    total_days     = serializers.IntegerField()
    available_days = serializers.IntegerField()
    occupied_days  = serializers.IntegerField()
    past_days      = serializers.IntegerField()
    calendar       = DayAvailabilitySerializer(many=True)