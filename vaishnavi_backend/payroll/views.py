from decimal import Decimal
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import *
from .serializers import *
from .utils import PayrollCalculator
from .permissions import CanViewSalaryReport, IsOwnerOrReadOnly
from rest_framework import viewsets, status
from datetime import datetime
from rest_framework.views import APIView
from django.db import transaction as db_transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models import Sum, OuterRef, Subquery
from accounts.models import CustomUser
from accounts.permissions import IsOwner

class EmployeePayrollViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only payroll summary list, scoped by the same hierarchy rules
    as SalaryStructureViewSet.
    """
    serializer_class = EmployeePayrollListSerializer
    permission_classes = [IsAuthenticated]

    filterset_fields = [
        "id",
        "first_name",
        "last_name",
        "employee_profile__employee_id",
        "email",
        "mobile_number",
        "employee_profile__category",
        "employee_profile__vendor_name",
    ]

    search_fields = [
        "first_name",
        "last_name",
        "employee_profile__employee_id",
        "employee_profile__vendor_name",
        "=email",
        "=mobile_number",
    ]

    ordering_fields = [
        "id",
        "first_name",
        "last_name",
        "basic_salary",
        "pf_amount",
        "esi_amount",
        "effective_date",
        "recent_payment",
    ]
    ordering = ["first_name", "last_name"]

    def get_queryset(self):
        user = self.request.user

        latest_salary = SalaryStructure.objects.filter(
            user=OuterRef("pk"),
        ).order_by("-effective_from", "-pk")

        latest_txn = SalaryTransaction.objects.filter(
            salary_report__user=OuterRef("pk"),
            status="SUCCESS",
        ).order_by("-processed_at", "-created_at")

        base_qs = (
            CustomUser.objects
            .employees()
            .select_related("employee_profile")
            .annotate(
                basic_salary=Subquery(latest_salary.values("final_salary")[:1]),
                pf_amount=Subquery(latest_salary.values("pf_amount")[:1]),
                esi_amount=Subquery(latest_salary.values("esi_amount")[:1]),
                effective_date=Subquery(latest_salary.values("effective_from")[:1]),
                recent_payment=Subquery(latest_txn.values("amount_paid")[:1]),
                payout_mode=Subquery(latest_txn.values("payment_method")[:1]),
            )
        )

        if user.is_superuser or user.is_owner:
            queryset = base_qs
        else:
            # Manager/Staff → only their own row
            queryset = base_qs.filter(id=user.id)

        return queryset

class SalaryStructureViewSet(viewsets.ModelViewSet): 
    """
    ViewSet for managing salary structures
    """

    serializer_class = SalaryStructureSerializer
    permission_classes = [IsAuthenticated,IsOwner]

    filterset_fields = [
        "user_id",
        "change_type",
        "effective_from",
    ]

    search_fields = [
        "user__first_name",
        "user__last_name",
        "=user__email",
        "=user__mobile_number",
    ]

    def get_queryset(self):
        """
        Get queryset based on user hierarchy
        """
        user = self.request.user

        # Admin → see everything
        if user.is_superuser or user.is_owner:
            queryset = SalaryStructure.objects.all()

        # Staff or Manager → see only their own salary structure
        else:
            queryset = SalaryStructure.objects.filter(user=user)
        return queryset.select_related("user").order_by("-effective_from")

    def perform_create(self, serializer):
        instance = serializer.save()
        instance.refresh_from_db()

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.refresh_from_db()

class AttendanceStatusViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceStatusSerializer
    permission_classes = [IsOwnerOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        global_statuses = AttendanceStatus.objects.filter(owner__is_superuser=True)
        if user.is_superuser:
            return AttendanceStatus.objects.all()
        if user.is_owner:
            return global_statuses | AttendanceStatus.objects.filter(owner=user)
        owner_id = getattr(getattr(user, "hierarchy", None), "owner_id", None)
        return global_statuses | AttendanceStatus.objects.filter(owner_id=owner_id)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

class AttendanceView(APIView):
    permission_classes = [IsAuthenticated]

    def _scoped_queryset(self, request):
        user = request.user
        if user.is_superuser and user.is_owner:
            return Attendance.objects.all()

        return Attendance.objects.filter(user=user)

    def get(self, request):
        queryset = self._scoped_queryset(request)
        for parameter, lookup in (("user_id", "user_id"), ("date", "date"), ("status", "status__code")):
            if value := request.query_params.get(parameter):
                queryset = queryset.filter(**{lookup: value})
        if value := request.query_params.get("start_date"):
            queryset = queryset.filter(date__gte=value)
        if value := request.query_params.get("end_date"):
            queryset = queryset.filter(date__lte=value)
        queryset = queryset.select_related("user", "status")
        return Response({"count": queryset.count(), "results": AttendanceSerializer(queryset, many=True).data})

    def post(self, request):
        user_id, attendance_date = request.data.get("user"), request.data.get("date")
        if not user_id or not attendance_date:
            return Response({"error": "user and date fields are required"}, status=status.HTTP_400_BAD_REQUEST)
        attendance = self._scoped_queryset(request).filter(user_id=user_id, date=attendance_date).first()
        if not attendance and not self._scoped_queryset(request).filter(user_id=user_id).exists():
            return Response({"error": "You do not have permission to update this user's attendance."}, status=status.HTTP_403_FORBIDDEN)
        serializer = AttendanceSerializer(attendance, data=request.data, partial=bool(attendance))
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "Attendance updated successfully" if attendance else "Attendance created successfully", "data": serializer.data},
            status=status.HTTP_200_OK if attendance else status.HTTP_201_CREATED,
        )

class PayrollReportAPIView(APIView):
    """Single on-the-fly attendance and salary report endpoint."""

    permission_classes = [CanViewSalaryReport]

    def get(self, request):
        try:
            start_date = datetime.strptime(request.query_params.get("start_date"), "%Y-%m-%d").date() if request.query_params.get("start_date") else None
            end_date = datetime.strptime(request.query_params.get("end_date"), "%Y-%m-%d").date() if request.query_params.get("end_date") else None
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)
        if bool(start_date) != bool(end_date):
            return Response({"error": "start_date and end_date must be supplied together"}, status=status.HTTP_400_BAD_REQUEST)
        period_type = request.query_params.get("period_type", "MONTHLY").upper()
        if period_type not in PayrollCalculator.PERIOD_TYPES:
            return Response({"error": "Invalid period_type"}, status=status.HTTP_400_BAD_REQUEST)
        target_users = self._target_users(request)
        if isinstance(target_users, Response):
            return target_users
        results = []
        for employee in target_users:
            for report in PayrollCalculator(employee).reports(start_date, end_date, period_type):
                results.append({
                    "user": employee.id, "user_name": employee.get_full_name(),
                    "start_date": report["start_date"], "end_date": report["end_date"],
                    "attendance": report["attendance"],
                    "salary": report["salary"],
                })
        return Response(sorted(results, key=lambda row: (row["start_date"], row["user"]), reverse=True))

    def _target_users(self, request):
        requester, user_id = request.user, request.query_params.get("user_id")
        if user_id:
            employee = get_object_or_404(CustomUser, pk=user_id)
            if not CanViewSalaryReport().has_object_permission(request, self, employee):
                return Response({"error": "You do not have permission to view this report."}, status=status.HTTP_403_FORBIDDEN)
            return [employee]
        if requester.is_superuser:
            return CustomUser.objects.employees()
        if requester.is_owner:
            return CustomUser.objects.filter(hierarchy__owner=requester)
        return [requester]

class SalaryTransactionViewSet(viewsets.ModelViewSet):
    serializer_class = SalaryTransactionSerializer
    filterset_fields = ["salary_report", "status"]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.is_owner:
            queryset = SalaryTransaction.objects.all()
        else:
            queryset = SalaryTransaction.objects.filter(salary_report__user=user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        user_filter = self.request.query_params.get('user_id')
        if user_filter:
            queryset = queryset.filter(
                salary_report__user_id=user_filter
            )

        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return SalaryTransactionCreateSerializer
        return SalaryTransactionSerializer

    @db_transaction.atomic
    def create(self, request, *args, **kwargs):
        user = request.user
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        salary_report = SalaryReport.objects.select_for_update().get(
            id=serializer.validated_data['salary_report_id']
        )

        # Permission check: only Owner (of this employee) or Admin can
        # record payments.
        if not user.is_superuser:
            owner_id = getattr(getattr(salary_report.user, "hierarchy", None), "owner_id", None)
            if not user.is_owner or owner_id != user.id:
                return Response(
                    {"detail": "You do not have permission to record payments for this report."},
                    status=status.HTTP_403_FORBIDDEN
                )

        amount_paid = serializer.validated_data['amount_paid']

        # Transactions are an immutable audit trail — always create a new
        # record for this payment rather than rewriting an existing one.
        # Supersede any stale PENDING/PROCESSING transaction instead of
        # overwriting its data.
        SalaryTransaction.objects.filter(
            salary_report=salary_report,
            status__in=['PENDING', 'PROCESSING'],
        ).update(status='CANCELLED', processed_at=timezone.localtime())

        SalaryTransaction.objects.create(
            salary_report=salary_report,
            amount_paid=amount_paid,
            payment_method=serializer.validated_data['payment_method'],
            payment_reference=serializer.validated_data.get('payment_reference', ''),
            note=serializer.validated_data.get('note', ''),
            processed_at=timezone.localtime(),
            status='SUCCESS',
        )

        # Recompute SalaryReport totals from the full SUCCESS history.
        paid_amount = SalaryTransaction.objects.filter(
            salary_report=salary_report,
            status='SUCCESS'
        ).aggregate(total=Sum('amount_paid'))['total'] or Decimal("0.00")

        salary_report.paid_amount = paid_amount
        if paid_amount >= salary_report.total_payable_amount:
            salary_report.remaining_payment = Decimal("0.00")
            salary_report.advance_amount = paid_amount - salary_report.total_payable_amount
        else:
            salary_report.remaining_payment = salary_report.total_payable_amount - paid_amount
            salary_report.advance_amount = Decimal("0.00")

        salary_report.save(
            update_fields=['paid_amount', 'remaining_payment', 'advance_amount', 'updated_at']
        )

        return Response(
            {'detail': 'Payment paid successfully.'},
            status=status.HTTP_200_OK
        )
