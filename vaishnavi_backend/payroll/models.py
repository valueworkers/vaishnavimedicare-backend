from django.db import models
from accounts.models import CustomUser
from django.utils import timezone
from django.db.models import Q, F,Sum
from decimal import Decimal
from django.core.validators import MinValueValidator
import uuid

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

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="salary_structures"
    )

    salary_type = models.CharField(
        max_length=20,
        choices=SALARY_TYPE_CHOICES,
        default="MONTHLY"
    )

    change_type = models.CharField(
        max_length=20,
        choices=SALARY_CHANGE_TYPE,
        default="BASE_SALARY"
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    final_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

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
        """
        Salary calculation rules:
        - BASE_SALARY → sets final_salary
        - INCREMENT → final_salary = latest final_salary + increment
        """
        self.full_clean()
        # Fetch last salary record before this effective date (excluding current record)
        previous = (
            SalaryStructure.objects
            .filter(
                user=self.user,
                effective_from__lte=self.effective_from,
                change_type__in=["BASE_SALARY","INCREMENT"]
            )
            .exclude(pk=self.pk)  # Exclude current record
            .order_by("-effective_from")
            .first()
        )

        previous_salary = previous.final_salary if previous else 0

        if self.change_type == "BASE_SALARY":
            self.final_salary = self.amount

        elif self.change_type == "INCREMENT":
            self.final_salary = previous_salary + self.amount

        elif self.change_type in ["ADVANCE", "LOAN"]:
            # Salary unchanged, deductions handled elsewhere if needed
            self.final_salary = previous_salary

        super().save(*args, **kwargs)

class SalaryReport(models.Model):
    """
    Salary calculation & payment breakdown report.
    Acts as an immutable audit record per salary period.
    """

    # -------------------- Relations --------------------
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

    # -------------------- Audit --------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    Records actual salary payment against a SalaryReport.
    Immutable financial transaction record.
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
    salary_report = models.ForeignKey(
        SalaryReport,
        on_delete=models.PROTECT,
        related_name="transactions",
    )
    # -------------------- Payment --------------------
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Actual amount paid",
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
    )

    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Bank / UPI / cheque reference",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
        db_index=True,
    )

    processed_at = models.DateTimeField(blank=True, null=True)

    note = models.TextField(blank=True, null=True)

    # -------------------- Audit --------------------
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # -------------------- Meta --------------------
    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0),
                name="amount_paid_non_negative",
            ),
        ]

    def __str__(self):
        return f"{self.transaction_id} | {self.salary_report.user}"

    # -------------------- Save --------------------
    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = self.generate_transaction_id()

        # Set processed time on final states
        if self.status in {"SUCCESS", "FAILED", "CANCELLED"} and not self.processed_at:
            self.processed_at = timezone.localtime()
        super().save(*args, **kwargs)

    # -------------------- Helpers --------------------
    @staticmethod
    def generate_transaction_id():
        return f"SAL{uuid.uuid4().hex[:12].upper()}"
