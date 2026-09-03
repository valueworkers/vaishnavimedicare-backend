from django.urls import path, include
from rest_framework import routers
from .views import *
app_name = 'attendance'

router = routers.DefaultRouter()

router.register(r'attendance-status', AttendanceStatusViewSet, basename='attendance-status')

urlpatterns = [
    path('', include(router.urls)),
    path('attendance/', AttendanceView.as_view(), name='attendance'),
    path('total-attendance/', AttendanceReportView.as_view(),name='total_attendance'),
]
