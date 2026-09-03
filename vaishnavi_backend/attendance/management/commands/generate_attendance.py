from django.core.management.base import BaseCommand
from django.db.models import Q
from datetime import date, timedelta
from attendance.models import Attendance, AttendanceStatus
from accounts.models import CustomUser


class Command(BaseCommand):
    help = "Mark attendance for all staff as Present from start_date to today"

    def handle(self, *args, **kwargs):
        # Get the "Present" status
        try:
            present_status = AttendanceStatus.objects.get(code='PRESENT')
        except AttendanceStatus.DoesNotExist:
            self.stdout.write(
                self.style.ERROR("AttendanceStatus with code 'PRESENT' not found.")
            )
            return

        start_date = date(year=2025,month=10,day=1)
        end_date = date.today() 
        
        # Get staff users as a list of IDs directly
        users_query= CustomUser.objects.all()
        users = users_query.filter(hierarchy__owner=2)
        user_ids = list(users.values_list('id', flat=True))
        if not user_ids:
            self.stdout.write(self.style.WARNING("No staff found for this owner."))
            return

        # Generate all date-user combinations
        date_range = [start_date + timedelta(days=n) 
                      for n in range((end_date - start_date).days + 1)]
        
        # Fetch ALL existing attendance records in one query
        existing_attendance = set(
            Attendance.objects.filter(
                user_id__in=user_ids,
                date__range=(start_date, end_date)
            ).values_list('user_id', 'date')
        )

        # Build attendance records excluding existing ones
        attendance_records = [
            Attendance(
                user_id=user_id,
                date=current_date,
                status=present_status,
                duration=None,
            )
            for user_id in user_ids
            for current_date in date_range
            if (user_id, current_date) not in existing_attendance
        ]
        # Log count and exit (remove these lines in production)
        self.stdout.write(
            self.style.SUCCESS(f"Ready to create {len(attendance_records)} records")
        )
        
        if attendance_records:
            Attendance.objects.bulk_create(
                attendance_records,
                batch_size=1000,
                ignore_conflicts=True  # Changed to True for safety
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created {len(attendance_records)} attendance records."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING("No new attendance records to create.")
            )