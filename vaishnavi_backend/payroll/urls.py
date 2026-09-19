from rest_framework.routers import DefaultRouter
from django.urls import path, include
from . import views

app_name = 'payroll'

router = DefaultRouter()
router.register(r'employee-payroll', views.EmployeePayrollViewSet, basename='emp-payroll-list')
router.register(r'salary-structures', views.SalaryStructureViewSet, basename='salary-structure')
router.register(r'salary-transactions', views.SalaryTransactionViewSet, basename='salary-transaction')
router.register(r'attendance-status', views.AttendanceStatusViewSet, basename='attendance-status')

urlpatterns = [
    path('', include(router.urls)),
    path("attendance/", views.AttendanceView.as_view(), name="attendance"),
    path("reports/", views.PayrollReportAPIView.as_view(), name="payroll-reports"),
]
