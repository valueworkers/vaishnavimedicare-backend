from __future__ import annotations

import re
import calendar
from datetime import date, time, datetime,timedelta
from typing import Optional
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Prefetch, QuerySet, Q
from django.db import transaction

from .constants import BookingStatus,PeriodChoices
from .models import PrimaryOrder, SecondaryOrder, TernaryOrder,Payment, TotalInvoice


class DateParser:
    """Centralized date parsing for DAILY and HOURLY packages."""
    
    @staticmethod
    def parse_dates(period_type: str, raw_dates):
        """
        Parse and validate dates for DAILY and HOURLY packages.
        
        Args:
            period_type: PeriodChoices.DAILY or PeriodChoices.HOURLY
            raw_dates: List (DAILY) or Dict (HOURLY) of date strings
            
        Returns:
            Parsed dates in appropriate format or raises ValidationError
            
        Raises:
            ValidationError: If format is invalid for period type
        """
        
        if period_type == PeriodChoices.DAILY:
            return DateParser._parse_daily(raw_dates)
        elif period_type == PeriodChoices.HOURLY:
            return DateParser._parse_hourly(raw_dates)
        else:
            raise ValidationError(
                {"package": f"Unsupported period type: {period_type}"}
            )
    
    @staticmethod
    def _parse_daily(raw_dates) -> list:
        """Parse DAILY package dates (list of ISO date strings)."""
        if not isinstance(raw_dates, list):
            raise ValidationError(
                {"dates": "For DAILY package, 'dates' must be a list of ISO date strings."}
            )
        
        try:
            return [date.fromisoformat(d) for d in raw_dates]
        except ValueError:
            raise ValidationError(
                {"dates": "Invalid date format. Use YYYY-MM-DD."}
            )
    
    @staticmethod
    def _parse_hourly(raw_dates) -> dict:
        """Parse HOURLY package dates (dict with date keys and time slot values)."""
        if not isinstance(raw_dates, dict):
            raise ValidationError(
                {"dates": "For HOURLY package, 'dates' must be a dictionary."}
            )
        
        try:
            return {
                date.fromisoformat(d): [time.fromisoformat(t) for t in slots]
                for d, slots in raw_dates.items()
            }
        except ValueError:
            raise ValidationError(
                {"dates": "Invalid date or time format. Use YYYY-MM-DD and HH:MM:SS."}
            )
    
    @staticmethod
    def extract_datetime_bounds(period_type: str, parsed_dates) -> tuple:
        """
        Extract start_datetime and end_datetime from parsed dates.
        
        Returns:
            (start_datetime, end_datetime) as timezone-aware datetimes
        """
        if period_type == PeriodChoices.DAILY:
            # parsed_dates is a list of date objects
            min_date = min(parsed_dates)
            max_date = max(parsed_dates)
            start_dt = timezone.make_aware(datetime.combine(min_date, time.min))
            end_dt = timezone.make_aware(datetime.combine(max_date, time.max))
        
        elif period_type == PeriodChoices.HOURLY:
            # parsed_dates is a dict with date keys
            all_dates = list(parsed_dates.keys())
            min_date = min(all_dates)
            max_date = max(all_dates)
            start_dt = timezone.make_aware(datetime.combine(min_date, time.min))
            end_dt = timezone.make_aware(datetime.combine(max_date, time.max))
        
        else:
            raise ValueError(f"Unsupported period type: {period_type}")
        
        return start_dt, end_dt

