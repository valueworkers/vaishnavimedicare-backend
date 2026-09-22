"""
management/commands/refresh_salary_reports.py

Usage:
    python manage.py refresh_salary_reports --user-id 5
    python manage.py refresh_salary_reports --all
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from ...tasks import queue_salary_report_refresh

CustomUser = get_user_model()


class Command(BaseCommand):
    help = "Queue a SalaryReport refresh task for one user or every employee."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, help="Refresh a single user by id")
        parser.add_argument("--all", action="store_true", help="Refresh every employee")

    def handle(self, *args, **options):
        if options["all"]:
            user_ids = CustomUser.objects.filter(
                user_type__in=["VSRE_MANAGER", "LINE_MANAGER", "VSRE_STAFF"]
            ).values_list("id", flat=True)
            for user_id in user_ids:
                queue_salary_report_refresh(user_id, countdown=0)
            self.stdout.write(self.style.SUCCESS(f"Queued refresh for {len(user_ids)} users."))
        elif options["user_id"]:
            queue_salary_report_refresh(options["user_id"], countdown=0)
            self.stdout.write(self.style.SUCCESS(f"Queued refresh for user {options['user_id']}."))
        else:
            self.stderr.write("Pass --user-id <id> or --all")