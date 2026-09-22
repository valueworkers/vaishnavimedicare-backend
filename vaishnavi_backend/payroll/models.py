from django.db import models
from accounts.models import CustomUser
from django.utils import timezone
from django.db.models import Q, F, Sum
from decimal import Decimal
from django.core.validators import MinValueValidator
import uuid

class AttendanceStatus(models.Model):
    """A payroll-owned attendance status used when calculating pay."""

    owner = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="attendance_statuses",
        limit_choices_to={"user_type": "VSRE_OWNER"},
    )
    code = models.CharField(max_length=20, unique=True)
    label = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["label"]
        verbose_name = "Attendance Status"
        verbose_name_plural = "Attendance Statuses"

    def __str__(self):
        return f"{self.label} ({self.code})"

class Attendance(models.Model):
    """Daily attendance input used by payroll calculations."""

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="attendance",
        limit_choices_to={"user_type__in": ["VSRE_MANAGER", "LINE_MANAGER", "VSRE_STAFF"]},
    )
    date = models.DateField(default=timezone.now)
    duration = models.DurationField(null=True, blank=True)
    status = models.ForeignKey(
        AttendanceStatus,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Attendance"
        verbose_name_plural = "Attendance"
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="payroll_attendance_user_date_unique"),
        ]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "-date"]),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.date} ({self.status.label})"

class SalaryStructure(models.Model):

    SALARY_TYPE_CHOICES = [
        ("HOURLY", "Hourly"),
        ("DAILY", "Daily"),
        ("WEEKLY", "Weekly"),
        ("FORTNIGHTLY", "Fortnightly"),
        ("MONTHLY", "Monthly"),
    ]

    SALARY_CHANGE_TYPE = [
        ("BASE_SALARY", "Base Salary"),
        ("INCREMENT", "Increment"),
        ("ADVANCE", "Advance"),
        ("LOAN", "Loan"),
    ]
    SALARY_MODE_CHOICES = [
            ("BANK_TRANSFER", "Bank Transfer"),
            ("UPI", "UPI"),
            ("CASH", "Cash"),
            ("CHECK", "Check"),
            ("OTHER", "Other"),
        ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="salary_structures")
    salary_type = models.CharField(max_length=20, choices=SALARY_TYPE_CHOICES, default="MONTHLY")
    change_type = models.CharField(max_length=20, choices=SALARY_CHANGE_TYPE, default="BASE_SALARY")

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    pf_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    esi_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    final_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    salary_mode = models.CharField(max_length=20, choices=SALARY_MODE_CHOICES, default="BANK_TRANSFER")

    effective_from = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from"]
        unique_together = ("user", "effective_from")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "effective_from"],
                condition=models.Q(change_type="BASE_SALARY"),
                name="unique_base_salary_per_user_per_date"
            )
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class SalaryReport(models.Model):
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="salary_reports",
        limit_choices_to={
            "user_type__in": [
                "VSRE_MANAGER",
                "LINE_MANAGER",
                "VSRE_STAFF",
            ]
        },
    )

    # -------------------- Period --------------------
    start_date = models.DateField()
    end_date = models.DateField()

    # -------------------- Attendance --------------------
    present_days = models.PositiveIntegerField(default=0)
    absent_days = models.PositiveIntegerField(default=0)
    half_days = models.PositiveIntegerField(default=0)
    paid_leave_days = models.PositiveIntegerField(default=0)
    unpaid_leave_days = models.PositiveIntegerField(default=0)

    payable_days = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=Decimal("0.0"),
        help_text="present_days + half_days * 0.5 + paid_leave_days",
    )

    # -------------------- Salary Structure --------------------
    daily_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    total_payable_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    remaining_payment = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        editable=False,
    )

    # -------------------- Computed --------------------
    final_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )
    advance_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00")
    )

    is_finalized = models.BooleanField(
        default=False, help_text="True once the month is closed; row becomes immutable"
    )

 
    # -------------------- Audit --------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    # -------------------- Meta --------------------
    class Meta:
        ordering = ["-start_date"]
        unique_together = ("user", "start_date", "end_date")
        verbose_name = "Salary Report"
        verbose_name_plural = "Salary Reports"

    def __str__(self):
        return f"{self.user} | {self.start_date} → {self.end_date}"
    
class SalaryTransaction(models.Model):
    """
    Records an actual salary payment against a SalaryReport.

    A SalaryTransaction represents a financial transaction and should
    generally be treated as immutable once it reaches a final status.
    """

    PAYMENT_METHOD_CHOICES = [
        ("BANK_TRANSFER", "Bank Transfer"),
        ("UPI", "UPI"),
        ("CASH", "Cash"),
        ("CHECK", "Check"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    ]

    # -------------------- Identity --------------------
    transaction_id = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        db_index=True,
    )

    # -------------------- Relations --------------------
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="salary_transactions",
        editable=False,
    )

    salary_report = models.ForeignKey(
        SalaryReport,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    # -------------------- Payment --------------------
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Actual amount paid.",
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Bank / UPI / cheque reference.",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
        db_index=True,
    )

    paid_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Actual date and time when the payment was completed.",
    )

    processed_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Date and time when the transaction reached a final state.",
    )

    note = models.TextField(
        blank=True,
        null=True,
    )

    # -------------------- Audit --------------------
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    # -------------------- Meta --------------------
    class Meta:
        ordering = ["-created_at"]

        constraints = [
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0),
                name="salary_transaction_amount_paid_non_negative",
            ),
        ]

        indexes = [
            models.Index(
                fields=["salary_report", "status"],
                name="salary_tx_report_status_idx",
            ),
            models.Index(
                fields=["paid_at"],
                name="salary_tx_paid_at_idx",
            ),
            models.Index(
                fields=["user", "status"],
                name="salary_tx_user_status_idx",
            ),
        ]

    # -------------------- String --------------------
    def __str__(self):
        return f"{self.transaction_id} | {self.salary_report.user}"

    # -------------------- Save --------------------
    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = self.generate_transaction_id()

        if not self.user_id:
            self.user_id = self.salary_report.user_id

        final_statuses = {
            "SUCCESS",
            "FAILED",
            "CANCELLED",
        }

        if self.status in final_statuses and not self.processed_at:
            self.processed_at = timezone.now()

        # Successful payment should have a paid_at timestamp.
        if self.status == "SUCCESS" and not self.paid_at:
            self.paid_at = timezone.now()

        super().save(*args, **kwargs)

    # -------------------- Helpers --------------------
    @staticmethod
    def generate_transaction_id():
        return f"SAL{uuid.uuid4().hex[:12].upper()}"

