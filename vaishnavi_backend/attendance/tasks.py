# attendance/tasks.py
import logging
from datetime import timedelta, date

from celery import shared_task
from django.utils import timezone

from attendance.models import Attendance, AttendanceStatus
from accounts.models import CustomUser

logger = logging.getLogger(__name__)

@shared_task
def mark_attendance_present():
    """
    Mark attendance for all staff as Present for today.
    This task is scheduled to run daily via Celery Beat.
    """
    try:
        # Get the "Present" status with code "PRESENT"
        present_status = AttendanceStatus.objects.get(code='PRESENT')
    except AttendanceStatus.DoesNotExist:
        return {
            'status': 'error',
            'message': "AttendanceStatus with code 'PRESENT' not found."
        }
        

    current_date = date.today()
    
    try:
        managers = CustomUser.objects.managers().values_list('id', flat=True)
        staff = CustomUser.objects.staff().values_list('id', flat=True)

        users_list = list(managers) + list(staff)

    except Exception as e:
        return {
            'status': 'error',
            'message': f"Error fetching users: {str(e)}"
        }


    if not users_list:
        return {
            'status': 'warning',
            'message': "No staff found for this owner."
        }
        

    # Get existing attendance records to avoid duplicates
    existing = set(
        Attendance.objects.filter(
            user_id__in=users_list,
            date=current_date
        ).values_list('user_id', 'date')
    )

    # Prepare bulk create data with "Present" status
    attendance_records = []
    for user_id in users_list:
        if (user_id, current_date) not in existing:
            attendance_records.append(
                Attendance(
                    user_id=user_id,
                    date=current_date,
                    status=present_status,
                    duration=None,
                )
            )

    # Bulk create all at once
    if attendance_records:
        created = Attendance.objects.bulk_create(
            attendance_records,
            batch_size=5000,
            ignore_conflicts=False
        )
        return {
            'status': 'success',
            'message': f"Created {len(created)} attendance records marked as Present."
        }
        
    else:
        return {
            'status': 'warning',
            'message': "No new attendance records to create."
        }

 # attendance/tasks.py (additions)

def _active_staff_ids():
    managers = CustomUser.objects.managers().values_list('id', flat=True)
    staff = CustomUser.objects.staff().values_list('id', flat=True)
    return list(managers) + list(staff)

def find_missing_attendance(start_date, end_date):
    """
    Read-only audit. Returns [(user_id, date), ...] for every staff/manager
    user with no Attendance record on a given date in [start_date, end_date].
    Use this to see the size of a gap before deciding whether to backfill it.
    """
    user_ids = _active_staff_ids()
    if not user_ids:
        return []

    total_days = (end_date - start_date).days + 1
    all_dates = [start_date + timedelta(days=i) for i in range(total_days)]

    existing = set(
        Attendance.objects.filter(
            user_id__in=user_ids,
            date__range=(start_date, end_date),
        ).values_list('user_id', 'date')
    )

    return [
        (user_id, d)
        for user_id in user_ids
        for d in all_dates
        if (user_id, d) not in existing
    ]

@shared_task
def backfill_missing_attendance(days_back=7):
    """
    Finds gaps in the last `days_back` days (never touches today — that's
    mark_attendance_present's job) and fills each with Present, same
    default the daily task applies. Meant as an occasional safety-net run
    (manual, or a low-frequency beat entry), not the primary marking path.
    """
    try:
        present_status = AttendanceStatus.objects.get(code='PRESENT')
    except AttendanceStatus.DoesNotExist:
        logger.error("backfill_missing_attendance: AttendanceStatus 'PRESENT' not found")
        return {'status': 'error', 'message': "AttendanceStatus 'PRESENT' not found."}

    today = timezone.localdate()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=days_back - 1)

    missing = find_missing_attendance(start_date, end_date)
    if not missing:
        logger.info("backfill_missing_attendance: no gaps (%s to %s)", start_date, end_date)
        return {'status': 'success', 'created': 0}

    records = [
        Attendance(user_id=user_id, date=d, status=present_status, duration=None)
        for user_id, d in missing
    ]
    created = Attendance.objects.bulk_create(records, batch_size=5000, ignore_conflicts=True)

    logger.info("backfill_missing_attendance: created %d (%s to %s)", len(created), start_date, end_date)
    return {'status': 'success', 'created': len(created)}       

    