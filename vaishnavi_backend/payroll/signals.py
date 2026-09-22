from decimal import Decimal

from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .models import Attendance, SalaryStructure
from .tasks import queue_salary_report_refresh


def calculate_gross_salary(change_type, amount, previous_gross_salary):
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
    current_pf_amount = Decimal("0.00")
    current_esi_amount = Decimal("0.00")

    updates = []

    for record in records:
        current_gross_salary = calculate_gross_salary(
            record.change_type, record.amount, current_gross_salary,
        )

        if record.change_type == "BASE_SALARY":
            current_pf_amount = record.pf_amount or Decimal("0.00")
            record.pf_amount = current_pf_amount
        elif record.pf_amount and record.pf_amount > 0:
            current_pf_amount = record.pf_amount
        else:
            record.pf_amount = current_pf_amount

        if record.change_type == "BASE_SALARY":
            current_esi_amount = record.esi_amount or Decimal("0.00")
            record.esi_amount = current_esi_amount
        elif record.esi_amount and record.esi_amount > 0:
            current_esi_amount = record.esi_amount
        else:
            record.esi_amount = current_esi_amount

        record.final_salary = current_gross_salary - current_pf_amount - current_esi_amount
        updates.append(record)

    if updates:
        SalaryStructure.objects.bulk_update(updates, ["pf_amount", "esi_amount", "final_salary"])


# NOTE on is_finalized: these signals just enqueue a user-level refresh --
# they don't know which period a given Attendance/SalaryStructure row falls
# into. The skip-if-finalized guard belongs in refresh_salary_reports()
# itself (see the docstring on refresh_salary_reports_task in tasks.py),
# since only it knows the period boundaries. No change needed here.

@receiver(post_save, sender=SalaryStructure)
def on_salary_structure_save(sender, instance, **kwargs):
    rebuild_salary_chain(instance.user)
    transaction.on_commit(lambda: queue_salary_report_refresh(instance.user_id))


@receiver(post_delete, sender=SalaryStructure)
def on_salary_structure_delete(sender, instance, **kwargs):
    rebuild_salary_chain(instance.user)
    transaction.on_commit(lambda: queue_salary_report_refresh(instance.user_id))


@receiver((post_save, post_delete), sender=Attendance)
def refresh_salary_reports_for_attendance(sender, instance, **kwargs):
    """Attendance is payroll input, so keep persisted salary snapshots current."""
    transaction.on_commit(lambda: queue_salary_report_refresh(instance.user_id))