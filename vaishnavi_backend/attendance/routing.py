from django.urls import re_path
from . import consumers

attendance_websocket_urlpatterns = [
    re_path(r"^ws/attendance/$", consumers.AttendanceConsumer.as_asgi()),
]