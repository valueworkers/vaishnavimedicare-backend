from django.urls import re_path

from .consumers import AttendanceConsumer


payroll_websocket_urlpatterns = [
    re_path(r"^ws/attendance/$", AttendanceConsumer.as_asgi()),
]
