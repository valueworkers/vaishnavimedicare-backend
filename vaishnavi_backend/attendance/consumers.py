import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from datetime import date
from .models import Attendance, AttendanceStatus
from .utils import AttendanceCalculator


class AttendanceConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer that:
      1. Subscribes the connected user to their personal attendance group.
      2. Receives payloads pushed by the publisher via the channel layer.
      3. Persists / updates the Attendance row using your exact model fields.
      4. Sends the saved record + live computed AttendanceReport summary to the browser.

    Channel-layer event the publisher must send
    ───────────────────────────────────────────
    {
        "type": "push_attendance",
        "data": {
            "date":       "2025-04-14",          # required  (YYYY-MM-DD)
            "status_code": "PRESENT",            # required  (AttendanceStatus.code)
            "duration":   "08:30:00",            # optional  (HH:MM:SS string)
            "reason":     "On time"              # optional
        }
    }

    Browser → server messages
    ──────────────────────────
    { "action": "fetch_report", "period_type": "MONTHLY" }
    { "action": "fetch_today" }
    """

    # ──────────────────────────────────────────────────────────────────────
    #  Connection lifecycle
    # ──────────────────────────────────────────────────────────────────────

    async def connect(self):
        user = self.scope["user"]

        if not user or not user.is_authenticated:
            await self.close()
            return

        self.user = user
        self.group_name = f"attendance_{user.id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Send today's attendance record immediately on connect
        today_data = await self.get_today_attendance()
        await self.send(json.dumps({
            "type": "today_attendance",
            "data": today_data,
        }))

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    # ──────────────────────────────────────────────────────────────────────
    #  Channel-layer → consumer  (publisher pushes here)
    # ──────────────────────────────────────────────────────────────────────

    async def push_attendance(self, event):
        """
        Triggered by the channel layer when the publisher calls group_send().

        Flow:
            publisher.publish_attendance(user_id, ...)
                → channel layer group_send
                    → this method
                        → Attendance row saved/updated
                            → browser receives attendance_update + report_update
        """
        payload = event["data"]

        # 1. Persist to Attendance model
        saved, error = await self.save_attendance(payload)
        if error:
            await self.send(json.dumps({"type": "error", "message": error}))
            return

        # 2. Push the saved attendance record to the browser
        await self.send(json.dumps({
            "type": "attendance_update",
            "data": saved,
        }))

        # 3. Push the latest computed monthly report so the UI stays in sync
        report = await self.get_latest_report(period_type="MONTHLY")
        await self.send(json.dumps({
            "type": "report_update",
            "data": report,
        }))

    # ──────────────────────────────────────────────────────────────────────
    #  Browser → server
    # ──────────────────────────────────────────────────────────────────────

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")

        if action == "fetch_today":
            today_data = await self.get_today_attendance()
            await self.send(json.dumps({
                "type": "today_attendance",
                "data": today_data,
            }))

        elif action == "fetch_report":
            period_type = data.get("period_type", "MONTHLY")
            report = await self.get_latest_report(period_type=period_type)
            await self.send(json.dumps({
                "type": "report_update",
                "data": report,
            }))

    # ──────────────────────────────────────────────────────────────────────
    #  Database helpers
    # ──────────────────────────────────────────────────────────────────────

    @database_sync_to_async
    def save_attendance(self, payload: dict):
        """
        Create or update an Attendance record using AttendanceStatus.code lookup.

        Returns (serialised_dict, None) on success or (None, error_str) on failure.
        """
        from datetime import timedelta

        # Resolve AttendanceStatus by code
        try:
            status = AttendanceStatus.objects.get(
                code=payload["status_code"],
                is_active=True,
            )
        except AttendanceStatus.DoesNotExist:
            return None, f"Unknown status code: {payload['status_code']}"

        # Parse optional duration  "08:30:00" → timedelta
        duration = None
        if payload.get("duration"):
            try:
                h, m, s = map(int, payload["duration"].split(":"))
                duration = timedelta(hours=h, minutes=m, seconds=s)
            except (ValueError, AttributeError):
                pass  # leave duration as None if malformed

        record, _ = Attendance.objects.update_or_create(
            user=self.user,
            date=payload["date"],
            defaults={
                "status": status,
                "duration": duration,
                "reason": payload.get("reason", ""),
            },
        )

        return {
            "id": record.id,
            "user_id": record.user_id,
            "date": str(record.date),
            "status_code": status.code,
            "status_label": status.label,
            "duration": str(record.duration) if record.duration else None,
            "reason": record.reason,
            "updated_at": str(record.updated_at),
        }, None

    @database_sync_to_async
    def get_today_attendance(self):
        """Return today's Attendance record for this user, or None."""
        today = timezone.now().date()
        try:
            record = Attendance.objects.select_related("status").get(
                user=self.user, date=today
            )
            return {
                "id": record.id,
                "date": str(record.date),
                "status_code": record.status.code,
                "status_label": record.status.label,
                "duration": str(record.duration) if record.duration else None,
                "reason": record.reason,
                "updated_at": str(record.updated_at),
            }
        except Attendance.DoesNotExist:
            return None

    @database_sync_to_async
    def get_latest_report(self, period_type: str = "MONTHLY"):
        """
        Compute the most recent attendance report for the given period_type.
        Returns the report for the current/latest period containing attendance data.
        """
        # Use AttendanceCalculator to compute reports on-the-fly
        calc = AttendanceCalculator(self.user)
        
        # Get all computed reports for the period type
        reports = calc.get_all_periods_computed(period_type=period_type)
        
        if not reports:
            return None

        # Get the most recent report (last in the list since they're sorted by start_date)
        # For current period, get the one that includes today or the most recent one
        today = date.today()
        
        # First try to find a report that includes today
        for report in reversed(reports):
            if report['start_date'] <= today <= report['end_date']:
                return self._format_report(report)
        
        # If no report includes today, return the most recent one
        latest_report = reports[-1]
        return self._format_report(latest_report)

    def _format_report(self, report: dict):
        """Format a computed report dict for WebSocket transmission."""
        return {
            "period_type": report.get("period_type", "MONTHLY"),
            "start_date": str(report["start_date"]),
            "end_date": str(report["end_date"]),
            "present_days": str(report["present_days"]),
            "absent_days": str(report["absent_days"]),
            "half_day_count": str(report["half_day_count"]),
            "paid_leave_days": str(report["paid_leave_days"]),
            "weekly_offs": str(report["weekly_Offs"]),
            "unpaid_leaves": str(report["unpaid_leaves"]),
            "total_payable_days": str(report["total_payable_days"]),
            "total_payable_hours": str(report["total_payable_hours"]),
        }