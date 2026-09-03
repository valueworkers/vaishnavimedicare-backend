# notifications/services.py

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from .models import Notification, NotificationTemplate

def create_missed_attendance_notification(user, date):
    template = NotificationTemplate.objects.filter(
        name="missed_attendance",
        channel=Notification.Channel.ALERT,
        is_active=True
    ).first()

    message = f"You missed marking attendance for {date}"

    if template:
        message = template.body.replace("{{ date }}", str(date))

    exists = Notification.objects.filter(
        recipient=user,
        title="Attendance Missed",
        created_at__date=timezone.now().date()
    ).exists()

    if not exists:
        Notification.objects.create(
            owner=user.hierarchy.owner if hasattr(user, "hierarchy") else None,
            recipient=user,
            template=template,
            channel=Notification.Channel.ALERT,
            category=Notification.Category.ALERT,
            priority=Notification.Priority.HIGH,
            title="Attendance Missed",
            message=message,
            recipient_email=user.email or "",
            content_type=ContentType.objects.get_for_model(user),
            object_id=user.id,
        )