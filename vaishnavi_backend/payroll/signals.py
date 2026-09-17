from decimal import Decimal

from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import SalaryStructure
from .utils import SalaryCalculator


def calculate_gross_salary(
    change_type,
    amount,
    previous_gross_salary,
):
    if change_type == "BASE_SALARY":
        return amount

    if change_type == "INCREMENT":
        return previous_gross_salary + amount

    # ADVANCE / LOAN do not affect gross salary
    return previous_gross_salary


def rebuild_salary_chain(user):

    records = (
        SalaryStructure.objects
        .filter(user=user)
        .order_by("effective_from", "pk")
    )

    current_gross_salary = Decimal("0.00")

    # Carry forward the latest PF and ESI values
    current_pf_amount = Decimal("0.00")
    current_esi_amount = Decimal("0.00")

    updates = []

    for record in records:

        # Calculate current gross salary
        current_gross_salary = calculate_gross_salary(
            record.change_type,
            record.amount,
            current_gross_salary,
        )

        # ====================================================
        # PF AMOUNT
        # ====================================================
        if record.change_type == "BASE_SALARY":
            # A new base salary starts its own PF baseline —
            # do NOT carry forward from an earlier, unrelated record.
            current_pf_amount = record.pf_amount or Decimal("0.00")
            record.pf_amount = current_pf_amount
        elif record.pf_amount and record.pf_amount > 0:
            current_pf_amount = record.pf_amount
        else:
            # INCREMENT / ADVANCE / LOAN: carry forward if not provided
            record.pf_amount = current_pf_amount

        # ====================================================
        # ESI AMOUNT
        # ====================================================
        if record.change_type == "BASE_SALARY":
            current_esi_amount = record.esi_amount or Decimal("0.00")
            record.esi_amount = current_esi_amount
        elif record.esi_amount and record.esi_amount > 0:
            current_esi_amount = record.esi_amount
        else:
            # INCREMENT / ADVANCE / LOAN: carry forward if not provided
            record.esi_amount = current_esi_amount

        # ====================================================
        # FINAL SALARY
        # ====================================================

        record.final_salary = (
            current_gross_salary
            - current_pf_amount
            - current_esi_amount
        )

        updates.append(record)

    if updates:

        SalaryStructure.objects.bulk_update(
            updates,
            [
                "pf_amount",
                "esi_amount",
                "final_salary",
            ],
        )

def handle_salary_structure_change(instance):
    """
    Rebuild salary chain immediately.

    Refresh salary reports after transaction commits.
    """

    user = instance.user

    rebuild_salary_chain(user)

    transaction.on_commit(
        lambda: SalaryCalculator(user).refresh_salary_reports()
    )


@receiver(post_save, sender=SalaryStructure)
def on_salary_structure_save(sender, instance, **kwargs):
    handle_salary_structure_change(instance)


@receiver(post_delete, sender=SalaryStructure)
def on_salary_structure_delete(sender, instance, **kwargs):
    handle_salary_structure_change(instance)