class OrderQuerySet(QuerySet):
    """Custom QuerySet for PrimaryOrder to reduce duplication."""
    
    def with_related(self):
        """Optimized query with all related objects."""
        return self.select_related(
            'patient', 'venue', 'service', 'package', 'user'
        ).prefetch_related('secondary_orders__ternary_orders')
    
    def exclude_status(self, statuses: list):
        """Exclude orders with given statuses."""
        return self.exclude(status__in=statuses)
    
    def customer_visible(self, user):
        """Filter orders visible to a customer user."""
        from django.db.models import Q
        if user.is_customer:
            return self.filter(
                Q(patient__registered_by=user) | Q(user=user)
            )
        return self
    
    def filter_by_status(self, statuses: list):
        """Filter orders with given statuses."""
        return self.filter(status__in=statuses)
    
    def active(self):
        """Get non-LOBBY and non-HOLD orders (default for OrderViewSet)."""
        return self.exclude_status([BookingStatus.LOBBY, BookingStatus.HOLD])
    
    def pending(self):
        """Get LOBBY and HOLD orders (for LobbyOrderViewSet)."""
        return self.filter_by_status([BookingStatus.LOBBY, BookingStatus.HOLD])
    
    def by_timeframe(self, timeframe: str):
        """Filter by timeframe: 'ongoing', 'upcoming', or 'past'."""
        now = timezone.now()
        
        if timeframe == 'ongoing':
            return self.filter(start_datetime__lte=now, end_datetime__gte=now)
        elif timeframe == 'upcoming':
            return self.filter(start_datetime__gt=now)
        elif timeframe == 'past':
            return self.filter(end_datetime__lt=now)
        else:
            return self

class SecondaryOrderHelper:
    """Helper methods for SecondaryOrder operations."""
    
    @staticmethod
    def get_matching_secondary_order(
        primary_order: PrimaryOrder,
        start_dt: datetime,
        end_dt: datetime
    ) -> SecondaryOrder:
        """
        Find a SecondaryOrder that contains the given datetime range.
        
        Args:
            primary_order: The parent PrimaryOrder
            start_dt: Start datetime for the service
            end_dt: End datetime for the service
            
        Returns:
            SecondaryOrder matching the criteria
            
        Raises:
            SecondaryOrder.DoesNotExist: If no matching secondary order found
        """
        try:
            return primary_order.secondary_orders.get(
                start_datetime__lte=start_dt,
                end_datetime__gte=end_dt,
            )
        except SecondaryOrder.DoesNotExist:
            raise SecondaryOrder.DoesNotExist(
                f"No secondary order found for {start_dt.year}-{start_dt.month:02d}. "
                "Ensure the service date falls within the booking range."
            )
    
    @staticmethod
    def cascade_status_change(
        primary_order: PrimaryOrder,
        new_status: str,
        specific_secondary_id: int = None,
        specific_ternary_id: int = None
    ) -> None:
        """
        Cascade status change to child orders with proper logic.
        
        Rules:
        - Cancelling primary → cancel all children
        - Changing primary status → change all children
        - Changing secondary status → change its ternary orders
        - Changing ternary status → no cascade
        
        Args:
            primary_order: The root PrimaryOrder
            new_status: New status to apply
            specific_secondary_id: If set, only affect this secondary (and its ternaries)
            specific_ternary_id: If set, only affect this ternary (no cascade)
        """
        secondary_ids = primary_order.secondary_orders.values_list('id', flat=True)
        
        if new_status == BookingStatus.CANCELLED and not specific_secondary_id and not specific_ternary_id:
            # Primary cancelled → cascade everywhere
            SecondaryOrder.objects.filter(id__in=secondary_ids).update(status=new_status)
            TernaryOrder.objects.filter(secondary_order_id__in=secondary_ids).update(status=new_status)
        
        elif specific_ternary_id:
            # Only ternary change - no cascade
            pass  # Already handled in caller
        
        elif specific_secondary_id:
            # Secondary change → cascade to its ternaries only
            TernaryOrder.objects.filter(
                secondary_order_id=specific_secondary_id
            ).update(status=new_status)
        
        else:
            # Primary change (non-cancel) → cascade to all children
            SecondaryOrder.objects.filter(id__in=secondary_ids).update(status=new_status)
            TernaryOrder.objects.filter(secondary_order_id__in=secondary_ids).update(status=new_status)

