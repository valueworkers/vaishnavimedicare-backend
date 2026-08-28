import calendar
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from attendance.models import Attendance, AttendanceStatus
from payroll.models import SalaryStructure, SalaryTransaction

from django.db.models import (
    Count,
    Sum,
    Q
)
from django.db.models.functions import TruncMonth, TruncDay
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from booking.models import SecondaryOrder, TernaryOrder, TotalInvoice, Payment, PaymentMethod

from .filters import (
    ALLOWED_EMPLOYEE_SORT_FIELDS,
    build_employee_filters,
    build_period_filters,
    build_sort,
)
from .mixins import PermissionScopeMixin
from .serializers import (
    EmployeeSalaryAnalysisSerializer,
    UserAttendanceSerializer,
    MonthlyAnalyticsResponseSerializer,
    InvoiceListSerializer,
)


ZERO = Decimal("0.00")


class SalaryAnalysisAPIView(PermissionScopeMixin, APIView):
    """
    Returns paginated salary analysis per employee with period-wise breakdown.
    Computes data on-the-fly from Attendance and SalaryStructure.

    Query Params:
    - Employee filters:
        user_id, user_type, emp_id, emp_id__icontains,
        first_name__icontains, last_name__icontains,
        mobile_number, search, status (active|inactive|all)

    - Period filters:
        start_date, start_date__gte, start_date__lte,
        end_date, end_date__gte, end_date__lte,
        total_salary__gte/lte, amount_paid__gte/lte

    - Sorting:
        sort_by (comma-separated), sort_dir (asc|desc)

    DB queries per request (regardless of page size)
    --------------------------------------------------
        Q1  employee queryset          (paginated)
        Q2  Attendance bulk fetch      (all employees in page, all dates)
        Q3  SalaryTransaction bulk     (all employees in page)
        Q4  SalaryStructure bulk       (all employees in page)
        Q5  AttendanceStatus           (once per process, module-level cache)

    Permission scoping (via PermissionScopeMixin):
        Superuser  → all employees
        Owner      → employees in their hierarchy
        Staff/Mgr  → only themselves
    """

    pagination_class = api_settings.DEFAULT_PAGINATION_CLASS

    ZERO = Decimal("0")
    ONE_CENT = Decimal("0.01")

    _ATTENDANCE_STATUSES = None  # lazy-loaded on first request
    
    DAYS_MAP = {
        "HOURLY":      Decimal("8"),
        "DAILY":       Decimal("1"),
        "WEEKLY":      Decimal("7"),
        "FORTNIGHTLY": Decimal("14"),
        "MONTHLY":     Decimal("30"),
    }
    
    PERIOD_FIELD_MAP = {
        "start_date":           "start_date",
        "end_date":             "end_date",
        "total_payable_amount": "total_salary",
        "paid_amount":          "amount_paid",
        "excess_balance":       "excess_balance",
        "calendar_days":        "calendar_days",
        "days_present":         "total_payable_days",
        "salary":               "salary",
    }
    
    def load_attendance_statuses(self):
        qs = AttendanceStatus.objects.filter(owner__is_superuser=True, is_active=True)
        keys = ["present", "absent", "paid_leave", "half_day", "weekly_off", "unpaid_leave"]
        return {k: qs.filter(code__icontains=k.upper()).first() for k in keys}

    def _get_statuses(self):
        if self._ATTENDANCE_STATUSES is None:
            self._ATTENDANCE_STATUSES = self.load_attendance_statuses()
        return self._ATTENDANCE_STATUSES

    def _get_monthly_period(self,base: date):
        first = base.replace(day=1)
        last = calendar.monthrange(base.year, base.month)[1]
        return first, base.replace(day=last)

    def _iter_monthly_periods(self,first_date: date, end_date: date):
        """Yield (period_start, period_end) tuples from first_date to end_date."""
        current = first_date.replace(day=1)
        while current <= end_date:
            start, end = self._get_monthly_period(current)
            yield start, end
            # advance to next month
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

    def _bulk_attendance_by_employee(self,employee_ids: list, statuses: dict) -> dict:
        """
        Fetch all Attendance rows for the given employee_ids in ONE query,
        then aggregate per (employee_id, period_start, period_end) in Python.

        Returns:
            {
                employee_id: {
                    (start_date, end_date): {
                        'present_days': int,
                        'absent_days': int,
                        'half_day_count': int,
                        'paid_leave_days': int,
                        'weekly_offs': int,
                        'unpaid_leaves': int,
                        'total_payable_days': Decimal,
                        'total_duration_seconds': Decimal,
                    }
                }
            }
        """
        # Build reverse map: status_id → key
        status_id_map = {}
        for key, obj in statuses.items():
            if obj is not None:
                status_id_map[obj.pk] = key

        # Single query — fetch only the columns we need
        rows = (
            Attendance.objects
            .filter(user_id__in=employee_ids)
            .values("user_id", "date", "status_id", "duration")
        )

        # First pass: bucket each row into its monthly period
        # structure: raw_buckets[emp_id][(period_start, period_end)] = list of rows
        raw_buckets: dict = defaultdict(lambda: defaultdict(list))

        for row in rows:
            period_start, period_end = self._get_monthly_period(row["date"])
            raw_buckets[row["user_id"]][(period_start, period_end)].append(row)

        # Second pass: aggregate counts per bucket
        result: dict = defaultdict(dict)

        for emp_id, periods in raw_buckets.items():
            for (p_start, p_end), period_rows in periods.items():
                counts = defaultdict(int)
                total_secs = Decimal("0")

                for row in period_rows:
                    key = status_id_map.get(row["status_id"])
                    if key:
                        counts[key] += 1
                    if row["duration"]:
                        total_secs += Decimal(row["duration"].total_seconds())

                present     = counts["present"]
                half_day    = counts["half_day"]
                paid_leave  = counts["paid_leave"]
                payable     = Decimal(present) + Decimal(paid_leave) + Decimal("0.5") * Decimal(half_day)

                result[emp_id][(p_start, p_end)] = {
                    "present_days":          present,
                    "absent_days":           counts["absent"],
                    "half_day_count":        half_day,
                    "paid_leave_days":       paid_leave,
                    "weekly_offs":           counts["weekly_off"],
                    "unpaid_leaves":         counts["unpaid_leave"],
                    "total_payable_days":    payable,
                    "total_duration_seconds": total_secs,
                }

        return result

    def _bulk_paid_amounts(self,employee_ids: list) -> dict:
        """
        Fetch all SUCCESS SalaryTransactions for the given employees in ONE query.

        Returns:
            { (employee_id, start_date, end_date): Decimal(total_paid) }
        """
        rows = (
            SalaryTransaction.objects
            .filter(salary_report__user_id__in=employee_ids, status="SUCCESS")
            .values(
                "salary_report__user_id",
                "salary_report__start_date",
                "salary_report__end_date",
                "amount_paid",
            )
        )

        totals: dict = defaultdict(Decimal)
        for row in rows:
            key = (
                row["salary_report__user_id"],
                row["salary_report__start_date"],
                row["salary_report__end_date"],
            )
            totals[key] += row["amount_paid"] or ZERO

        return totals

    def _bulk_salary_structures(self,employee_ids: list) -> dict:
        """
        Fetch all relevant SalaryStructure rows in ONE query, ordered by
        effective_from ascending.

        Returns:
            { employee_id: [SalaryStructure, ...] }   (sorted by effective_from asc)
        """
        qs = (
            SalaryStructure.objects
            .filter(
                user_id__in=employee_ids,
                change_type__in=["BASE_SALARY", "INCREMENT"],
            )
            .order_by("user_id", "effective_from")
        )

        result: dict = defaultdict(list)
        for obj in qs:
            result[obj.user_id].append(obj)

        return result

    def _get_salary_snapshot_from_list(self,structures: list, check_date: date):
        """
        Equivalent to SalaryCalculator.get_salary_snapshot but operates on a
        pre-fetched list — no DB hit.
        Returns the most recent SalaryStructure with effective_from <= check_date.
        """
        best = None
        for s in structures:
            if s.effective_from <= check_date:
                best = s
            else:
                break  # list is sorted asc, so we can stop early
        return best

    def _daily_rate(self,salary_obj) -> Decimal:
        if not salary_obj:
            return ZERO
        divisor = self.DAYS_MAP.get(salary_obj.salary_type, Decimal("30"))
        return salary_obj.final_salary / divisor

    def _calc_amount(self,daily_rate: Decimal, payable_days: Decimal) -> Decimal:
        return (daily_rate * payable_days).quantize(self.ONE_CENT, rounding=ROUND_HALF_UP)

    def _payment_status(self,paid_amount: Decimal, total_payable: Decimal) -> str:
        excess = paid_amount - total_payable
        if excess >= 0:
            return "Paid"
        if paid_amount == 0:
            return "Unpaid"
        return "Partially Paid"

    def _build_salary_periods(
        self,
        emp,
        attendance_by_period: dict,   # { (start, end): agg_dict }
        salary_structures: list,      # sorted asc by effective_from
        paid_amounts: dict,           # { (emp_id, start, end): Decimal }
        period_order_by: list,
    ) -> list:
        """
        Compute all salary period dicts for one employee.
        Pure Python — zero DB queries.
        """
        # Determine date range from attendance data
        if not attendance_by_period:
            return []

        all_periods_sorted = sorted(attendance_by_period.keys())  # (start, end) tuples
        today = date.today()

        # We iterate periods in chronological order to carry forward correctly
        carry_forward = ZERO
        salary_cache = {}
        results = []

        for (p_start, p_end) in all_periods_sorted:
            att = attendance_by_period[(p_start, p_end)]

            # Salary snapshot — cached by end_date
            if p_end not in salary_cache:
                salary_cache[p_end] = self._get_salary_snapshot_from_list(salary_structures, p_end)
            salary_obj = salary_cache[p_end]

            daily_rate   = self._daily_rate(salary_obj)
            payable_days = att["total_payable_days"]
            total_days   = Decimal((p_end - p_start).days + 1)

            # Full-month shortcut
            if (
                salary_obj
                and salary_obj.salary_type == "MONTHLY"
                and (payable_days > 30 or payable_days == total_days)
            ):
                total_amount = salary_obj.final_salary
            else:
                total_amount = self._calc_amount(daily_rate, payable_days)

            paid_amount = paid_amounts.get((emp.id, p_start, p_end), ZERO)

            remaining = paid_amount - total_amount + carry_forward
            carry_forward = remaining

            calendar_days   = int(total_days)
            absent_days     = Decimal(att["absent_days"])
            unpaid_leaves   = Decimal(att["unpaid_leaves"])
            half_day_count  = Decimal(att["half_day_count"])
            total_unpaid    = absent_days + unpaid_leaves + Decimal("0.5") * half_day_count
            excess_balance  = paid_amount - total_amount
            attendance_pct  = (
                round((float(payable_days) / calendar_days) * 100, 2)
                if calendar_days > 0 else 0
            )

            results.append({
                "start_date":         p_start,
                "end_date":           p_end,
                "calendar_days":      calendar_days,
                "attendance_pct":     attendance_pct,
                "total_payable_days": payable_days,
                "total_unpaid_days":  total_unpaid,
                "salary":             salary_obj.final_salary if salary_obj else ZERO,
                "total_salary":       total_amount,
                "payment_status":     self._payment_status(paid_amount, total_amount),
                "amount_paid":        paid_amount,
                "excess_balance":     excess_balance,
            })

        return results

    def _build_summary(self,all_periods: list) -> dict:
        total_salary   = ZERO
        total_paid     = ZERO
        total_excess   = ZERO
        total_payable  = 0
        total_calendar = 0

        for p in all_periods:
            total_salary   += p["total_salary"]
            total_paid     += p["amount_paid"]
            total_excess   += p["excess_balance"]
            total_payable  += int(p["total_payable_days"])
            total_calendar += p["calendar_days"]

        attendance_pct = (
            round((total_payable / total_calendar) * 100, 2)
            if total_calendar > 0 else None
        )

        return {
            "totals": {
                "total_salary":        total_salary,
                "total_amount_paid":   total_paid,
                "total_excess_balance": total_excess,
            },
            "attendance": {
                "total_days_present":   total_payable,
                "total_attendance_pct": attendance_pct,
            },
        }

    def _apply_period_filters(self,periods: list, period_q) -> list:
        if not period_q.children:
            return periods

        filtered = []
        for period in periods:
            include = True
            for child in period_q.children:
                if not isinstance(child, tuple):
                    continue
                field, value = child

                if field == "start_date"                and period["start_date"] != value:        include = False
                elif field == "start_date__gte"         and period["start_date"] < value:         include = False
                elif field == "start_date__lte"         and period["start_date"] > value:         include = False
                elif field == "end_date"                and period["end_date"] != value:          include = False
                elif field == "end_date__gte"           and period["end_date"] < value:           include = False
                elif field == "end_date__lte"           and period["end_date"] > value:           include = False
                elif field == "total_payable_amount__gte" and period["total_salary"] < value:     include = False
                elif field == "total_payable_amount__lte" and period["total_salary"] > value:     include = False
                elif field == "paid_amount__gte"        and period["amount_paid"] < value:        include = False
                elif field == "paid_amount__lte"        and period["amount_paid"] > value:        include = False

            if include:
                filtered.append(period)

        return filtered

    def _sort_periods(self,periods: list, period_order_by: list) -> list:
        if not periods or not period_order_by:
            return periods

        # Apply sorts in reverse so the first field in the list is the primary key
        for order_expr in reversed(period_order_by):
            reverse = order_expr.startswith("-")
            raw_field = order_expr.lstrip("-")
            actual_field = self.PERIOD_FIELD_MAP.get(raw_field, raw_field)
            periods = sorted(
                periods,
                key=lambda x: x.get(actual_field) or ZERO,
                reverse=reverse,
            )

        return periods

    def get(self, request):
        params = request.query_params
        errors = {}

        emp_q,    emp_errors    = build_employee_filters(params)
        period_q, period_errors = build_period_filters(params)
        order_by, sort_errors   = build_sort(params)

        if emp_errors:
            errors["employee_filters"] = emp_errors
        if period_errors:
            errors["period_filters"] = period_errors
        if sort_errors:
            errors["sort"] = sort_errors

        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        # ── Sort levels ──────────────────────────────────────────────────
        from .filters import ALLOWED_EMPLOYEE_SORT_FIELDS
        emp_sort_fields  = set(ALLOWED_EMPLOYEE_SORT_FIELDS.values())
        employee_order_by = [o for o in order_by if o.lstrip("-") in emp_sort_fields] or ["id"]
        period_order_by   = [o for o in order_by if o.lstrip("-") not in emp_sort_fields] or ["-start_date"]

        # ── Q1: Scoped + paginated employee queryset ─────────────────────
        employee_qs = (
            self.get_user_queryset(request)
            .filter(emp_q)
            .order_by(*employee_order_by)
        )

        paginator     = self.pagination_class()
        paginated_emps = paginator.paginate_queryset(employee_qs, request, view=self)
        employee_ids   = [e.id for e in paginated_emps]

        if not employee_ids:
            # Empty page — skip all bulk queries
            serializer = EmployeeSalaryAnalysisSerializer([], many=True)
            response   = paginator.get_paginated_response(serializer.data)
            response.data["summary"] = self._build_summary([])
            return response

        # ── Load module-level status cache (Q5, once per process) ────────
        statuses = self._get_statuses()

        # ── Q2: Bulk attendance fetch ────────────────────────────────────
        # Returns { emp_id: { (start, end): agg_dict } }
        attendance_by_emp = self._bulk_attendance_by_employee(employee_ids, statuses)

        # ── Q3: Bulk salary transactions ─────────────────────────────────
        # Returns { (emp_id, start, end): Decimal }
        paid_amounts = self._bulk_paid_amounts(employee_ids)

        # ── Q4: Bulk salary structures ───────────────────────────────────
        # Returns { emp_id: [SalaryStructure sorted asc] }
        salary_structures_by_emp = self._bulk_salary_structures(employee_ids)

        # ── Compute, filter, sort periods per employee ───────────────────
        periods_by_user: dict = {}
        all_periods: list     = []

        for emp in paginated_emps:
            periods = self._build_salary_periods(
                emp,
                attendance_by_period   = attendance_by_emp.get(emp.id, {}),
                salary_structures      = salary_structures_by_emp.get(emp.id, []),
                paid_amounts           = paid_amounts,
                period_order_by        = period_order_by,
            )

            # Filter
            periods = self._apply_period_filters(periods, period_q)

            # Sort
            periods = self._sort_periods(periods, period_order_by)

            periods_by_user[emp.id] = periods
            all_periods.extend(periods)          # single pass — no double flatten

        # ── Serialize ────────────────────────────────────────────────────
        results = [
            {
                "id":            emp.id,
                "emp_id":        emp.employee_id,
                "first_name":    emp.first_name,
                "middle_name":   emp.middle_name,
                "last_name":     emp.last_name,
                "mobile_number": emp.mobile_number,
                "status":        emp.is_active,
                "periods":       periods_by_user.get(emp.id, []),
            }
            for emp in paginated_emps
        ]

        serializer = EmployeeSalaryAnalysisSerializer(results, many=True)
        response   = paginator.get_paginated_response(serializer.data)
        response.data["summary"] = self._build_summary(all_periods)
        return response        


