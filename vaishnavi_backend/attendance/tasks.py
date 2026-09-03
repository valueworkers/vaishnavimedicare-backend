# attendance/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import date
from attendance.models import Attendance, AttendanceStatus
from accounts.models import CustomUser


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
        