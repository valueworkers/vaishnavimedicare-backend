"""The single source of truth for attendance and salary calculations."""

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Sum

from .models import Attendance, SalaryReport, SalaryStructure, SalaryTransaction


ZERO = Decimal("0.00")
HALF_DAY = Decimal("0.50")
HOURS_PER_DAY = Decimal("8")


class PayrollCalculator:
    """Build attendance and salary ledgers from the same pay-period inputs."""

    PERIOD_TYPES = {"HOURLY", "DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY"}
    DAILY_DIVISORS = {
        "HOURLY": HOURS_PER_DAY,
        "DAILY": Decimal("1"),
        "WEEKLY": Decimal("7"),
        "FORTNIGHTLY": Decimal("14"),
        "MONTHLY": Decimal("30"),
    }
    PAYABLE_STATUS_WEIGHTS = {
        "P": Decimal("1"),
        "PRESENT": Decimal("1"),
        "PL": Decimal("1"),
        "PAID_LEAVE": Decimal("1"),
        "H": HALF_DAY,
        "HALF_DAY": HALF_DAY,
    }
    STATUS_FIELDS = {
        "P": "present_days",
        "PRESENT": "present_days",
        "A": "absent_days",
        "ABSENT": "absent_days",
        "H": "half_day_count",
        "HALF_DAY": "half_day_count",
        "PL": "paid_leave_days",
        "PAID_LEAVE": "paid_leave_days",
        "WO": "weekly_offs",
        "WEEKLY_OFF": "weekly_offs",
        "UL": "unpaid_leaves",
        "UNPAID_LEAVE": "unpaid_leaves",
    }

    # Maps the keys attendance_report() returns to the SalaryReport model's
    # field names, wherever they differ (half_day_count -> half_days,
    # unpaid_leaves -> unpaid_leave_days, total_payable_days -> payable_days).
    # weekly_offs and total_payable_hours have no matching model field and
    # are intentionally left out of the report snapshot.
    ATTENDANCE_TO_REPORT_FIELDS = {
        "present_days": "present_days",
        "absent_days": "absent_days",
        "half_day_count": "half_days",
        "paid_leave_days": "paid_leave_days",
        "unpaid_leaves": "unpaid_leave_days",
        "total_payable_days": "payable_days",
    }

    def __init__(self, user):
        self.user = user

    @classmethod
    def period_for(cls, base_date, period_type):
        """Return the calendar-aligned pay period containing ``base_date``."""
        if period_type not in cls.PERIOD_TYPES:
            raise ValueError("Unsupported period type")
        if period_type in {"HOURLY", "DAILY"}:
            return base_date, base_date
        if period_type == "WEEKLY":
            start = base_date - timedelta(days=base_date.weekday())
            return start, start + timedelta(days=6)
        if period_type == "FORTNIGHTLY":
            if base_date.day <= 15:
                return base_date.replace(day=1), base_date.replace(day=15)
            return base_date.replace(day=16), base_date.replace(
                day=calendar.monthrange(base_date.year, base_date.month)[1]
            )
        return base_date.replace(day=1), base_date.replace(
            day=calendar.monthrange(base_date.year, base_date.month)[1]
        )

    def _periods(self, start_date=None, end_date=None, period_type="MONTHLY"):
        first_date = Attendance.objects.filter(user=self.user).order_by("date").values_list("date", flat=True).first()
        if not first_date:
            return []
        final_date = end_date or date.today()
        if start_date and start_date > final_date:
            raise ValueError("start_date cannot be after end_date")
        current = self.period_for(first_date, period_type)[0]
        periods = []
        while current <= final_date:
            period_start, period_end = self.period_for(current, period_type)
            periods.append((period_start, period_end))
            current = period_end + timedelta(days=1)
        return periods

    @staticmethod
    def _status_code(attendance):
        return attendance.status.code.strip().upper().replace(" ", "_")

    def _attendance_totals(self, records, start_date, end_date, period_type):
        totals = {
            "present_days": 0,
            "absent_days": 0,
            "half_day_count": 0,
            "paid_leave_days": 0,
            "weekly_offs": 0,
            "unpaid_leaves": 0,
            "total_payable_days": ZERO,
            "total_payable_hours": ZERO,
        }
        for record in records:
            code = self._status_code(record)
            field = self.STATUS_FIELDS.get(code)
            if field:
                totals[field] += 1
            weight = self.PAYABLE_STATUS_WEIGHTS.get(code, ZERO)
            totals["total_payable_days"] += weight
            if weight:
                seconds = Decimal(record.duration.total_seconds()) if record.duration else weight * HOURS_PER_DAY * Decimal(3600)
                totals["total_payable_hours"] += seconds / Decimal(3600)
        return {
            "start_date": start_date,
            "end_date": end_date,
            "period_type": period_type,
            **totals,
        }

    def attendance_report(self, start_date, end_date, period_type="MONTHLY", records=None):
        records = records if records is not None else list(
            Attendance.objects.select_related("status").filter(
                user=self.user, date__range=(start_date, end_date)
            )
        )
        return self._attendance_totals(records, start_date, end_date, period_type)

    def _salary_structures(self, final_date):
        return list(
            SalaryStructure.objects.filter(user=self.user, effective_from__lte=final_date)
            .order_by("effective_from", "pk")
        )

    @staticmethod
    def _structure_for(day, structures):
        applicable = [structure for structure in structures if structure.effective_from <= day]
        return applicable[-1] if applicable else None

    def _paid_amounts(self):
        amounts = defaultdict(lambda: ZERO)
        for row in (
            SalaryTransaction.objects.filter(salary_report__user=self.user, status="SUCCESS")
            .values("salary_report__start_date", "salary_report__end_date")
            .annotate(total=Sum("amount_paid"))
        ):
            amounts[(row["salary_report__start_date"], row["salary_report__end_date"])] = row["total"] or ZERO
        return amounts

    @classmethod
    def _daily_rate(cls, structure):
        if not structure:
            return ZERO
        return (structure.final_salary / cls.DAILY_DIVISORS[structure.salary_type]).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    def _period_salary(self, records, structures, period_end):
        amount = ZERO
        for record in records:
            weight = self.PAYABLE_STATUS_WEIGHTS.get(self._status_code(record), ZERO)
            if not weight:
                continue
            structure = self._structure_for(record.date, structures)
            if not structure:
                continue
            daily_rate = self._daily_rate(structure)
            if structure.salary_type == "HOURLY":
                hours = Decimal(record.duration.total_seconds()) / Decimal(3600) if record.duration else weight * HOURS_PER_DAY
                amount += daily_rate * (hours / HOURS_PER_DAY)
            else:
                amount += daily_rate * weight
        ending_structure = self._structure_for(period_end, structures)
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), self._daily_rate(ending_structure), ending_structure

    def reports(self, start_date=None, end_date=None, period_type="MONTHLY"):
        """Return a chronological ledger; balances always include prior periods."""
        if period_type not in self.PERIOD_TYPES:
            raise ValueError("Unsupported period type")
        periods = self._periods(start_date, end_date, period_type)
        if not periods:
            return []
        calculation_end = end_date or date.today()
        records = list(
            Attendance.objects.select_related("status").filter(
                user=self.user, date__range=(periods[0][0], calculation_end)
            ).order_by("date")
        )
        structures = self._salary_structures(calculation_end)
        paid_amounts = self._paid_amounts()
        carry_forward = ZERO
        ledger = []
        for period_start, period_end in periods:
            calculated_through = min(period_end, calculation_end)
            period_records = [r for r in records if period_start <= r.date <= calculated_through]
            attendance = self.attendance_report(period_start, period_end, period_type, period_records)
            attendance["calculated_through"] = calculated_through
            payable_amount, daily_rate, structure = self._period_salary(period_records, structures, calculated_through)
            paid_amount = paid_amounts[(period_start, period_end)]
            balance = payable_amount - paid_amount - carry_forward
            remaining_payment = max(balance, ZERO)
            carry_forward = max(-balance, ZERO)
            ledger.append({
                "user": self.user,
                "start_date": period_start,
                "end_date": period_end,
                "attendance": attendance,
                "salary": {
                    "daily_rate": daily_rate,
                    "final_salary": structure.final_salary if structure else ZERO,
                    "total_payable_amount": payable_amount,
                    "paid_amount": paid_amount,
                    "remaining_payment": remaining_payment,
                    "advance_amount": carry_forward,
                },
            })
        if start_date:
            ledger = [row for row in ledger if row["end_date"] >= start_date]
        return ledger

    def refresh_salary_reports(self):
        rows = self.reports(period_type="MONTHLY")
        if not rows:
            return

        # Don't overwrite a period that's already been closed out.
        finalized_periods = set(
            SalaryReport.objects.filter(
                user=self.user,
                start_date__in=[row["start_date"] for row in rows],
                is_finalized=True,
            ).values_list("start_date", "end_date")
        )
        rows = [row for row in rows if (row["start_date"], row["end_date"]) not in finalized_periods]
        if not rows:
            return
        
        def attendance_fields(row):
            return {
                model_field: row["attendance"][source_field]
                for source_field, model_field in self.ATTENDANCE_TO_REPORT_FIELDS.items()
            }

        SalaryReport.objects.bulk_create(
            [
                SalaryReport(
                    user=row["user"], start_date=row["start_date"], end_date=row["end_date"],
                    **attendance_fields(row),
                    **row["salary"],
                )
                for row in rows
            ],
            update_conflicts=True,
            unique_fields=["user", "start_date", "end_date"],
            update_fields=[
                "present_days", "absent_days", "half_days", "paid_leave_days",
                "unpaid_leave_days", "payable_days",
                "daily_rate", "total_payable_amount", "paid_amount",
                "advance_amount", "remaining_payment", "final_salary",
            ],
        )