class UserAttendanceAPIView(PermissionScopeMixin, APIView):
    """
    Retrieve attendance data for users.
    Computes data on-the-fly from Attendance records.

    Permission scoping (via PermissionScopeMixin):
        - Superuser  → all users / all attendance
        - Owner      → users in their hierarchy
        - Staff/Mgr  → only themselves

    Behavior:
        - If `user_id` is provided → single user (no pagination).
          Returns 404 if the requested user is outside the requester's scope.
        - If `user_id` is not provided → paginated list of scoped users.

    Query Parameters:
        user_id     (int,  optional) - specific user ID
        start_month (str,  optional) - YYYY-MM  (inclusive)
        end_month   (str,  optional) - YYYY-MM  (inclusive)
        page        (int,  optional) - page number
        page_size   (int,  optional) - items per page
    """

    pagination_class = api_settings.DEFAULT_PAGINATION_CLASS

    # Entry point

    def get(self, request):
        user_id = request.query_params.get("user_id")
        start_month = request.query_params.get("start_month")
        end_month = request.query_params.get("end_month")

        if user_id:
            return self._get_single_user(request, user_id, start_month, end_month)
        return self._get_all_users(request, start_month, end_month)

    # Private helpers
    def _get_single_user(self, request, user_id, start_month, end_month):
        # Scope the lookup — prevents accessing users outside the requester's scope.
        try:
            user = self.get_user_queryset(request).get(pk=user_id)
        except Exception:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        qs = (
            self.get_attendance_queryset(request)
            .filter(user=user)
            .select_related("status")
        )
        qs = self._apply_date_filters(qs, start_month, end_month)

        data = {
            "user": user.id,
            "attendance": self._build_attendance(qs).get(user.id, {}),
        }
        return Response(UserAttendanceSerializer(data).data)

    def _get_all_users(self, request, start_month, end_month):

        # Employee Filters
        employee_q, employee_errors = build_employee_filters(
            request.query_params
        )

        # Sorting
        order_by, sort_errors = build_sort(request.query_params)

        errors = employee_errors + sort_errors

        if errors:
            return Response(
                {"errors": errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Permission Scoped Users
        user_qs = (
            self.get_user_queryset(request)
            .filter(employee_q)
        )
        
        # Apply Sorting
        if order_by:
            user_qs = user_qs.order_by(*order_by)
        else:
            user_qs = user_qs.order_by("id")

        # Pagination
        paginator = self.pagination_class()

        paginated_users = paginator.paginate_queryset(
            user_qs,
            request,
            view=self
        )

        paginated_ids = [u.id for u in paginated_users]

        # Attendance Query
        qs = (
            self.get_attendance_queryset(request)
            .filter(user__id__in=paginated_ids)
            .select_related("user", "status")
        )

        qs = self._apply_date_filters(qs, start_month, end_month)

        # Attendance Grouping
        attendance_map = self._build_attendance(qs)

        result = [
            {
                "user": user.id,
                "attendance": attendance_map.get(user.id, {}),
            }
            for user in paginated_users
        ]

        serializer = UserAttendanceSerializer(result, many=True)

        return paginator.get_paginated_response(serializer.data)

    # Date filtering
    def _apply_date_filters(self, qs, start_month, end_month):
        if start_month:
            year, month = map(int, start_month.split("-"))
            qs = qs.filter(date__gte=f"{year}-{month:02d}-01")

        if end_month:
            year, month = map(int, end_month.split("-"))
            last_day = calendar.monthrange(year, month)[1]
            qs = qs.filter(date__lte=f"{year}-{month:02d}-{last_day}")

        return qs

    # Attendance grouping

    def _build_attendance(self, qs):
        """
        Group queryset into:
            { user_id -> { 'Mon-YYYY' -> { 'DD': 'P/A/H/PL/UL' } } }
        Both months and days are sorted chronologically.
        """
        grouped = defaultdict(lambda: defaultdict(dict))

        for record in qs:
            month_key = record.date.strftime("%b'%Y")
            day_key = record.date.strftime("%d")
            grouped[record.user_id][month_key][day_key] = self._map_status(
                record.status.label
            )

        return {
            user_id: {
                month: dict(sorted(days.items()))
                for month, days in sorted(
                    months.items(),
                    key=lambda x: self._month_sort_key(x[0]),
                )
            }
            for user_id, months in grouped.items()
        }

    @staticmethod
    def _map_status(label: str) -> str:
        """
        Dynamically map status label to abbreviation by taking first letter of each word.
        Words can be separated by space, comma, dash, or underscore.
        
        Examples:
            "Present" -> "P"
            "Absent" -> "A"
            "Half Day" -> "HD"
            "Paid Leave" -> "PL"
        """
        if not label:
            return "?"
        
        # Replace separators with spaces for uniform splitting
        normalized = label.replace(',', ' ').replace('-', ' ').replace('_', ' ')
        
        # Split into words and take first letter of each
        words = normalized.split()
        
        if not words:
            return "?"
        
        # Take first letter of each word, capitalize, and join
        abbreviation = ''.join(word[0].upper() for word in words if word)
        
        return abbreviation if abbreviation else "?"

    @staticmethod
    def _month_sort_key(month_str: str):
        from datetime import datetime
        return datetime.strptime(month_str, "%b'%Y")

class PaymentMasterViewSet(viewsets.ViewSet):
    """
    ViewSet for monthly performance across invoices, bookings, and payments.
    
    Supports Calendar Year (CY) and Financial Year (FY) filtering.
    Financial Year: April - March (e.g., FY2025 = Apr 2024 - Mar 2025)

    Endpoints:
        GET /api/month-wise-performance/
        GET /api/month-wise-performance/?year=2024&month=3&year_type=CY
        GET /api/month-wise-performance/?year=2025&year_type=FY
        GET /api/daily-collection/?year=2025&month=3&year_type=CY
        GET /api/payment-mode-analytics/?year=2025&month=12&year_type=FY
    
    Query Parameters:
        - year (int): Year to filter by. Default: current year
        - month (int): Month 1-12. Optional for monthly data, required for daily data
        - year_type (str): 'CY' for Calendar Year or 'FY' for Financial Year. Default: 'CY'
    """

    DIGITAL_METHODS = {PaymentMethod.UPI, PaymentMethod.CARD, PaymentMethod.BANK}
    CASH_METHODS = {PaymentMethod.CASH}
    CHEQUE_METHODS = {PaymentMethod.CHEQUE}
    
    # Financial Year config: starts in April (month 4)
    FY_START_MONTH = 4

    # ── Year type helpers ──────────────────────────────────────────────────────

    def _get_fy_range(self, fy_year):
        """
        Get (start_year, start_month, end_year, end_month) for a financial year.
        
        FY2025 = Apr 2024 to Mar 2025
        Parameters:
            fy_year: Financial year (e.g., 2025)
        Returns:
            (start_year, start_month, end_year, end_month)
        """
        return (fy_year - 1, self.FY_START_MONTH, fy_year, self.FY_START_MONTH - 1)

    def _current_fy(self):
        """Get current financial year."""
        today = date.today()
        if today.month < self.FY_START_MONTH:
            return today.year
        return today.year + 1

    def _cy_to_fy(self, cy_year, cy_month):
        """
        Convert calendar year/month to financial year.
        Returns fy_year (which FY does this month belong to)
        """
        if cy_month >= self.FY_START_MONTH:
            return cy_year + 1
        return cy_year

    # ── Filter parsers ─────────────────────────────────────────────────────────

    def _parse_filters(self, request):
        """
        Parse year/month/year_type query params.
        Month=0 means all months.
        year_type: 'CY' (default) or 'FY'
        """
        year_param = request.query_params.get("year")
        month_param = request.query_params.get("month")
        year_type_param = request.query_params.get("year_type", "CY").upper()

        if year_type_param not in ("CY", "FY"):
            raise ValidationError("year_type must be 'CY' or 'FY'.")

        if not year_param:
            if year_type_param == "FY":
                year = self._current_fy()
            else:
                year = date.today().year
        else:
            try:
                year = int(year_param)
            except ValueError:
                raise ValidationError("Year must be a valid integer.")

        if month_param:
            try:
                month = int(month_param)
            except ValueError:
                raise ValidationError("Month must be a valid integer between 1 and 12.")
            if not 1 <= month <= 12:
                raise ValidationError("Month must be between 1 and 12.")
        else:
            month = 0

        return year, month, year_type_param

    def _parse_daily_filters(self, request):
        """
        Parse required year/month for day-level granularity.
        year_type: 'CY' (default) or 'FY'
        """
        year_param = request.query_params.get("year")
        month_param = request.query_params.get("month")
        year_type_param = request.query_params.get("year_type", "CY").upper()

        if year_type_param not in ("CY", "FY"):
            raise ValidationError("year_type must be 'CY' or 'FY'.")

        try:
            year = int(year_param) if year_param else (
                self._current_fy() if year_type_param == "FY" else date.today().year
            )
            month = int(month_param) if month_param else date.today().month
        except ValueError:
            raise ValidationError("Year and month must be valid integers.")

        if not 1 <= month <= 12:
            raise ValidationError("Month must be between 1 and 12.")

        return year, month, year_type_param

    # ── Shared queryset helpers ────────────────────────────────────────────────

    def _base_payment_qs(self, year, month, year_type="CY"):
        """
        Build base payment queryset filtered by year/month.
        Includes fully paid AND partially paid payments.
        year_type: 'CY' for calendar year, 'FY' for financial year
        """
        if year_type == "FY":
            qs = self._base_payment_qs_fy(year, month)
        else:
            qs = self._base_payment_qs_cy(year, month)
        return qs

    def _base_payment_qs_cy(self, year, month):
        """
        Calendar year queryset.
        Includes payments linked to fully paid AND partially paid invoices.
        """
        qs = Payment.objects.filter(
            paid_date__year=year
        ).filter(
            Q(invoice__isnull=True) |
            Q(invoice__status__in=["PAID", "PARTIALLY_PAID"])
        )
        if month:
            qs = qs.filter(paid_date__month=month)
        return qs

    def _base_payment_qs_fy(self, fy_year, month):
        """
        Financial year queryset.
        FY2025 = Apr 2024 to Mar 2025
        Includes payments linked to fully paid AND partially paid invoices.
        
        If month specified (1-12): filter to that month across both calendar years
        If month=0: include all months in the FY
        """
        start_year, start_month, end_year, end_month = self._get_fy_range(fy_year)

        # plus unmapped payments (invoice__isnull=True).
        status_filter = Q(invoice__isnull=True) | Q(invoice__status__in=["PAID", "PARTIALLY_PAID"])

        if month:
            if month >= start_month:
                qs = Payment.objects.filter(
                    paid_date__year=start_year,
                    paid_date__month=month,
                ).filter(status_filter)
            else:
                qs = Payment.objects.filter(
                    paid_date__year=end_year,
                    paid_date__month=month,
                ).filter(status_filter)
        else:
            qs = Payment.objects.filter(
                Q(
                    paid_date__year=start_year,
                    paid_date__month__gte=start_month
                ) | Q(
                    paid_date__year=end_year,
                    paid_date__month__lte=end_month
                )
            ).filter(status_filter)

        return qs

    def _fetch_unmapped_payments(self, year, month, year_type="CY"):
        """Fetch count of payments where invoice is None."""
        # Use raw date filter (no status constraint) for unmapped payments
        if year_type == "FY":
            start_year, start_month, end_year, end_month = self._get_fy_range(year)
            if month:
                if month >= start_month:
                    qs = Payment.objects.filter(
                        invoice__isnull=True,
                        paid_date__year=start_year,
                        paid_date__month=month,
                    )
                else:
                    qs = Payment.objects.filter(
                        invoice__isnull=True,
                        paid_date__year=end_year,
                        paid_date__month=month,
                    )
            else:
                qs = Payment.objects.filter(
                    invoice__isnull=True,
                ).filter(
                    Q(paid_date__year=start_year, paid_date__month__gte=start_month) |
                    Q(paid_date__year=end_year, paid_date__month__lte=end_month)
                )
        else:
            qs = Payment.objects.filter(invoice__isnull=True, paid_date__year=year)
            if month:
                qs = qs.filter(paid_date__month=month)

        return (
            qs
            .annotate(month=TruncMonth("paid_date"))
            .values("month")
            .annotate(
                unmapped_count=Count("id"),
                unmapped_amount=Sum("amount")
            )
            .order_by("month")
        )

    def _fetch_invoice_data(self, year, month, year_type="CY"):
        """Fetch invoice data for year/month."""
        if year_type == "FY":
            qs = self._fetch_invoice_data_fy(year, month)
        else:
            qs = self._fetch_invoice_data_cy(year, month)
        return qs

    def _fetch_invoice_data_cy(self, year, month):
        """
        Calendar year invoice data.
        """
        qs = TotalInvoice.objects.filter(issued_date__year=year)
        if month:
            qs = qs.filter(issued_date__month=month)
        return (
            qs
            .annotate(month=TruncMonth("issued_date"))\
            .values("month")
            .annotate(
                invoice_value=Sum("total_amount", default=ZERO),
                unpaid_invoices=Count("id", filter=~Q(status__in=["PAID", "PARTIALLY_PAID"])),
                paid_invoices=Count("id", filter=Q(status="PAID")),
                partially_paid_invoices=Count("id", filter=Q(status="PARTIALLY_PAID")),  
                generated_invoices=Count("id"),
            )
            .order_by("month")
        )

    def _fetch_invoice_data_fy(self, fy_year, month):
        """
        Financial year invoice data.
        FY2025 = Apr 2024 to Mar 2025
        """
        start_year, start_month, end_year, end_month = self._get_fy_range(fy_year)

        if month:
            if month >= start_month:
                qs = TotalInvoice.objects.filter(
                    issued_date__year=start_year,
                    issued_date__month=month
                )
            else:
                qs = TotalInvoice.objects.filter(
                    issued_date__year=end_year,
                    issued_date__month=month
                )
        else:
            qs = TotalInvoice.objects.filter(
                Q(
                    issued_date__year=start_year,
                    issued_date__month__gte=start_month
                ) | Q(
                    issued_date__year=end_year,
                    issued_date__month__lte=end_month
                )
            )

        return (
            qs
            .annotate(month=TruncMonth("issued_date"))
            .values("month")
            .annotate(
                invoice_value=Sum("total_amount", default=ZERO),
                unpaid_invoices=Count("id", filter=Q(status="UNPAID")),
                paid_invoices=Count("id", filter=Q(status="PAID")),
                partially_paid_invoices=Count("id", filter=Q(status="PARTIALLY_PAID")),
                generated_invoices=Count("id"),
            )
            .order_by("month")
        )

    def _fetch_order_bookings(self, model, year, month, year_type="CY"):
        """Generic booking count fetcher for SecondaryOrder / TernaryOrder."""
        if year_type == "FY":
            qs = self._fetch_order_bookings_fy(model, year, month)
        else:
            qs = self._fetch_order_bookings_cy(model, year, month)
        return qs

    def _fetch_order_bookings_cy(self, model, year, month):
        """
        Calendar year booking data.
         Annotates both start_datetime (starting_count) and
        end_datetime (ending_count) so callers know bookings starting vs ending
        in each month.
        """
        # Bookings ending in the given CY/month
        ending_qs = model.objects.filter(end_datetime__year=year)
        if month:
            ending_qs = ending_qs.filter(end_datetime__month=month)
        ending_qs = (
            ending_qs
            .annotate(month=TruncMonth("end_datetime"))
            .values("month")
            .annotate(ending_count=Count("id"))
            .order_by("month")
        )

        # Bookings starting in the given CY/month
        starting_qs = model.objects.filter(start_datetime__year=year)
        if month:
            starting_qs = starting_qs.filter(start_datetime__month=month)
        starting_qs = (
            starting_qs
            .annotate(month=TruncMonth("start_datetime"))
            .values("month")
            .annotate(starting_count=Count("id"))
            .order_by("month")
        )

        return ending_qs, starting_qs   #  returns a tuple

    def _fetch_order_bookings_fy(self, model, fy_year, month):
        """
        Financial year booking data.
         Returns (ending_qs, starting_qs) tuple — bookings ending
        and bookings starting within the FY window.
        """
        start_year, start_month, end_year, end_month = self._get_fy_range(fy_year)

        def _build_qs(date_field):
            if month:
                if month >= start_month:
                    return model.objects.filter(
                        **{f"{date_field}__year": start_year,
                           f"{date_field}__month": month}
                    )
                else:
                    return model.objects.filter(
                        **{f"{date_field}__year": end_year,
                           f"{date_field}__month": month}
                    )
            else:
                return model.objects.filter(
                    Q(**{f"{date_field}__year": start_year,
                         f"{date_field}__month__gte": start_month}) |
                    Q(**{f"{date_field}__year": end_year,
                         f"{date_field}__month__lte": end_month})
                )

        ending_qs = (
            _build_qs("end_datetime")
            .annotate(month=TruncMonth("end_datetime"))
            .values("month")
            .annotate(ending_count=Count("id"))
            .order_by("month")
        )

        starting_qs = (
            _build_qs("start_datetime")
            .annotate(month=TruncMonth("start_datetime"))
            .values("month")
            .annotate(starting_count=Count("id"))
            .order_by("month")
        )

        return ending_qs, starting_qs   #  returns a tuple

    @staticmethod
    def _to_date(value):
        """
        Normalize a TruncMonth result to datetime.date.

        TruncMonth on a DateField  -> datetime.date   (already fine)
        TruncMonth on a DateTimeField -> datetime.datetime (needs .date())

        Keeping all monthly_map keys as plain date objects means sorted()
        never has to compare date vs datetime, which raises TypeError.
        """
        return value.date() if hasattr(value, "date") and callable(value.date) else value

    def _merge_monthly_data(
        self,
        invoice_data,
        secondary_ending, secondary_starting,   #  split into two
        ternary_ending, ternary_starting,        #  split into two
        payment_data,
        unmapped_payments,
    ):
        """Merge all data sources into monthly map."""
        monthly_map = defaultdict(lambda: {
            #  bookings_ending = bookings whose end_datetime falls in the month
            #  bookings_starting = bookings whose start_datetime falls in the month
            "bookings_ending": 0,
            "bookings_starting": 0,
            "invoice_value": ZERO,
            "amt_collected": ZERO,
            "unpaid_invoices": 0,
            "paid_invoices": 0,
            "partially_paid_invoices": 0,
            "generated_invoices": 0,
            "unmapped_count": 0,
            "unmapped_amount": 0,
        })

        for row in invoice_data:
            monthly_map[self._to_date(row["month"])].update({
                "invoice_value": row["invoice_value"] or ZERO,
                "unpaid_invoices": row["unpaid_invoices"],
                "paid_invoices": row["paid_invoices"],
                "partially_paid_invoices": row["partially_paid_invoices"],  
                "generated_invoices": row["generated_invoices"],
            })

        #  Accumulate ending counts from secondary + ternary
        for row in (*secondary_ending, *ternary_ending):
            monthly_map[self._to_date(row["month"])]["bookings_ending"] += row["ending_count"]

        #  Accumulate starting counts from secondary + ternary
        for row in (*secondary_starting, *ternary_starting):
            monthly_map[self._to_date(row["month"])]["bookings_starting"] += row["starting_count"]

        for row in payment_data:
            monthly_map[self._to_date(row["month"])]["amt_collected"] = row["amt_collected"] or ZERO

        for row in unmapped_payments:
            monthly_map[self._to_date(row["month"])].update({
                "unmapped_count": row["unmapped_count"],
                "unmapped_amount": row["unmapped_amount"],
            })

        return monthly_map

    # ── month-wise-performance ─────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="month-wise-performance")
    def month_wise_performance(self, request):
        try:
            year, month, year_type = self._parse_filters(request)
            monthly_data = self._fetch_monthly_data(year, month, year_type)
            rows = self._build_rows(monthly_data)
            response_data = {
                "year": year,
                "month": month,
                "year_type": year_type,
                "rows": rows,
                "summary": self._build_summary_monthly(rows),
            }
            return Response(MonthlyAnalyticsResponseSerializer(response_data).data)
        except ValidationError:
            raise
        except Exception as e:
            raise e(f"An unexpected error occurred: {e}")

    def _fetch_monthly_data(self, year, month, year_type="CY"):
        """Fetch all monthly data."""
        invoice_data = self._fetch_invoice_data(year, month, year_type)

        #  _fetch_order_bookings now returns (ending_qs, starting_qs)
        secondary_ending, secondary_starting = self._fetch_order_bookings(
            SecondaryOrder, year, month, year_type
        )
        ternary_ending, ternary_starting = self._fetch_order_bookings(
            TernaryOrder, year, month, year_type
        )

        payment_data = self._fetch_payment_data(year, month, year_type)
        unmapped_payments = self._fetch_unmapped_payments(year, month, year_type)

        return self._merge_monthly_data(
            invoice_data,
            secondary_ending, secondary_starting,   # 
            ternary_ending, ternary_starting,        # 
            payment_data,
            unmapped_payments,
        )

    def _fetch_payment_data(self, year, month, year_type="CY"):
        """
        Fetch payment data for year/month.
         Uses _base_payment_qs which now includes partially paid records.
        """
        return (
            self._base_payment_qs(year, month, year_type)
            .annotate(month=TruncMonth("paid_date"))
            .values("month")
            .annotate(amt_collected=Sum("amount", default=ZERO))
            .order_by("month")
        )

    def _build_row(self, month, data):
        """
        Build single month row.
         Exposes bookings_starting and bookings_ending separately.
         Exposes partially_paid_invoices.
        """
        invoice_value = data["invoice_value"]
        generated_invoices = data["generated_invoices"]
        amt_collected = data["amt_collected"]
        return {
            "month": month.strftime("%b'%Y") if month else "All Months",
            #  two booking columns instead of one
            "bookings_starting": data["bookings_starting"],
            "bookings_ending": data["bookings_ending"],
            "invoice_value": invoice_value,
            "amt_collected": amt_collected,
            "balance": str(invoice_value - amt_collected),
            "collection_pct": self._collection_pct(amt_collected, invoice_value),
            "unpaid_invoices": data["unpaid_invoices"],
            "paid_invoices": data["paid_invoices"],
            "partially_paid_invoices": data["partially_paid_invoices"],  # 
            "generated_invoices": str(generated_invoices),
            "unmapped_count": data["unmapped_count"],
            "unmapped_amount": data["unmapped_amount"],
        }

    def _build_rows(self, monthly_data):
        """Build response rows from monthly data."""
        return [
            self._build_row(month, monthly_data[month])
            for month in sorted(monthly_data.keys(), reverse=True)
        ]

    def _build_summary_monthly(self, rows):
        """
        Build summary from rows.
         Sums bookings_starting and bookings_ending separately.
         Adds total_partially_paid_invoices to summary.
        """
        if not rows:
            return {
                "total_bookings_starting": 0,    
                "total_bookings_ending": 0,   
                "total_invoice_value": 0.00,
                "total_amt_collected": 0.00,
                "total_balance": 0.00,
                "collection_pct": 0.00,
                "total_unpaid_invoices": 0,
                "total_paid_invoices": 0,
                "total_partially_paid_invoices": 0,  
                "total_unmapped_count": 0,
                "total_unmapped_amount": 0,
                "total_generated_invoices": 0,
            }

        total_invoice = sum(Decimal(r["invoice_value"]) for r in rows)
        total_collected = sum(Decimal(r["amt_collected"]) for r in rows)

        return {
            "total_bookings_starting": sum(int(r["bookings_starting"]) for r in rows),
            "total_bookings_ending": sum(int(r["bookings_ending"]) for r in rows),    
            "total_invoice_value": total_invoice,
            "total_amt_collected": total_collected,
            "total_balance": str(total_invoice - total_collected),
            "collection_pct": self._collection_pct(total_collected, total_invoice),
            "total_unpaid_invoices": sum(int(r["unpaid_invoices"]) for r in rows),
            "total_paid_invoices": sum(int(r["paid_invoices"]) for r in rows),
            "total_partially_paid_invoices": sum(int(r["partially_paid_invoices"]) for r in rows),
            "total_generated_invoices": sum(int(r["generated_invoices"]) for r in rows),
            "total_unmapped_count": sum(int(r["unmapped_count"]) for r in rows),
            "total_unmapped_amount": sum(int(r["unmapped_amount"]) for r in rows),
        }

    # ── daily-collection ───────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="daily-collection")
    def daily_collection(self, request):
        try:
            year, month, year_type = self._parse_daily_filters(request)
            return Response({
                "year": year,
                "month": month,
                "year_type": year_type,
                "daily_collection": self._fetch_daily_collection_map(year, month, year_type),
            })
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"An unexpected error occurred: {e}")

    def _fetch_daily_collection_map(self, year, month, year_type="CY"):
        """
        Returns attendance-style format:
        { "Mar-2025": { "01": "500.00", "15": "1200.00" } }
        Only days with actual collection are included.
        """
        rows = (
            self._base_payment_qs(year, month, year_type)
            .annotate(day=TruncDay("paid_date"))
            .values("day")
            .annotate(amt_collected=Sum("amount", default=ZERO))
            .order_by("day")
        )

        daily_payment = defaultdict(dict)
        for row in rows:
            day: date = row["day"]
            daily_payment[day.strftime("%b'%Y")][day.strftime("%d")] = str(row["amt_collected"])

        return dict(daily_payment)

    # ── payment-mode-analytics ─────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="payment-mode-analytics")
    def payment_mode_analytics(self, request):
        """
        Returns:
          - summary_cards : digital / cash / cheque totals + grand total
          - mode_split    : per-method amount + % of total
          - monthly_trend : month-wise breakdown by method + row total
        """
        try:
            year, month, year_type = self._parse_filters(request)
            return Response(self._fetch_payment_mode_data(year, month, year_type))
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"An unexpected error occurred: {e}")

    def _fetch_payment_mode_data(self, year, month, year_type="CY"):
        """Fetch payment mode analytics."""
        qs = self._base_payment_qs(year, month, year_type)

        method_totals = qs.values("method").annotate(total=Sum("amount", default=ZERO))
        method_map = {row["method"]: row["total"] for row in method_totals}
        grand_total = sum(method_map.values()) or ZERO

        def pct(amount):
            return round(float(amount / grand_total * 100), 1) if grand_total > 0 else 0.0

        mode_split = [
            {
                "method": method,
                "amount": str(method_map.get(method, ZERO)),
                "pct": pct(method_map.get(method, ZERO)),
            }
            for method in PaymentMethod.values
        ]

        def group_total(methods):
            return sum(method_map.get(m, ZERO) for m in methods)

        digital_total = group_total(self.DIGITAL_METHODS)
        cash_total = group_total(self.CASH_METHODS)
        cheque_total = group_total(self.CHEQUE_METHODS)

        summary_cards = {
            "digital_payments": {"amount": str(digital_total), "pct_of_total": pct(digital_total)},
            "cash_payments": {"amount": str(cash_total), "pct_of_total": pct(cash_total)},
            "cheque_payments": {"amount": str(cheque_total), "pct_of_total": pct(cheque_total)},
            "total_collected": {
                "amount": str(grand_total),
                "period": self._format_period(year, month, year_type),
            },
        }

        monthly_raw = (
            qs
            .annotate(month=TruncMonth("paid_date"))
            .values("month", "method")
            .annotate(total=Sum("amount", default=ZERO))
            .order_by("month", "method")
        )

        trend_map = defaultdict(lambda: defaultdict(Decimal))
        for row in monthly_raw:
            trend_map[row["month"]][row["method"]] += row["total"]

        monthly_trend = [
            {
                "month": month_dt.strftime("%b'%Y"),
                "methods": {m: str(trend_map[month_dt].get(m, ZERO)) for m in PaymentMethod.values},
                "total": str(sum(trend_map[month_dt].values())),
            }
            for month_dt in sorted(trend_map)
        ]

        return {
            "year": year,
            "month": month,
            "year_type": year_type,
            "summary_cards": summary_cards,
            "mode_split": mode_split,
            "monthly_trend": monthly_trend,
        }

    # ── Utility ────────────────────────────────────────────────────────────────

    @staticmethod
    def _collection_pct(collected, total):
        """Calculate collection percentage."""
        if total and total > 0:
            return round((collected / total) * 100, 1)
        return "0.00"

    def _format_period(self, year, month, year_type):
        """Format period string for display."""
        if year_type == "FY":
            if month:
                return f"{calendar.month_abbr[month]}, FY{year}"
            return f"FY{year}"
        else:
            if month:
                return f"{calendar.month_abbr[month]} {year}"
            return str(year)
         
class InvoiceListViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API for listing and retrieving invoices.
    Supports:
    - Search
    - Filtering
    - Ordering
    - Year/Month filtering (CY and FY)
    """

    queryset = TotalInvoice.objects.select_related(
        'secondary_order__primary_order__venue__location',
        "secondary_order__primary_order__venue",
        'secondary_order__primary_order__service',
        'secondary_order__primary_order__package',
        "secondary_order__primary_order",
        "secondary_order",
    )

    serializer_class = InvoiceListSerializer
    search_fields = [
        "invoice_number",
        "patient__first_name",
        "patient__last_name",
        "user__email",
        "user__first_name",
        "user__last_name",
    ]
    filterset_fields = {
        'patient': ['exact'],
        'secondary_order__primary_order__booking_type': ['exact'],
        'status': ['exact'],
    }
    ordering_fields = [
        "issued_date", "due_date", "period_start", "period_end",
        "total_amount", "paid_amount", "remaining_amount",
        "status", "created_at",
    ]
    ordering = ["-issued_date"]

    # ── Constants ──────────────────────────────────────────────────────────────

    FY_START_MONTH = 4

    # ── FY helpers ─────────────────────────────────────────────────────────────

    def _get_fy_range(self, fy_year):
        """
        FY2025 = Apr 2024 → Mar 2025
        Returns (start_year, start_month, end_year, end_month)
        """
        return (fy_year - 1, self.FY_START_MONTH, fy_year, self.FY_START_MONTH - 1)

    def _current_fy(self):
        today = date.today()
        return today.year if today.month < self.FY_START_MONTH else today.year + 1

    def _cy_to_fy(self, cy_year, cy_month):
        return cy_year + 1 if cy_month >= self.FY_START_MONTH else cy_year

    # ── Filter parsers ─────────────────────────────────────────────────────────

    def _parse_filters(self, request):
        """
        Parse year / month / year_type from query params.
        month=0 → all months.
        """
        year_param      = request.query_params.get("year")
        month_param     = request.query_params.get("month")
        year_type_param = request.query_params.get("year_type", "CY").upper()

        if year_type_param not in ("CY", "FY"):
            raise ValidationError("year_type must be 'CY' or 'FY'.")

        if not year_param:
            year = self._current_fy() if year_type_param == "FY" else date.today().year
        else:
            try:
                year = int(year_param)
            except ValueError:
                raise ValidationError("Year must be a valid integer.")

        if month_param:
            try:
                month = int(month_param)
            except ValueError:
                raise ValidationError("Month must be a valid integer between 1 and 12.")
            if not 1 <= month <= 12:
                raise ValidationError("Month must be between 1 and 12.")
        else:
            month = 0

        return year, month, year_type_param

    def get_queryset(self):
        queryset = super().get_queryset()
        year, month, year_type = self._parse_filters(self.request)

        if year_type == "FY":
            start_year, start_month, end_year, end_month = self._get_fy_range(year)
            if month == 0:
                # Full FY: Apr YYYY-1 → Mar YYYY
                queryset = queryset.filter(
                    period_end__gte=date(start_year, start_month, 1),
                    period_end__lte=date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
                )
            else:
                cy_year = start_year if month >= self.FY_START_MONTH else end_year
                queryset = queryset.filter(
                    period_end__year=cy_year,
                    period_end__month=month
                )
        else:
            # CY
            if month == 0:
                queryset = queryset.filter(period_end__year=year)
            else:
                queryset = queryset.filter(
                    period_end__year=year,
                    period_end__month=month
                )

        return queryset