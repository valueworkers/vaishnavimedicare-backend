from rest_framework import serializers
from attendance.models import Attendance, AttendanceStatus
from booking.models import TotalInvoice



class SalaryPeriodSerializer(serializers.Serializer):
    """One pay period row for an employee."""

    start_date      = serializers.DateField()
    end_date        = serializers.DateField()
    calendar_days   = serializers.IntegerField()
    total_payable_days     = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_unpaid_days     = serializers.DecimalField(max_digits=10, decimal_places=2)
    attendance_pct  = serializers.DecimalField(max_digits=10, decimal_places=2)
    salary          = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_salary    = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_status          = serializers.CharField(allow_null=True)
    amount_paid     = serializers.DecimalField(max_digits=12, decimal_places=2)
    excess_balance  = serializers.DecimalField(max_digits=12, decimal_places=2)


class EmployeeSalaryAnalysisSerializer(serializers.Serializer):
    """One employee with all their salary periods nested."""

    id              = serializers.IntegerField()
    emp_id          = serializers.CharField(allow_null=True)
    first_name      = serializers.CharField()
    middle_name     = serializers.CharField(allow_null=True)
    last_name       = serializers.CharField()
    mobile_number   = serializers.CharField()
    status          = serializers.BooleanField()
    periods         = SalaryPeriodSerializer(many=True)


class AttendanceDaySerializer(serializers.Serializer):
    """
    Represents a single month's attendance record.
    Example: { "01": "P", "02": "A", "03": "H" }
    """
    def to_representation(self, instance):
        return instance  # already a dict of { "DD": "status_code" }

class UserAttendanceSerializer(serializers.Serializer):
    """
    Represents attendance data for a single user.
    """
    user = serializers.IntegerField()
    attendance = serializers.SerializerMethodField()

    def get_attendance(self, obj):
        """
        obj["attendance"] is already a structured dict:
            { "Jan-2025": { "01": "P", "02": "A" }, ... }
        We simply return it as-is.
        """
        return obj.get("attendance", {})

class MonthlyAnalyticsRowSerializer(serializers.Serializer):
    month = serializers.CharField()
    invoice_value = serializers.FloatField()
    amt_collected = serializers.FloatField()
    balance = serializers.FloatField()
    collection_pct = serializers.FloatField(allow_null=True)
    paid_invoices = serializers.IntegerField()
    partially_paid_invoices = serializers.IntegerField()   # [CHANGE 3]
    unpaid_invoices = serializers.IntegerField()
    generated_invoices = serializers.IntegerField()
    unmapped_count = serializers.IntegerField()
    unmapped_amount = serializers.FloatField()
    bookings_starting = serializers.IntegerField()         # [CHANGE 1]
    bookings_ending = serializers.IntegerField()           # [CHANGE 1]

class MonthlyAnalyticsSummarySerializer(serializers.Serializer):
    total_invoice_value = serializers.FloatField()
    total_amt_collected = serializers.FloatField()
    total_balance = serializers.FloatField()
    collection_pct = serializers.FloatField(allow_null=True)
    total_paid_invoices = serializers.IntegerField()
    total_partially_paid_invoices = serializers.IntegerField()   # [CHANGE 3]
    total_unpaid_invoices = serializers.IntegerField()
    total_generated_invoices = serializers.IntegerField()
    total_unmapped_count = serializers.IntegerField()
    total_unmapped_amount = serializers.FloatField()
    total_bookings_starting = serializers.IntegerField()         # [CHANGE 1]
    total_bookings_ending = serializers.IntegerField()           # [CHANGE 1]

class MonthlyAnalyticsResponseSerializer(serializers.Serializer):
    year = serializers.IntegerField()
    month = serializers.IntegerField()
    year_type = serializers.CharField()
    rows = MonthlyAnalyticsRowSerializer(many=True)
    summary = MonthlyAnalyticsSummarySerializer()

class InvoiceListSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(
        source="patient.get_full_name",
        read_only=True
    )
    user_email = serializers.EmailField(
        source="user.email",
        read_only=True
    )

    booking_order_id = serializers.CharField(
        source="secondary_order.order_id",
        read_only=True
    )
    booking_venue = serializers.CharField(
        source="secondary_order.primary_order.venue.name",
        read_only=True, allow_null=True
    )
    booking_locality = serializers.CharField(
        source="secondary_order.primary_order.venue.location.locality",
        read_only=True, allow_null=True
    )
    booking_service = serializers.CharField(
        source="secondary_order.booking_service",
        read_only=True, allow_null=True
    )
    booking_package = serializers.CharField(
        source="secondary_order.booking_package",
        read_only=True, allow_null=True
    )


    class Meta:
        model = TotalInvoice
        fields = (
            "id",
            "invoice_number",

            # Booking details
            "booking_order_id",
            "booking_venue",
            "booking_locality",
            "booking_service",
            "booking_package",

            # Relations
            "secondary_order",
            "ternary_order",
            "patient",
            "patient_name",
            "user",
            "user_email",

            # Period
            "period_start",
            "period_end",

            # Financials
            "total_amount",
            "paid_amount",
            "remaining_amount",

            # Status
            "status",
            "due_date",
            "issued_date",
        )
