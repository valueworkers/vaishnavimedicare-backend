import json
from datetime import date, timedelta

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from .models import Attendance, AttendanceStatus
from .utils import PayrollCalculator


class AttendanceConsumer(AsyncWebsocketConsumer):
    """Payroll-owned real-time attendance channel (keeps the existing WS URL)."""

    async def connect(self):
        if not self.scope["user"].is_authenticated:
            await self.close()
            return
        self.user = self.scope["user"]
        self.group_name = f"attendance_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(json.dumps({"type": "today_attendance", "data": await self.today_attendance()}))

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def push_attendance(self, event):
        record, error = await self.save_attendance(event["data"])
        if error:
            await self.send(json.dumps({"type": "error", "message": error}))
            return
        await self.send(json.dumps({"type": "attendance_update", "data": record}))
        await self.send(json.dumps({"type": "report_update", "data": await self.current_report()}))

    async def receive(self, text_data):
        action = json.loads(text_data).get("action")
        if action == "fetch_today":
            await self.send(json.dumps({"type": "today_attendance", "data": await self.today_attendance()}))
        elif action == "fetch_report":
            await self.send(json.dumps({"type": "report_update", "data": await self.current_report()}))

    @database_sync_to_async
    def save_attendance(self, payload):
        status = AttendanceStatus.objects.filter(code=payload.get("status_code"), is_active=True).first()
        if not status:
            return None, "Unknown or inactive attendance status."
        duration = None
        if payload.get("duration"):
            try:
                hours, minutes, seconds = map(int, payload["duration"].split(":"))
                duration = timedelta(hours=hours, minutes=minutes, seconds=seconds)
            except ValueError:
                return None, "duration must use HH:MM:SS format."
        record, _ = Attendance.objects.update_or_create(
            user=self.user, date=payload.get("date", date.today()),
            defaults={"status": status, "duration": duration, "reason": payload.get("reason", "")},
        )
        return self._serialize(record), None

    @database_sync_to_async
    def today_attendance(self):
        record = Attendance.objects.select_related("status").filter(user=self.user, date=timezone.localdate()).first()
        return self._serialize(record) if record else None

    @database_sync_to_async
    def current_report(self):
        start, end = PayrollCalculator.period_for(date.today(), "MONTHLY")
        return PayrollCalculator(self.user).attendance_report(start, end)

    @staticmethod
    def _serialize(record):
        return {"id": record.id, "date": str(record.date), "status_code": record.status.code,
                "status_label": record.status.label, "duration": str(record.duration) if record.duration else None,
                "reason": record.reason, "updated_at": str(record.updated_at)}
