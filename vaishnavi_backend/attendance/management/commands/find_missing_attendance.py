# attendance/management/commands/find_missing_attendance.py


from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from attendance.models import Attendance, AttendanceStatus
from attendance.tasks import find_missing_attendance


class Command(BaseCommand):
    '''
    # report only, last 7 days
    python manage.py find_missing_attendance

    # report only, explicit range
    python manage.py find_missing_attendance --start 2026-09-01 --end 2026-09-10

    # actually create the missing records as Present
    python manage.py find_missing_attendance --start 2026-09-01 --end 2026-09-10 --backfill

    # check one person
    python manage.py find_missing_attendance --user 42 --days-back 14
    '''
    help = (
        "Report (and optionally backfill) missing Attendance records for "
        "staff/managers over a date range. Defaults to the last 7 days, "
        "excluding today."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start", type=str, default=None,
            help="Start date YYYY-MM-DD (default: 7 days before end).",
        )
        parser.add_argument(
            "--end", type=str, default=None,
            help="End date YYYY-MM-DD (default: yesterday, local date).",
        )
        parser.add_argument(
            "--days-back", type=int, default=7,
            help="Used only if --start is omitted. Default: 7.",
        )
        parser.add_argument(
            "--backfill", action="store_true",
            help="Create the missing records as Present. Without this flag, report only.",
        )
        parser.add_argument(
            "--user", type=int, default=None,
            help="Restrict to a single user id (for spot-checking one person).",
        )

    def handle(self, *args, **options):
        today = timezone.localdate()

        end_date = parse_date(options["end"]) if options["end"] else today - timedelta(days=1)
        if end_date is None:
            raise CommandError(f"Could not parse --end date: {options['end']!r}")
        if end_date >= today:
            self.stdout.write(self.style.WARNING(
                f"--end ({end_date}) is today or later; mark_attendance_present "
                f"owns today's records, so results for it may look 'missing' "
                f"before that task has run."
            ))

        if options["start"]:
            start_date = parse_date(options["start"])
            if start_date is None:
                raise CommandError(f"Could not parse --start date: {options['start']!r}")
        else:
            start_date = end_date - timedelta(days=options["days_back"] - 1)

        if start_date > end_date:
            raise CommandError(f"--start ({start_date}) is after --end ({end_date}).")

        missing = find_missing_attendance(start_date, end_date)

        if options["user"]:
            missing = [(uid, d) for uid, d in missing if uid == options["user"]]

        if not missing:
            self.stdout.write(self.style.SUCCESS(
                f"No gaps found for {start_date} → {end_date}."
            ))
            return

        by_user = {}
        for user_id, d in missing:
            by_user.setdefault(user_id, []).append(d)

        self.stdout.write(self.style.WARNING(
            f"{len(missing)} missing record(s) across {len(by_user)} user(s), "
            f"{start_date} → {end_date}:"
        ))
        for user_id, dates in sorted(by_user.items()):
            dates_str = ", ".join(d.isoformat() for d in sorted(dates))
            self.stdout.write(f"  user {user_id}: {dates_str}")

        if not options["backfill"]:
            self.stdout.write(self.style.NOTICE(
                "Dry run only — pass --backfill to create these as Present."
            ))
            return

        try:
            present_status = AttendanceStatus.objects.get(code="PRESENT")
        except AttendanceStatus.DoesNotExist:
            raise CommandError("AttendanceStatus with code 'PRESENT' not found.")

        records = [
            Attendance(user_id=user_id, date=d, status=present_status, duration=None)
            for user_id, d in missing
        ]
        created = Attendance.objects.bulk_create(records, batch_size=5000, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} attendance record(s)."))