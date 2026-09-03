from decimal import Decimal
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import SalaryStructure
from .utils import SalaryCalculator

# SalaryStructure chain recalculation
def calculate_final_salary(change_type, amount, previous_salary):
    if change_type == "BASE_SALARY":
        return amount

    if change_type == "INCREMENT":
        return previous_salary + amount

    # ADVANCE / LOAN do not affect base salary
    return previous_salary

def rebuild_salary_chain(user):
    """
    Rebuild ALL final_salary values for a user in chronological order.
    Deterministic + safe.
    """

    records = (
        SalaryStructure.objects
        .filter(user=user)
        .order_by("effective_from")
    )

    current_salary = Decimal("0")
    updates = []

    for record in records:
        current_salary = calculate_final_salary(
            record.change_type,
            record.amount,
            current_salary,
        )
        record.final_salary = current_salary
        updates.append(record)

    if updates:
        SalaryStructure.objects.bulk_update(updates, ["final_salary"])

# Unified handler
def handle_salary_structure_change(instance):
    """
    Rebuild salary chain immediately.
    Refresh SalaryReports AFTER transaction commits.
    """

    user = instance.user
    effective_from = instance.effective_from

    rebuild_salary_chain(user)

    # IMPORTANT: refresh salary reports only after commit
    transaction.on_commit(
        lambda: SalaryCalculator(user).refresh_salary_reports()
    )

# Signals
@receiver(post_save, sender=SalaryStructure)
def on_salary_structure_save(sender, instance, **kwargs):
    handle_salary_structure_change(instance)

@receiver(post_delete, sender=SalaryStructure)
def on_salary_structure_delete(sender, instance, **kwargs):
    handle_salary_structure_change(instance)
