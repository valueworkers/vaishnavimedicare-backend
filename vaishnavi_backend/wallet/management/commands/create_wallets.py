# wallet/management/commands/create_wallets.py

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import CustomUser
from wallet.models import Wallet


class Command(BaseCommand):
    help = "Create wallets for all customers who don't have one"

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-type',
            type=str,
            default='CUSTOMER',
            help='User type to create wallets for'
        )

    @transaction.atomic
    def handle(self, *args, **options):
        user_type = options['user_type']

        users = CustomUser.objects.filter(
            user_type=user_type
        ).exclude(
            wallet__isnull=False
        )

        created_count = 0

        for user in users:
            Wallet.objects.create(user=user)
            created_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Wallet created for: {user.get_full_name()}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSuccessfully created {created_count} wallets."
            )
        )