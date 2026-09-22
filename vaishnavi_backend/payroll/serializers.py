# serializers.py
from rest_framework import serializers
from .models import Attendance, AttendanceStatus, SalaryStructure, SalaryReport, SalaryTransaction
from accounts.models import CustomUser


class AttendanceStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceStatus
        fields = "__all__"
        read_only_fields = ["owner"]

class AttendanceSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="status.label", read_only=True)
    status_code = serializers.CharField(source="status.code", read_only=True)

    class Meta:
        model = Attendance
        fields = ["user", "date", "duration", "status", "status_label", "status_code", "reason"]

    def validate(self, attrs):
        user = attrs.get("user", getattr(self.instance, "user", None))
        attendance_date = attrs.get("date", getattr(self.instance, "date", None))
        if not self.instance and Attendance.objects.filter(user=user, date=attendance_date).exists():
            raise serializers.ValidationError(
                f"Attendance for {user.get_full_name()} on {attendance_date} already exists."
            )
        return attrs

class EmployeePayrollListSerializer(serializers.ModelSerializer):
    """
    Flat payroll-report row per user. basic_salary/pf/esi come from the
    latest SalaryStructure; recent_payment/payout_mode come from the
    latest successful SalaryTransaction — all annotated in the viewset
    queryset, so no per-row queries happen here.
    """
    employee_id = serializers.CharField(source="employee_profile.employee_id", read_only=True, allow_null=True)
    vendor_name = serializers.CharField(source="employee_profile.vendor_name", read_only=True, allow_null=True)
    employee_category = serializers.CharField(source="employee_profile.category", read_only=True)


    basic_salary = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    pf_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, allow_null=True)
    esi_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, allow_null=True)

    recent_payment = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    payout_mode = serializers.CharField(read_only=True, allow_null=True)

    effective_date = serializers.DateField()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "first_name",
            "last_name",
            "employee_id",
            "email",
            "mobile_number",
            "is_active",
            "is_deleted",
            "employee_category",
            "vendor_name",
            "basic_salary",
            "pf_amount",
            "esi_amount",
            "recent_payment",
            "payout_mode",
            "effective_date",
        ]

class SalaryStructureSerializer(serializers.ModelSerializer):
    """
    Serializer for SalaryStructure model with nested user data
    """

    class Meta:
        model = SalaryStructure
        fields = "__all__"
        read_only_fields = ['id', 'final_salary', 'created_at', 'updated_at']

    def validate(self, attrs):
        request = self.context.get("request")
        target_user = attrs.get("user", getattr(self.instance, "user", None))
        change_type = attrs.get("change_type", getattr(self.instance, "change_type", None))

        if request is not None and target_user is not None:
            requester = request.user

            if not requester.is_superuser:
                if getattr(requester, "is_owner", False):
                    # Owner may only manage salary structures within their own hierarchy
                    owned = getattr(target_user, "hierarchy", None)
                    if owned is None or owned.owner_id != requester.id:
                        raise serializers.ValidationError({
                            "user": "You can only manage salary structures for your own staff or managers."
                        })
                elif requester.id != target_user.id:
                    # Manager/Staff can never set/change salary structures for someone else
                    raise serializers.ValidationError({
                        "user": "You do not have permission to modify salary structures for this user."
                    })
                else:
                    raise serializers.ValidationError({
                        "user": "You are not permitted to modify your own salary structure."
                    })

        # Only check when creating/updating base salary
        if change_type == "BASE_SALARY":
            qs = SalaryStructure.objects.filter(user=target_user, change_type="BASE_SALARY")
            if self.instance:
                qs = qs.exclude(id=self.instance.id)
            if qs.exists():
                raise serializers.ValidationError({
                    "change_type": "Base salary already exists for this user."
                })

        return attrs
    

class SalaryReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalaryReport
        fields = [
            "id", "user", "start_date", "end_date",
            "present_days", "absent_days", "half_days",
            "paid_leave_days", "unpaid_leave_days", "payable_days",
            "daily_rate", "total_payable_amount", "paid_amount",
            "remaining_payment", "advance_amount", "final_salary",
            "is_finalized", "created_at", "updated_at",
        ]
        # is_finalized flips via the `finalize` action / finalize tasks only,
        # never a direct field edit through this serializer.
        read_only_fields = ["is_finalized"]



class SalaryTransactionSerializer(serializers.ModelSerializer):
    salary_report_id = serializers.IntegerField(source='salary_report.id', read_only=True)
    start_date = serializers.DateField(source='salary_report.start_date', read_only=True)
    end_date = serializers.DateField(source='salary_report.end_date', read_only=True)
    employee_name = serializers.CharField(source='salary_report.user.get_full_name', read_only=True)

    class Meta:
        model = SalaryTransaction
        fields = [
            'employee_name',
            'id',
            'transaction_id',
            'salary_report_id',
            'start_date',
            'end_date',
            'amount_paid',
            'payment_method',
            'payment_reference',
            'processed_at',
            'note',
            'status',
        ]
        read_only_fields = ['transaction_id','start_date','end_date', 'processed_at']

class SalaryTransactionCreateSerializer(serializers.Serializer):
    salary_report_id = serializers.IntegerField()
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    payment_method = serializers.ChoiceField(choices=SalaryTransaction.PAYMENT_METHOD_CHOICES)
    payment_reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate_amount_paid(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount paid must be greater than 0.")
        return value

    def validate_salary_report_id(self, value):
        try:
            SalaryReport.objects.get(id=value)
        except SalaryReport.DoesNotExist:
            raise serializers.ValidationError("Salary report not found.")
        return value

