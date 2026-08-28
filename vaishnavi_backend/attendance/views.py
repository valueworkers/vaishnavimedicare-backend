from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from django.shortcuts import get_object_or_404
from accounts.models import CustomUser
from vaishnavi_backend.pagination import StandardResultsSetPagination
from datetime import date
from .models import Attendance, AttendanceStatus
from .utils import AttendanceCalculator
from .permissions import IsSuperUserOrOwnerOrReadOnly
from .serializers import AttendanceSerializer, AttendanceStatusSerializer

class AttendanceStatusViewSet(ModelViewSet):
    serializer_class = AttendanceStatusSerializer
    permission_classes = [IsAuthenticated, IsSuperUserOrOwnerOrReadOnly]

    def get_queryset(self):
        user = self.request.user

        # Superuser → everything
        if user.is_superuser:
            return AttendanceStatus.objects.all()

        # Global statuses (created by superuser)
        global_qs = AttendanceStatus.objects.filter(owner__is_superuser=True)

        # Owner → global + own
        if user.is_owner:
            return global_qs | AttendanceStatus.objects.filter(owner=user)

        # Staff / Manager → global + their owner's
        if hasattr(user, "hierarchy") and user.hierarchy.owner:
            return global_qs | AttendanceStatus.objects.filter(
                owner=user.hierarchy.owner
            )

        return global_qs.none()

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

class AttendanceReportView(APIView):
    def get(self, request):
        user = request.user
        user_id = request.query_params.get("user_id")
        period_type = request.query_params.get("period_type", "MONTHLY")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        # Determine which users we can see
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
            if user.is_superuser:
                target_users = CustomUser.objects.all()
            elif user.is_owner:
                target_users = CustomUser.objects.filter(hierarchy__owner=user)
            else:
                target_users = [user]

        # Build reports on the fly
        results = []
        for target_user in target_users:
            calc = AttendanceCalculator(target_user)

            if start_date and end_date:
                # Custom range — single report
                report = calc.get_attendance_for_date_range(
                    date.fromisoformat(start_date),
                    date.fromisoformat(end_date),
                )
                results.append(self._format_report(target_user, report, period_type))
            else:
                # All periods from first attendance to today
                period_reports = calc.get_all_periods_computed(
                    period_type=period_type
                )
                for period_report in period_reports:
                    results.append(self._format_report(target_user, period_report, period_type))

        # Sort by start_date descending
        results.sort(key=lambda r: r["start_date"], reverse=True)

        # Manually paginate since APIView doesn't auto-paginate
        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(results, request)
        return paginator.get_paginated_response(page)

    def _format_report(self, user, data, period_type):
        return {
            "user": user.id,
            "user_name": user.get_full_name(),
            "employee_id": getattr(user, "employee_id", None),
            "start_date": data["start_date"],
            "end_date": data["end_date"],
            "period_type": data.get("period_type", period_type),
            "present_days": data["present_days"],
            "absent_days": data["absent_days"],
            "half_day_count": data["half_day_count"],
            "paid_leave_days": data["paid_leave_days"],
            "weekly_Offs": data["weekly_Offs"],
            "unpaid_leaves": data["unpaid_leaves"],
            "total_payable_days": data["total_payable_days"],
            "total_payable_hours": data["total_payable_hours"],
        }