
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import EmployeeProfile


class Command(BaseCommand):
    help = "Generate employee IDs for existing EmployeeProfiles"

    def handle(self, *args, **options):

        prefix_map = {
            "VSRE_MANAGER": "M",
            "LINE_MANAGER": "LM",
            "VSRE_STAFF": "S",
        }

        year = timezone.now().year

        generated_count = 0
        skipped_count = 0

        profiles = (
            EmployeeProfile.objects
            .select_related("user")
            .filter(Q(employee_id__isnull=True) | Q(employee_id=""))
            .order_by("user_id")
        )

        for profile in profiles:

            user = profile.user

            # Skip invalid user types
            prefix = prefix_map.get(user.user_type)

            if not prefix:
                skipped_count += 1
                continue

            # Generate employee ID
            employee_id = f"{prefix}{year}{user.id:04d}"

            with transaction.atomic():

                # Protect against overwriting existing IDs
               updated = (
                    EmployeeProfile.objects
                    .filter(
                        Q(employee_id__isnull=True) | Q(employee_id=""),
                        pk=profile.pk,
                    )
                    .update(
                        employee_id=employee_id
                    )
                )

            if updated:
                generated_count += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Generated: {employee_id} "
                        f"for {user.get_full_name()} "
                        f"(User ID: {user.id})"
                    )
                )
            else:
                skipped_count += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Employee IDs generated: {generated_count}"
            )
        )

        self.stdout.write(
            self.style.WARNING(
                f"Profiles skipped: {skipped_count}"
            )
        )