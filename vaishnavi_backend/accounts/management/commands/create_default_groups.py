from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# ----------------------------------------------------------
# GROUP PERMISSION RULES
# ----------------------------------------------------------
GROUP_RULES = {
    # Master Admin gets every permission
    "MASTER_ADMIN": "__all__",

    # VSRE_OWNER gets full access to accounts & venue_manager apps
    "VSRE_OWNER": {
        "apps": ["accounts", "venue_manager"],
        "actions": "__all__",
    },

    # VSRE_MANAGER can view/change accounts & venue_manager
    "VSRE_MANAGER": {
        "apps": ["accounts", "venue_manager"],
        "actions": ["view", "change"],
    },

    # VSRE_STAFF can only view venue_manager
    "VSRE_STAFF": {
        "apps": ["venue_manager"],
        "actions": ["view"],
    },

    # LINE_MANAGER can view venue_manager
    "LINE_MANAGER": {
        "apps": ["venue_manager"],
        "actions": ["view"],
    },

    # CUSTOMER can view & add booking
    "CUSTOMER": {
        "apps": ["booking"],
        "actions": ["view", "add"],
    },
}


class Command(BaseCommand):
    help = "Create default groups and assign permissions automatically"

    def handle(self, *args, **options):
        for group_name, rule in GROUP_RULES.items():
            group, created = Group.objects.get_or_create(name=group_name)

            if rule == "__all__":
                # Give all permissions to MASTER_ADMIN
                all_perms = Permission.objects.all()
                group.permissions.set(all_perms)
                self.stdout.write(self.style.SUCCESS(f"✅ Group '{group_name}' configured (ALL PERMISSIONS)"))
                continue

            group.permissions.clear()

            # Collect permissions based on apps and actions
            apps = rule.get("apps", [])
            actions = rule.get("actions", [])

            for app_label in apps:
                content_types = ContentType.objects.filter(app_label=app_label)
                if not content_types.exists():
                    self.stdout.write(self.style.WARNING(f"⚠️ No content types found for app '{app_label}'"))
                    continue

                # Filter permissions for this app
                if actions == "__all__":
                    perms = Permission.objects.filter(content_type__in=content_types)
                else:
                    perms = Permission.objects.filter(
                        content_type__in=content_types,
                        codename__regex=f"^({'|'.join(actions)})_"
                    )

                if perms.exists():
                    group.permissions.add(*perms)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✅ Group '{group_name}' assigned {perms.count()} permissions from '{app_label}'"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f"⚠️ No permissions found for app '{app_label}'")
                    )

            self.stdout.write(self.style.SUCCESS(f"✅ Group '{group_name}' configured successfully\n"))
