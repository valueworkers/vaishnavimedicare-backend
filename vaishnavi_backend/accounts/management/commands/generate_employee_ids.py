from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import CustomUser, EmployeeProfile


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

        users = list(CustomUser.objects.employees().order_by("id"))

        for user in users:

            # get_or_create() only works one row at a time (it can't take
            # a bulk __in filter) — so it's called per-user here, creating
            # an EmployeeProfile for any employee who doesn't have one yet.
            profile, created = EmployeeProfile.objects.get_or_create(user=user)

            if len(profile.employee_id)>2:
                # Already has an ID — nothing to do.
                skipped_count += 1
                continue

            # Skip invalid user types
            prefix = prefix_map.get(user.user_type)

            if not prefix:
                skipped_count += 1
                continue

            # Generate employee ID
            employee_id = f"{prefix}{year}{user.id:04d}"

            # Protect against overwriting existing IDs (single UPDATE,
            # no need to wrap this in transaction.atomic() since it's
            # already one atomic statement).
            updated = (
                EmployeeProfile.objects
                .filter(
                    pk=profile.pk,
                )
                .update(employee_id=employee_id)
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