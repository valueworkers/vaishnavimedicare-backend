# serializers.py
from rest_framework import serializers
from .models import SalaryStructure, SalaryReport,SalaryTransaction


class SalaryStructureSerializer(serializers.ModelSerializer):
    """
    Serializer for SalaryStructure model with nested user data
    """
    class Meta:
        model = SalaryStructure
        fields = [
            'id',
            'user',
            'salary_type',
            'change_type',
            'amount',
            'final_salary',
            'effective_from',
        ]
        read_only_fields = ['id','final_salary','created_at', 'updated_at']
    
    def validate(self, attrs):
        user = attrs.get("user")
        change_type = attrs.get("change_type")

        # Only check when creating base salary
        if change_type == "BASE_SALARY":
            qs = SalaryStructure.objects.filter(
                user=user,
                change_type="BASE_SALARY"
            )

            # If this is update, exclude current instance
            if self.instance:
                qs = qs.exclude(id=self.instance.id)

            if qs.exists():
                raise serializers.ValidationError({
                    "change_type": "Base salary already exists for this user."
                })

        return attrs
    
class SalaryReportSerializer(serializers.ModelSerializer):
    final_salary = serializers.SerializerMethodField()
    advance_amount = serializers.SerializerMethodField()

    class Meta:
        model = SalaryReport
        fields = [
            "id",
            "user",
            "start_date",
            "end_date",
            "final_salary",
            "advance_amount",
            "total_payable_amount",
            "paid_amount",
            "remaining_payment",
        ]
        read_only_fields = [
            "id",
            "remaining_payment",
            "final_salary",
            "advance_amount",
        ]

    def validate(self, attrs):
        start = attrs.get("start_date")
        end = attrs.get("end_date")

        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "End date must be after start date"}
            )

        return attrs
    def get_advance_amount(self, obj):
        return obj.advance_amount
    def get_final_salary(self, obj):
        return obj.final_salary
    
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

