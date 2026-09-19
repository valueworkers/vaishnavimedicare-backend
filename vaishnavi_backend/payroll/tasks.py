import logging
from datetime import date

from celery import shared_task

from accounts.models import CustomUser
from .models import Attendance, AttendanceStatus
from .utils import PayrollCalculator

logger = logging.getLogger(__name__)


@shared_task
def mark_attendance_present():
    """Create today's missing attendance records and refresh affected payroll."""
    present_status = AttendanceStatus.objects.filter(code="PRESENT", is_active=True).first()
    if not present_status:
        return {"status": "error", "message": "Active PRESENT attendance status was not found."}

    today = date.today()
    user_ids = CustomUser.objects.employees().values_list("id", flat=True)
    existing_ids = set(Attendance.objects.filter(user_id__in=user_ids, date=today).values_list("user_id", flat=True))
    new_records = [Attendance(user_id=user_id, date=today, status=present_status) for user_id in user_ids if user_id not in existing_ids]
    Attendance.objects.bulk_create(new_records, batch_size=5000)
    for user in CustomUser.objects.filter(id__in=[record.user_id for record in new_records]):
        PayrollCalculator(user).refresh_salary_reports()
    return {"status": "success", "message": f"Created {len(new_records)} attendance record(s)."}
