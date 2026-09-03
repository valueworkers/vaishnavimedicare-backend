# vaishnavi_backend/celery.py
import os
from celery import Celery
from celery.schedules import crontab, schedule
from datetime import timedelta
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vaishnavi_backend.settings')

app = Celery('vaishnavi_backend')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'daily-digest': {
        'task': 'notifications.tasks.send_daily_digest',
        'schedule': crontab(hour=8, minute=0),
    },
    'mark-attendance-present': {
        'task': 'attendance.tasks.mark_attendance_present',
        'schedule': crontab(hour=0, minute=0),
    },
    'update-booking-status': {
        'task': 'booking.tasks.update_statuses_by_time',
        'schedule': schedule(timedelta(minutes=5)),
    },

    "auto-continue-orders": {
        "task": "booking.tasks.trigger_auto_continue_secondary_orders",
        "schedule": crontab(hour=23, minute=30),   # run nightly at 23:30
    }

}

app.conf.timezone = settings.TIME_ZONE