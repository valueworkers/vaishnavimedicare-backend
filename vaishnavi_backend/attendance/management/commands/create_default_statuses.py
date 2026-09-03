from django.core.management.base import BaseCommand
from attendance.models import AttendanceStatus


class Command(BaseCommand):
    help = "Create default attendance statuses if not present"

    DEFAULT_STATUSES = [
        ('ABSENT','Absent'),
        ('PRESENT','Present'),
        ('HALF_DAY','Half day'),
        ('PAID_LEAVE','Paid leave'),
        ('UNPAID_LEAVE','Unpaid leave'),
    ]

    def handle(self, *args, **kwargs):
        created_count = 0

        for code, label in self.DEFAULT_STATUSES:
            obj, created = AttendanceStatus.objects.update_or_create(
                code=code,
                defaults={"label": label, "is_active": True},
            )
            if obj or created:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"✔ {created_count} default statuses created successfully.")
        )
