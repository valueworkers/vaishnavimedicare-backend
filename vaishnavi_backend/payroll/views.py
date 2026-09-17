from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import *
from .serializers import *
from .utils import SalaryCalculator 
from rest_framework import viewsets, status
from datetime import datetime, timedelta
from rest_framework.views import APIView
from dateutil.relativedelta import relativedelta
from django.db import transaction as db_transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models import Sum, OuterRef, Subquery
from vaishnavi_backend.pagination import StandardResultsSetPagination
from accounts.models import CustomUser


class EmployeePayrollListViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only payroll summary list, scoped by the same hierarchy rules
    as SalaryStructureViewSet.
    """
    serializer_class = EmployeePayrollListSerializer
    permission_classes = [IsAuthenticated]

    filterset_fields = ["user_type"]
    search_fields = [
        "first_name",
        "last_name",
        "employee_profile__employee_id",
        "employee_profile__vendor_name",
        "=email",
        "=mobile_number",
    ]

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

        return queryset.order_by("first_name", "last_name")
    
class SalaryStructureViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing salary structures
    """

    serializer_class = SalaryStructureSerializer
    permission_classes = [IsAuthenticated]

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

class SalaryReportAPIView(APIView):
    """
    Compute salary reports on-the-fly from attendance data.
    
    GET /api/salary-reports/
    GET /api/salary-reports/<id>/

    Filters:
    - Default: last 6 months
    - ?year=YYYY
    - ?start_date=YYYY-MM-DD
    - ?end_date=YYYY-MM-DD
    - ?user_id=123
    """

    def get(self, request, pk=None):
        user = request.user
        params = request.query_params

        # Initialize default date range (6 months to end of current month)
        today = datetime.now().date()
        end_date = (today.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        start_date = (end_date - relativedelta(months=6)).replace(day=1)

        # ----- Year filter (highest priority) -----
        year = params.get("year")
        if year:
            try:
                year = int(year)
                start_date = datetime(year, 1, 1).date()
                end_date = datetime(year, 12, 31).date()
            except ValueError:
                return Response(
                    {'error': 'Invalid year format'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ----- Custom date override -----
        custom_start = params.get("start_date")
        custom_end = params.get("end_date")

        if custom_start or custom_end:
            try:
                if custom_start:
                    start_date = datetime.strptime(custom_start, "%Y-%m-%d").date()
                if custom_end:
                    end_date = datetime.strptime(custom_end, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {'error': 'Invalid date format. Use YYYY-MM-DD'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ----- User filter -----
        user_id = params.get("user_id")
        
        if user_id:
            target_user = get_object_or_404(CustomUser, id=user_id)
            
            # Permission check
            if not user.is_superuser:
                if user.is_owner:
                    if not CustomUser.objects.filter(
                        id=user_id, hierarchy__owner=user
                    ).exists():
                        return Response(
                            {'error': 'You do not have permission to view this user\'s reports'},
                            status=status.HTTP_403_FORBIDDEN
                        )
                elif target_user != user:
                    return Response(
                        {'error': 'You can only view your own reports'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            target_users = [target_user]
        else:
            # Determine which users we can see
            if user.is_superuser:
                target_users = CustomUser.objects.all()
            elif user.is_owner:
                target_users = CustomUser.objects.filter(hierarchy__owner=user)
            else:
                target_users = [user]

        # ----- Build reports on the fly -----
        results = []
        for target_user in target_users:
            calc = SalaryCalculator(target_user)
            salary_reports = calc.get_salary_reports_computed(
                start_date=start_date,
                end_date=end_date
            )
            
            for report in salary_reports:
                results.append(self._format_report(target_user, report))

        # Sort by start_date descending
        results.sort(key=lambda r: r["start_date"], reverse=True)

        # ----- Handle single report retrieval -----
        if pk:
            # Find report by matching start_date or some unique identifier
            # Since we don't have DB IDs, we need to handle this differently
            # For now, return 404 as we can't retrieve by ID without DB
            return Response(
                {"detail": "Single report retrieval by ID not supported in computed mode"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(results, status=status.HTTP_200_OK)

    def _format_report(self, user, data):
        return {
            "user": user.id,
            "start_date": data["start_date"],
            "end_date": data["end_date"],
            "final_salary": float(data["final_salary"]),
            "advance_amount": float(data["advance_amount"]),
            "total_payable_amount": float(data["total_payable_amount"]),
            "paid_amount": float(data["paid_amount"]),
            "remaining_payment": float(data["remaining_payment"]),
        }

class SalaryTransactionViewSet(viewsets.ModelViewSet):
    serializer_class = SalaryTransactionSerializer
    filterset_fields = ["salary_report", "status"]

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            queryset = SalaryTransaction.objects.all()
        elif user.is_owner:
            queryset = SalaryTransaction.objects.filter(salary_report__user__hierarchy__owner=user)
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

        # Permission Check: Only Owner or Admin can create transactions for their staff
        if not user.is_superuser:
            if not user.is_owner or salary_report.user.hierarchy.owner != user:
                return Response(
                    {"detail": "You do not have permission to record payments for this report."},
                    status=status.HTTP_403_FORBIDDEN
                )

        amount_paid = serializer.validated_data['amount_paid']

        existing_transaction = SalaryTransaction.objects.filter(
            salary_report=salary_report
        ).order_by('-created_at').first()

        if existing_transaction and existing_transaction.status in ['PENDING', 'PROCESSING']:
            existing_transaction.status = 'SUCCESS'
            existing_transaction.amount_paid = amount_paid
            existing_transaction.payment_method = serializer.validated_data['payment_method']
            existing_transaction.payment_reference = serializer.validated_data.get('payment_reference', '')
            existing_transaction.note = serializer.validated_data.get('note', '')
            existing_transaction.processed_at = timezone.localtime()
            existing_transaction.save()
        else:
            SalaryTransaction.objects.create(
                salary_report=salary_report,
                amount_paid=amount_paid,
                payment_method=serializer.validated_data['payment_method'],
                payment_reference=serializer.validated_data.get('payment_reference', ''),
                note=serializer.validated_data.get('note', ''),
                processed_at=timezone.localtime(),
                status='SUCCESS',
            )

        # Update SalaryReport totals
        paid_amount = SalaryTransaction.objects.filter(
            salary_report=salary_report,
            status='SUCCESS'
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        salary_report.paid_amount = paid_amount
        salary_report.remaining_payment = salary_report.total_payable_amount - paid_amount
        salary_report.advance_amount += max(paid_amount - salary_report.total_payable_amount, 0)
        salary_report.save(
            update_fields=['paid_amount', 'remaining_payment', 'advance_amount', 'updated_at']
        )

        return Response(
            {'detail': 'Payment paid successfully.'},
            status=status.HTTP_200_OK
        )