class MonthAvailabilityChecker:
    """
    For every calendar day in the given month, checks whether the patient
    already has an active SecondaryOrder (for any service) on that day.
    Each booking entry also carries its non-cancelled TernaryOrder line
    items, if any exist.
    """

    def __init__(
        self,
        patient_id: int,
        month: int,
        year: int,
        exclude_order_id: Optional[int] = None,
    ):
        self.patient_id       = patient_id
        self.month            = month
        self.year             = year
        self.exclude_order_id = exclude_order_id

        self.last_day    = calendar.monthrange(year, month)[1]
        self.month_start = datetime(year, month, 1, 0, 0, 0)
        self.month_end   = datetime(year, month, self.last_day, 23, 59, 59)

    # ── Public ─────────────────────────────────────────────────────────────────

    def check(self) -> dict:
        qs = self._build_queryset(SecondaryOrder)

        month_first = date(self.year, self.month, 1)
        month_last  = date(self.year, self.month, self.last_day)
        date_bookings: dict[date, list[dict]] = {}

        for sec in qs:
            po = sec.primary_order

            ternary_orders = [
                {
                    "ternary_order_id" : t.pk,
                    "order_id"         : t.order_id,
                    "start_datetime"   : t.start_datetime,
                    "end_datetime"     : t.end_datetime,
                    "status"           : t.status,
                    "service_name"     : t.service.name if t.service else "—",
                    "package_name"     : t.package.name,
                    "venue_name"       : t.venue.name if t.venue else "—",
                }
                for t in sec.ternary_orders.all()  # prefetched, cancelled excluded
            ]

            booking = {
                "secondary_order_id" : sec.pk,
                "order_id"           : sec.order_id,
                "start_datetime"     : sec.start_datetime,
                "end_datetime"       : sec.end_datetime,
                "status"             : sec.status,
                "service_id"         : po.service_id,
                "service_name"       : po.service.name if po.service else "—",
                "package_name"       : po.package.name if po.package else "—",
                "primary_order_id"   : po.order_id,
                "booking_type"       : po.booking_type,
                "ternary_orders"     : ternary_orders,
            }

            cursor = max(sec.start_datetime.date(), month_first)
            end    = min(sec.end_datetime.date(),   month_last)
            while cursor <= end:
                date_bookings.setdefault(cursor, []).append(booking)
                cursor += timedelta(days=1)

        today         = timezone.now().date()
        calendar_rows = []
        past_days     = 0
        occupied_days = 0

        for day in range(1, self.last_day + 1):
            d        = date(self.year, self.month, day)
            is_past  = d < today
            bookings = date_bookings.get(d, [])
            is_avail = not bookings

            if is_past:
                past_days += 1
            if not is_avail:
                occupied_days += 1

            calendar_rows.append({
                "date"         : d,
                "is_available" : is_avail,
                "is_past"      : is_past,
                "bookings"     : bookings,
            })

        return {
            "patient_id"     : self.patient_id,
            "month"          : self.month,
            "year"           : self.year,
            "month_label"    : date(self.year, self.month, 1).strftime("%B %Y"),
            "total_days"     : self.last_day,
            "available_days" : self.last_day - occupied_days,
            "occupied_days"  : occupied_days,
            "past_days"      : past_days,
            "calendar"       : calendar_rows,
        }

    # ── Private ────────────────────────────────────────────────────────────────

    def _build_queryset(self, SecondaryOrder):
        """
        Overlap condition (covers all 4 overlap cases):
            slot.start < month_end  AND  slot.end > month_start
        """
        active_ternaries = Prefetch(
            "ternary_orders",
            queryset=TernaryOrder.objects
                .exclude(status=BookingStatus.CANCELLED)
                .select_related("service", "venue", "package")
                .order_by("start_datetime"),
        )

        qs = (
            SecondaryOrder.objects
            .filter(
                primary_order__patient_id=self.patient_id,
                start_datetime__lt=self.month_end,
                end_datetime__gt=self.month_start,
            )
            .exclude(primary_order__status=BookingStatus.CANCELLED)
            .exclude(status=BookingStatus.CANCELLED)
            .select_related(
                "primary_order",
                "primary_order__service",
                "primary_order__package",
                "primary_order__venue",
            )
            .prefetch_related(active_ternaries)
            .order_by("start_datetime")
        )

        if self.exclude_order_id:
            qs = qs.exclude(primary_order_id=self.exclude_order_id)

        return qs

