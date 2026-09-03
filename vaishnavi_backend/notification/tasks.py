from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(self, to_email, subject, message):
    """Send notification email asynchronously."""
    try:
        from django.core.mail import send_mail
        from django.conf import settings
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_push_task(self, user_id, title, message):
    """Send FCM/APNS push notification asynchronously."""
    try:
        from push_notifications.models import GCMDevice, APNSDevice
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.get(id=user_id)
        GCMDevice.objects.filter(user=user, active=True).send_message(message, title=title)
        APNSDevice.objects.filter(user=user, active=True).send_message(message, title=title)
    except Exception as exc:
        raise self.retry(exc=exc)

# TODO : Testing task

@shared_task
def send_daily_digest():
    """Celery Beat task: email digest of unread notifications every morning."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from datetime import timedelta
    from .models import Notification

    yesterday = timezone.now() - timedelta(days=1)
    for user in get_user_model().objects.filter(is_active=True, email__isnull=False):
        unread = Notification.objects.filter(
            recipient=user, is_read=False, created_at__gte=yesterday
        ).count()
        if unread:
            send_email_task.delay(
                user.email,
                f"🔔 You have {unread} unread notification{'s' if unread > 1 else ''}",
                f"Hi {user.username},\n\nYou have {unread} unread notifications. "
                f"Log in to check them.\n\nCheers,\nThe Team"
            )