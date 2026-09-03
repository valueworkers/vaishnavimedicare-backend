# attendance/management/commands/check_missed_attendance.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import CustomUser
from attendance.models import Attendance
from notification.services import create_missed_attendance_notification


class Command(BaseCommand):
    help = "Check and notify missed attendance"

    def handle(self, *args, **kwargs):
        today = timezone.localdate()

        users = [CustomUser.objects.staff(), CustomUser.objects.manager()]

        for user in users:
            exists = Attendance.objects.filter(user=user, date=today).exists()

            if not exists:
                create_missed_attendance_notification(user, today)

        self.stdout.write(self.style.SUCCESS("Missed attendance check completed"))