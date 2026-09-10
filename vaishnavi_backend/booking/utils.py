from __future__ import annotations

from datetime import date, time, datetime,timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Prefetch, QuerySet

from .constants import BookingStatus,PeriodChoices
from .models import PrimaryOrder, SecondaryOrder, TernaryOrder 

import calendar
from typing import Optional



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

# ── Checker ──────────────────────────────────────────────────────────────────

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