class PaymentMappingService:

    AUTO_MAP_THRESHOLD = Decimal("90.00")
    REVIEW_THRESHOLD = Decimal("65.00")
    AMBIGUITY_MARGIN = Decimal("10.00")

    def __init__(self, payment):
        self.payment = payment

    # =========================================================
    # PUBLIC
    # =========================================================

    def run(self, dry_run: bool = False):
        """
        Score candidates for one payment.

        dry_run=True: never writes to the DB. Same result shape as a real
        run, plus "dry_run": True, so the API can preview without committing.
        """
        if self.payment.invoice_id and self.payment.patient_id:
            return {"status": "ALREADY_MAPPED", "payment_id": self.payment.id}

        candidates = self._find_candidates()
        scored = [r for r in (self._score_invoice(inv) for inv in candidates) if r["score"] > 0]

        if not scored:
            return self._finalize("UNMAPPED", dry_run)

        scored.sort(key=lambda x: x["score"], reverse=True)
        best = scored[0]

        if (
            best["score"] >= self.REVIEW_THRESHOLD
            and best["score"] < 100
            and len(scored) > 1
            and (best["score"] - scored[1]["score"]) < self.AMBIGUITY_MARGIN
        ):
            return self._finalize("REVIEW", dry_run, best, scored)

        if best["score"] >= self.AUTO_MAP_THRESHOLD:
            return self._finalize("AUTO_MAPPED", dry_run, best, scored)

        if best["score"] >= self.REVIEW_THRESHOLD:
            return self._finalize("REVIEW", dry_run, best, scored)

        return self._finalize("UNMAPPED", dry_run)

    # =========================================================
    # DISPATCH
    # =========================================================

    def _finalize(self, status, dry_run, best=None, scored=None):
        if dry_run:
            return self._preview_result(status, best, scored)
        if status == "AUTO_MAPPED":
            return self._auto_map(best)
        if status == "REVIEW":
            return self._mark_review(best, scored)
        return self._mark_unmapped()

    def _preview_result(self, status, best, scored):
        result = {"status": status, "payment_id": self.payment.id, "dry_run": True}
        if best:
            result["invoice_id"] = best["invoice"].id
            result["invoice_number"] = best["invoice"].invoice_number
            result["patient_id"] = best["invoice"].patient_id
            result["confidence"] = float(best["score"])
            result["reason"] = best["reason"]
        if scored:
            result["other_candidates"] = [
                {
                    "invoice_id": x["invoice"].id,
                    "invoice_number": x["invoice"].invoice_number,
                    "score": float(x["score"]),
                }
                for x in scored[1:5]
            ]
        return result

    # =========================================================
    # CANDIDATES
    # =========================================================

    def _find_candidates(self):
        payment = self.payment
        payment_date = payment.paid_date.date()

        filters = Q()
        invoice_numbers = self._extract_invoice_numbers()
        if invoice_numbers:
            filters |= Q(invoice_number__in=invoice_numbers)

        if payment.patient_id:
            filters |= Q(patient_id=payment.patient_id)

        # Amount and date only count together, not separately — otherwise
        # any invoice sharing the exact rupee amount anywhere in the last/next
        # 30 days becomes a full scoring candidate on every payment.
        filters |= Q(
            total_amount=payment.amount,
            issued_date__range=(
                payment_date - timedelta(days=30),
                payment_date + timedelta(days=30),
            ),
        )

        if not filters:
            return TotalInvoice.objects.none()

        return (
            TotalInvoice.objects.filter(filters)
            .exclude(remaining_amount__lte=0)  # fully paid invoices aren't valid targets
            .select_related("patient")
            .distinct()
        )

    def _extract_invoice_numbers(self):
        reference = self.payment.reference or ""
        return [
            value.upper()
            for value in re.findall(r"\b[ST]INV\d{1,12}\b", reference, flags=re.IGNORECASE)
        ]

    # =========================================================
    # SCORING (unchanged from your version)
    # =========================================================

    def _score_invoice(self, invoice):
        payment = self.payment
        score = Decimal("0.00")
        reasons = {}

        if self._reference_contains_invoice(payment.reference, invoice.invoice_number):
            score += Decimal("50.00")
            reasons["reference_invoice_match"] = True
        else:
            reasons["reference_invoice_match"] = False

        if payment.patient_id:
            patient_match = payment.patient_id == invoice.patient_id
        else:
            patient_match = self._patient_from_reference(payment.reference, invoice.patient)

        if patient_match:
            score += Decimal("25.00")
        reasons["patient_match"] = patient_match

        amount_match = payment.amount == invoice.total_amount
        if amount_match:
            score += Decimal("20.00")
        reasons["amount_match"] = amount_match

        date_difference = abs((payment.paid_date.date() - invoice.issued_date).days)
        if date_difference == 0:
            score += Decimal("5.00")
            reasons["date_match"] = "EXACT"
        elif date_difference <= 3:
            score += Decimal("3.00")
            reasons["date_match"] = "WITHIN_3_DAYS"
        elif date_difference <= 7:
            score += Decimal("1.00")
            reasons["date_match"] = "WITHIN_7_DAYS"
        else:
            reasons["date_match"] = "OUTSIDE_7_DAYS"

        if invoice.remaining_amount >= payment.amount:
            score += Decimal("5.00")
            reasons["amount_fits_remaining"] = True
        else:
            reasons["amount_fits_remaining"] = False

        return {"invoice": invoice, "score": min(score, Decimal("100.00")), "reason": reasons}

    # =========================================================
    # AUTO MAP
    # =========================================================

    @transaction.atomic
    def _auto_map(self, result):
        payment = Payment.objects.select_for_update().select_related("invoice").get(pk=self.payment.pk)

        if payment.invoice_id:
            return {"status": "ALREADY_MAPPED", "payment_id": payment.id, "invoice_id": payment.invoice_id}

        invoice = TotalInvoice.objects.select_for_update().get(pk=result["invoice"].pk)
        patient = invoice.patient

        payment.invoice = invoice
        payment.patient = patient
        payment.mapping_status = "AUTO_MAPPED"
        payment.mapping_meta = {
            "source": self._get_source(result["reason"]),
            "confidence": float(result["score"]),
            "reason": result["reason"],
        }
        payment.save(update_fields=["invoice", "patient", "mapping_status", "mapping_meta", "updated_at"])

        invoice.recalculate_payments()

        return {
            "status": "AUTO_MAPPED",
            "payment_id": payment.id,
            "invoice_id": invoice.id,
            "patient_id": patient.id,
            "confidence": float(result["score"]),
            "reason": result["reason"],
        }

    # =========================================================
    # REVIEW
    # =========================================================

    def _mark_review(self, best, candidates):
        mapping_reason = {
            "best_candidate": {
                "invoice_id": best["invoice"].id,
                "invoice_number": best["invoice"].invoice_number,
                "score": float(best["score"]),
                "reason": best["reason"],
            },
            "other_candidates": [
                {
                    "invoice_id": x["invoice"].id,
                    "invoice_number": x["invoice"].invoice_number,
                    "score": float(x["score"]),
                    "reason": x["reason"],
                }
                for x in candidates[1:5]
            ],
        }

        self.payment.mapping_status = "REVIEW"
        self.payment.mapping_meta = mapping_reason
        self.payment.save(update_fields=["mapping_status", "mapping_meta", "updated_at"])

        return {
            "status": "REVIEW",
            "payment_id": self.payment.id,
            "source": self._get_source(best["reason"]),
            "confidence": float(best["score"]),
            "reason": mapping_reason,
        }

    # =========================================================
    # UNMAPPED
    # =========================================================

    def _mark_unmapped(self):
        self.payment.mapping_status = "UNMAPPED"
        self.payment.save(update_fields=["mapping_status", "updated_at"])
        return {"status": "UNMAPPED", "payment_id": self.payment.id}

    # =========================================================
    # HELPERS (unchanged)
    # =========================================================

    @staticmethod
    def _normalize(value):
        if not value:
            return ""
        return re.sub(r"[^A-Z0-9]", "", value.upper())

    def _reference_contains_invoice(self, reference, invoice_number):
        ref = self._normalize(reference)
        inv = self._normalize(invoice_number)
        return bool(ref and inv and inv in ref)

    def _patient_from_reference(self, reference, patient):
        if not reference or not patient:
            return False
        normalized_reference = self._normalize(reference)

        if patient.patient_id and self._normalize(patient.patient_id) in normalized_reference:
            return True
        if patient.phone and patient.phone in normalized_reference:
            return True
        full_name = self._normalize(f"{patient.first_name}{patient.last_name}")
        if full_name and full_name in normalized_reference:
            return True
        return False

    @staticmethod
    def _get_source(reason):
        if reason.get("reference_invoice_match"):
            return "REFERENCE_INVOICE"
        if reason.get("patient_match") and reason.get("amount_match"):
            return "PATIENT_AMOUNT"
        if reason.get("amount_match"):
            return "AMOUNT_DATE"
        return "AUTO"
