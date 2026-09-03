import random
from decimal import Decimal
from django.core.management.base import BaseCommand
from accounts.models import CustomUser
from payroll.models import SalaryStructure


class Command(BaseCommand):
    help = "Create random SalaryStructure for all existing users without one"

    def handle(self, *args, **kwargs):

        users = CustomUser.objects.get_staff_under_owner(owner=2)

        SALARY_TYPES = ["HOURLY", "DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY"]

        created_count = 0
        list_Data  = []
        for user in users:

            salary_type = random.choice(SALARY_TYPES)

            # Random base_salary based on salary type
            if salary_type == "HOURLY":
                base_salary = Decimal(random.randint(100, 1000))
            elif salary_type == "DAILY":
                base_salary = Decimal(random.randint(500, 5000))
            elif salary_type == "WEEKLY":
                base_salary = Decimal(random.randint(2000, 15000))
            elif salary_type == "FORTNIGHTLY":
                base_salary = Decimal(random.randint(4000, 30000))
            else:  # MONTHLY
                base_salary = Decimal(random.randint(10000, 100000))

            advance = Decimal(random.randint(0, 5000))
            data = {
                "user":user,
                "salary_type":salary_type,
                "base_salary":base_salary,
                "advance_amount":advance,
                "is_increment":False
            }
            list_Data.append(SalaryStructure(
                    user=user,
                    salary_type=salary_type,
                    base_salary=base_salary,
                    advance_amount=advance,
                    is_increment=False,
                ))
            created_count += 1
        SalaryStructure.objects.bulk_create(list_Data)

        self.stdout.write(
            self.style.SUCCESS(f"Successfully created {created_count} SalaryStructure records.")
        )
