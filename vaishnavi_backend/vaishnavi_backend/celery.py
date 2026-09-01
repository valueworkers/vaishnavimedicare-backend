# vaishnavi_backend/celery.py

import os
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab, schedule
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vaishnavi_backend.settings")

app = Celery("vaishnavi_backend")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Daily at 08:00
    "daily-digest": {
        "task": "notification.tasks.send_daily_digest",
        "schedule": crontab(hour=8, minute=0),
    },

    # Daily at 00:00
    "mark-attendance-present": {
        "task": "attendance.tasks.mark_attendance_present",
        "schedule": crontab(hour=0, minute=0),
    },

    # Every 5 minutes
    "update-booking-status": {
        "task": "booking.tasks.update_statuses_by_time",
        "schedule": schedule(timedelta(minutes=5)),
    },

    # Daily at 23:30
    "auto-continue-orders": {
        "task": "booking.tasks.trigger_auto_continue_secondary_orders",
        "schedule": crontab(hour=23, minute=30),
    },

    # ==========================================================
    # TEMPORARY CELERY TEST
    # Runs every minute
    # Remove after testing
    # ==========================================================
    "celery-test-every-minute": {
        "task": "vaishnavi_backend.celery.test_task",
        "schedule": crontab(minute=1),
    },
}

app.conf.timezone = settings.TIME_ZONE


@app.task
def test_task():
    print("========================================")
    print("CELERY TEST TASK EXECUTED SUCCESSFULLY")
    print("Celery Beat -> Redis -> Celery Worker OK")
    print("========================================")

    return "Celery test successful"