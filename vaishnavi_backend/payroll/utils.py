# utils.py
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from django.db.models import Sum
from collections import defaultdict
from payroll.models import SalaryStructure, SalaryReport, SalaryTransaction
from attendance.utils import AttendanceCalculator


class SalaryCalculator:
    """
    Sign convention (kept consistent with SalaryTransactionViewSet.create):
      - remaining_payment: amount still owed TO the employee (>= 0)
      - advance_amount:    amount the employee was overpaid / carried
                            forward as an advance (>= 0)
    A period can have exactly one of the two be nonzero at a time.
    """

    DAYS_MAP = {
        "HOURLY": Decimal("8"),
        "DAILY": Decimal("1"),
        "WEEKLY": Decimal("7"),
        "FORTNIGHTLY": Decimal("14"),
        "MONTHLY": Decimal("30"),
    }

    def __init__(self, user):
        self.user = user

    # --------------------------------------------------

    def get_salary_snapshot(self, check_date: date):
        return SalaryStructure.objects.filter(
            user=self.user,
            effective_from__lte=check_date,
            change_type__in=["BASE_SALARY", "INCREMENT"]
        ).order_by("-effective_from").first()

    # --------------------------------------------------

    def get_daily_rate(self, salary_obj: SalaryStructure) -> Decimal:
        if not salary_obj:
            return Decimal("0")

        divisor = self.DAYS_MAP.get(salary_obj.salary_type, Decimal("30"))
        return salary_obj.final_salary / divisor

    def calculate_amount(self, daily_rate: Decimal, payable_days) -> Decimal:
        payable_days = Decimal(payable_days or 0)
        return (daily_rate * payable_days).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    # --------------------------------------------------

    def _get_paid_amount_map(self):
        """
        One query: total SUCCESS amount paid per (start_date, end_date) period.
        """
        paid_amount_map = defaultdict(Decimal)
        paid_qs = (
            SalaryTransaction.objects
            .filter(
                salary_report__user=self.user,
                status="SUCCESS",
            )
            .values(
                "salary_report__start_date",
                "salary_report__end_date",
            )
            .annotate(total=Sum("amount_paid"))
        )

        for row in paid_qs:
            paid_amount_map[
                (row["salary_report__start_date"], row["salary_report__end_date"])
            ] = row["total"] or Decimal("0.00")

        return paid_amount_map

    def _build_rows(self, attendance_reports):
        """
        Shared computation used by both get_salary_reports_computed()
        and refresh_salary_reports(). Returns a list of plain dicts.
        """
        if not attendance_reports:
            return []

        paid_amount_map = self._get_paid_amount_map()

        rows = []
        salary_cache = {}
        carry_forward = Decimal("0.00")  # advance carried from the previous period

        attendance_reports = sorted(attendance_reports, key=lambda x: x['start_date'])

        for attendance in attendance_reports:
            att_start = attendance['start_date']
            att_end = attendance['end_date']

            if att_end not in salary_cache:
                salary_cache[att_end] = self.get_salary_snapshot(att_end)

            salary_obj = salary_cache[att_end]

            daily_rate = self.get_daily_rate(salary_obj)
            payable_days = Decimal(attendance.get('total_payable_days', 0))

            total_days = Decimal((att_end - att_start).days + 1)

            # Full month shortcut
            if (
                salary_obj
                and salary_obj.salary_type == "MONTHLY"
                and (payable_days > 30 or payable_days == total_days)
            ):
                total_amount = salary_obj.final_salary
            else:
                total_amount = self.calculate_amount(daily_rate, payable_days)

            paid_amount = paid_amount_map.get(
                (att_start, att_end),
                Decimal("0.00"),
            )

            # Net what's owed this period, after applying any advance
            # carried in from the previous period.
            net = (total_amount - paid_amount) - carry_forward

            if net < 0:
                # Employee has been overpaid overall — no amount owed,
                # and the excess becomes the new advance carried forward.
                remaining_payment = Decimal("0.00")
                carry_forward = -net
            else:
                remaining_payment = net
                carry_forward = Decimal("0.00")

            advance_total = carry_forward

            rows.append({
                'user': self.user,
                'start_date': att_start,
                'end_date': att_end,
                'daily_rate': daily_rate.quantize(Decimal("0.01")),
                'total_payable_amount': total_amount,
                'advance_amount': advance_total,
                'paid_amount': paid_amount,
                'remaining_payment': remaining_payment,
                'final_salary': salary_obj.final_salary if salary_obj else Decimal("0"),
            })

        return rows

    # --------------------------------------------------
    def get_salary_reports_computed(self, start_date=None, end_date=None):
        """
        Compute salary reports on-the-fly from attendance data.
        Returns list of dicts without saving to database.
        """
        attendance_calc = AttendanceCalculator(self.user)
        attendance_reports = attendance_calc.get_all_periods_computed(
            start_date=start_date,
            end_date=end_date,
            period_type="MONTHLY"
        )
        return self._build_rows(attendance_reports)

    # --------------------------------------------------
    def refresh_salary_reports(self):
        """
        Calculate and save salary reports to database.
        Used by signals when salary structure changes.
        """
        attendance_calc = AttendanceCalculator(self.user)
        attendance_reports = attendance_calc.get_all_periods_computed(
            period_type="MONTHLY"
        )

        rows = self._build_rows(attendance_reports)
        if not rows:
            return

        salary_reports = [
            SalaryReport(
                user=row['user'],
                start_date=row['start_date'],
                end_date=row['end_date'],
                daily_rate=row['daily_rate'],
                total_payable_amount=row['total_payable_amount'],
                advance_amount=row['advance_amount'],
                paid_amount=row['paid_amount'],
                remaining_payment=row['remaining_payment'],
                final_salary=row['final_salary'],
            )
            for row in rows
        ]

        SalaryReport.objects.bulk_create(
            salary_reports,
            update_conflicts=True,
            unique_fields=["user", "start_date", "end_date"],
            update_fields=[
                "daily_rate",
                "total_payable_amount",
                "paid_amount",
                "advance_amount",
                "remaining_payment",
                "final_salary",
            ],
        )