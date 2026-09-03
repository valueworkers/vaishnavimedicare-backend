from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Q

import django_filters
from booking.models import TotalInvoice, InvoiceStatus


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_EMPLOYEE_SORT_FIELDS = {
    "emp_id":        "employee_id",
    "first_name":    "first_name",
    "last_name":     "last_name",
    "mobile_number": "mobile_number",
    "user_type":     "user_type",
}

ALLOWED_PERIOD_SORT_FIELDS = {
    "start_date":     "start_date",
    "end_date":       "end_date",
    "calendar_days":  "calendar_days",   # annotated
    "days_present":   "days_present",    # annotated
    "days_absent":    "days_absent",     # annotated
    "base_salary":    "base_salary",     # annotated
    "salary":         "salary",          # annotated
    "total_salary":   "total_payable_amount",
    "amount_paid":    "paid_amount",
    "excess_balance": "excess_balance",  # computed after annotation
    "status":         "tx_status",       # annotated
    "payment_date":   "payment_date",    # annotated
}

ALLOWED_USER_TYPES            = ["VSRE_MANAGER", "LINE_MANAGER", "VSRE_STAFF"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value, param_name):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError(f"'{param_name}' must be YYYY-MM-DD.")


def _parse_decimal(value, param_name):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError(f"'{param_name}' must be a valid number.")


def _parse_int(value, param_name):
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(f"'{param_name}' must be an integer.")


# ---------------------------------------------------------------------------
# Filter builder
# ---------------------------------------------------------------------------

def build_employee_filters(params: dict) -> tuple[Q, list[str]]:
    """
    Parse request params and return (Q object for CustomUser, errors list).

    Supported employee-level filters
    ---------------------------------
    user_id         : int
    user_type       : VSRE_MANAGER | LINE_MANAGER | VSRE_STAFF
    emp_id          : exact match on employee_id
    emp_id__icontains : partial match on employee_id
    first_name__icontains
    last_name__icontains
    mobile_number
    search          : searches across first_name, last_name, emp_id, mobile_number
    """
    q      = Q()
    errors = []

    # --- user_id ---
    if uid := params.get("user_id"):
        try:
            q &= Q(pk=_parse_int(uid, "user_id"))
        except ValueError as e:
            errors.append(str(e))

    # --- user_type ---
    if ut := params.get("user_type"):
        if ut not in ALLOWED_USER_TYPES:
            errors.append(f"'user_type' must be one of {ALLOWED_USER_TYPES}.")
        else:
            q &= Q(user_type=ut)

    # --- emp_id exact ---
    if eid := params.get("emp_id"):
        q &= Q(employee_id=eid)

    # --- emp_id partial ---
    if eid_c := params.get("emp_id__icontains"):
        q &= Q(employee_id__icontains=eid_c)

    # --- name search ---
    if fn := params.get("first_name__icontains"):
        q &= Q(first_name__icontains=fn)

    if ln := params.get("last_name__icontains"):
        q &= Q(last_name__icontains=ln)

    # --- mobile ---
    if mob := params.get("mobile_number"):
        q &= Q(mobile_number=mob)

    # --- global search (first_name OR last_name OR employee_id OR mobile) ---
    if search := params.get("search"):
        q &= (
            Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(employee_id__icontains=search)
            | Q(mobile_number__icontains=search)
        )

    # --- Status filter ---
    if status := params.get("status"):
        if status.lower() == "active":
            q &= Q(is_active=True)
        elif status.lower() == "inactive":
            q &= Q(is_active=False)
        else:
            errors["status"] = f"Invalid value '{status}'. Must be one of: active, inactive"

    return q, errors


def build_period_filters(params: dict) -> tuple[Q, list[str]]:
    """
    Parse request params and return (Q object for SalaryReport, errors list).

    Supported period-level filters
    --------------------------------
    start_date          : exact
    start_date__gte     : period starts on or after
    start_date__lte     : period starts on or before
    end_date            : exact
    end_date__gte
    end_date__lte
    days_present__gte
    days_present__lte
    days_absent__gte
    days_absent__lte
    base_salary__gte
    base_salary__lte
    salary__gte
    salary__lte
    total_salary__gte
    total_salary__lte
    amount_paid__gte
    amount_paid__lte
    excess_balance__gte
    excess_balance__lte
    status              : PENDING | PROCESSING | SUCCESS | FAILED | CANCELLED
    """
    q      = Q()
    errors = []

    # --- date filters ---
    date_params = [
        ("start_date",      "start_date"),
        ("start_date__gte", "start_date__gte"),
        ("start_date__lte", "start_date__lte"),
        ("end_date",        "end_date"),
        ("end_date__gte",   "end_date__gte"),
        ("end_date__lte",   "end_date__lte"),
    ]
    for param, lookup in date_params:
        if val := params.get(param):
            try:
                q &= Q(**{lookup: _parse_date(val, param)})
            except ValueError as e:
                errors.append(str(e))

    # --- decimal range filters ---
    # Maps (param_name → ORM field for SalaryReport or annotation name)
    decimal_range_params = [
        ("days_present__gte",    "days_present__gte"),
        ("days_present__lte",    "days_present__lte"),
        ("days_absent__gte",     "days_absent__gte"),
        ("days_absent__lte",     "days_absent__lte"),
        ("base_salary__gte",     "base_salary__gte"),
        ("base_salary__lte",     "base_salary__lte"),
        ("salary__gte",          "salary__gte"),
        ("salary__lte",          "salary__lte"),
        ("total_salary__gte",    "total_payable_amount__gte"),
        ("total_salary__lte",    "total_payable_amount__lte"),
        ("amount_paid__gte",     "paid_amount__gte"),
        ("amount_paid__lte",     "paid_amount__lte"),
    ]
    for param, lookup in decimal_range_params:
        if val := params.get(param):
            try:
                q &= Q(**{lookup: _parse_decimal(val, param)})
            except ValueError as e:
                errors.append(str(e))

    return q, errors


