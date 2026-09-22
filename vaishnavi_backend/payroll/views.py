from decimal import Decimal
from rest_framework import mixins, viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import action
from .models import *
from .serializers import *
from .permissions import CanViewSalaryReport, IsOwnerOrReadOnly
from datetime import datetime
from django.db import transaction as db_transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models import Sum, OuterRef, Subquery
from accounts.models import CustomUser
from accounts.permissions import IsOwner
from .tasks import queue_salary_report_refresh

from rest_framework.pagination import CursorPagination


class AttendanceCursorPagination(CursorPagination):
    page_size = 25
    ordering = ("-date", "id")   # tuple → DRF appends `id` as the tiebreaker
    cursor_query_param = "cursor"

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
    """
    GET: List all attendance records with filters
    POST: Create or Update attendance
    If attendance exists for user+date, update it. Otherwise create new.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        # Admin → see everything
        if user.is_superuser:
            queryset = Attendance.objects.all()
        # Owner → see attendance of their staff + managers
        elif user.is_owner:
            queryset = Attendance.objects.filter(user__hierarchy__owner=user)
        # Staff or Manager → see only their own attendance
        else:
            queryset = Attendance.objects.filter(user=user)

        # Apply filters from query parameters
        user_id = request.query_params.get('user_id', None)
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        
        start_date = request.query_params.get('start_date', None)
        end_date = request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        
        status_code = request.query_params.get('status', None)
        if status_code:
            queryset = queryset.filter(status__code=status_code)
        
        date = request.query_params.get('date', None)
        if date:
            queryset = queryset.filter(date=date)

        queryset = queryset.select_related('user', 'status').order_by('-date')
        serializer = AttendanceSerializer(queryset, many=True)
        
        return Response({
            'count': queryset.count(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request):
        user_id = request.data.get('user')
        date = request.data.get('date')

        # Validate required fields
        if not user_id:
            return Response(
                {'error': 'user field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not date:
            return Response(
                {'error': 'date field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if attendance already exists
        try:
            attendance = Attendance.objects.select_related('user', 'status').get(
                user_id=user_id, 
                date=date
            )
            # Update existing attendance
            serializer = AttendanceSerializer(attendance, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(
                    {
                        'message': 'Attendance updated successfully',
                        'data': serializer.data
                    },
                    status=status.HTTP_200_OK
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        except Attendance.DoesNotExist:
            # Create new attendance
            serializer = AttendanceSerializer(data=request.data)
            if serializer.is_valid():
                serializer.save()
                return Response(
                    {
                        'message': 'Attendance created successfully',
                        'data': serializer.data
                    },
                    status=status.HTTP_201_CREATED
                )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SalaryReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Read-only access to the persisted SalaryReport table.

    GET  /reports/?user_id=5&start_date=2026-04-01&end_date=2026-09-30&is_finalized=false
    GET  /reports/<id>/
    POST /reports/refresh/            body: {"user_id": 5}
    POST /reports/<id>/finalize/       -- locks that one report
    """

    serializer_class = SalaryReportSerializer
    permission_classes = [CanViewSalaryReport]

    def get_queryset(self):
        user = self.request.user
        qs = SalaryReport.objects.all() if (user.is_superuser or user.is_owner) else SalaryReport.objects.filter(user=user)

        user_id = self.request.query_params.get("user_id")
        if user_id:
            qs = qs.filter(user_id=user_id)

        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        if start_date:
            qs = qs.filter(start_date__gte=start_date)
        if end_date:
            qs = qs.filter(end_date__lte=end_date)

        is_finalized = self.request.query_params.get("is_finalized")
        if is_finalized is not None:
            qs = qs.filter(is_finalized=is_finalized.lower() in ("1", "true", "yes"))

        return qs.select_related("user").order_by("-start_date")

    @action(detail=False, methods=["post"])
    def refresh(self, request):
        """Manually trigger the same task the signals fire -- for support/debug use."""
        user_id = request.data.get("user_id")
        if not user_id:
            return Response({"error": "user_id is required"}, status=400)

        if not (request.user.is_superuser or request.user.is_owner or str(request.user.id) == str(user_id)):
            return Response({"detail": "You do not have permission to refresh this user's reports."}, status=403)

        # Finalized reports are protected inside refresh_salary_reports()
        # itself (see tasks.py) -- queuing here is safe either way, it just
        # won't touch any period that's already locked.
        queue_salary_report_refresh(int(user_id), countdown=0)
        return Response({"detail": f"Refresh queued for user {user_id}."})

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        """Locks this one report so it's never overwritten by a future refresh."""
        report = self.get_object()
        if not (request.user.is_superuser or request.user.is_owner):
            return Response({"detail": "Only an owner or admin can finalize a report."}, status=403)

        if report.is_finalized:
            return Response({"detail": "Already finalized."})

        report.is_finalized = True
        report.save(update_fields=["is_finalized", "updated_at"])
        return Response(SalaryReportSerializer(report).data)
    from django.db.models import OuterRef, Subquery

class SalaryTransactionViewSet(viewsets.ModelViewSet):
    serializer_class = SalaryTransactionSerializer
    filterset_fields = ["salary_report", "user", "status"]

    def get_queryset(self):
        user = self.request.user

        queryset = SalaryTransaction.objects.select_related(
            "user",
            "user__hierarchy",
            "salary_report",
        )

        if not (user.is_superuser or user.is_owner):
            queryset = queryset.filter(user=user)

        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        user_filter = self.request.query_params.get('user_id')
        if user_filter:
            queryset = queryset.filter(user_id=user_filter)

        # Applicable SalaryStructure's split fields, computed once per
        # row via correlated subquery instead of a per-row DB hit in
        # the serializer.
        latest_structure = SalaryStructure.objects.filter(
            user=OuterRef('user_id'),
            effective_from__lte=OuterRef('salary_report__start_date'),
        ).order_by('-effective_from')

        queryset = queryset.annotate(
            structure_basic=Subquery(latest_structure.values('amount')[:1]),
            structure_pf=Subquery(latest_structure.values('pf_amount')[:1]),
            structure_esi=Subquery(latest_structure.values('esi_amount')[:1]),
            structure_final=Subquery(latest_structure.values('final_salary')[:1]),
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

        salary_report = SalaryReport.objects.select_related('user').select_for_update().get(
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
            user=salary_report.user,
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