# ---------------------------------------------------------------------------
# Sort builder
# ---------------------------------------------------------------------------

def build_sort(params: dict) -> tuple[list[str], list[str]]:
    """
    Parse sort_by and sort_dir params.

    sort_by  : comma-separated list of field names from ALLOWED_EMPLOYEE_SORT_FIELDS
               or ALLOWED_PERIOD_SORT_FIELDS
    sort_dir : asc | desc  (applies to all fields, default asc)

    Returns (order_by_list, errors)

    Example:
        ?sort_by=start_date,total_salary&sort_dir=desc
        → ["-start_date", "-total_payable_amount"]
    """
    errors    = []
    order_by  = []
    sort_dir  = params.get("sort_dir", "asc").lower()

    if sort_dir not in ("asc", "desc"):
        errors.append("'sort_dir' must be 'asc' or 'desc'.")
        sort_dir = "asc"

    prefix = "-" if sort_dir == "desc" else ""

    all_sortable = {**ALLOWED_EMPLOYEE_SORT_FIELDS, **ALLOWED_PERIOD_SORT_FIELDS}

    raw_sort = params.get("sort_by", "")
    if raw_sort:
        for field in [f.strip() for f in raw_sort.split(",") if f.strip()]:
            if field not in all_sortable:
                errors.append(
                    f"'{field}' is not a sortable field. "
                    f"Allowed: {sorted(all_sortable.keys())}"
                )
            else:
                order_by.append(f"{prefix}{all_sortable[field]}")

    return order_by, errors

class TotalInvoiceFilter(django_filters.FilterSet):
    # Status
    status = django_filters.MultipleChoiceFilter(choices=InvoiceStatus.choices)

    # Invoice type shorthand
    invoice_type = django_filters.CharFilter(method="filter_invoice_type")

    # Patient / user
    patient  = django_filters.NumberFilter(field_name="patient__id")
    user     = django_filters.NumberFilter(field_name="user__id")

    # Period range
    period_start_after  = django_filters.DateTimeFilter(field_name="period_start", lookup_expr="gte")
    period_start_before = django_filters.DateTimeFilter(field_name="period_start", lookup_expr="lte")
    period_end_after    = django_filters.DateTimeFilter(field_name="period_end",   lookup_expr="gte")
    period_end_before   = django_filters.DateTimeFilter(field_name="period_end",   lookup_expr="lte")

    # Issued / due date range
    issued_date_after  = django_filters.DateFilter(field_name="issued_date", lookup_expr="gte")
    issued_date_before = django_filters.DateFilter(field_name="issued_date", lookup_expr="lte")
    due_date_after     = django_filters.DateFilter(field_name="due_date",    lookup_expr="gte")
    due_date_before    = django_filters.DateFilter(field_name="due_date",    lookup_expr="lte")

    # Amount ranges
    total_min     = django_filters.NumberFilter(field_name="total_amount",     lookup_expr="gte")
    total_max     = django_filters.NumberFilter(field_name="total_amount",     lookup_expr="lte")
    remaining_min = django_filters.NumberFilter(field_name="remaining_amount", lookup_expr="gte")
    remaining_max = django_filters.NumberFilter(field_name="remaining_amount", lookup_expr="lte")

    # FK convenience
    secondary_order = django_filters.NumberFilter(field_name="secondary_order__id")
    ternary_order   = django_filters.NumberFilter(field_name="ternary_order__id")
    parent_invoice  = django_filters.NumberFilter(field_name="parent_invoice__id")

    class Meta:
        model  = TotalInvoice
        fields = []  # all filters defined explicitly above

    def filter_invoice_type(self, queryset, name, value):
        value = value.upper()
        if value == "SECONDARY":
            return queryset.filter(secondary_order__isnull=False)
        if value == "TERNARY":
            return queryset.filter(ternary_order__isnull=False)
        return queryset