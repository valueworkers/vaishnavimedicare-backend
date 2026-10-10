from django.urls import path,include
from .views import (
    SalaryAnalysisAPIView,
    UserAttendanceAPIView,
    PaymentMasterViewSet,
    InvoiceListViewSet,
    DashboardKPIAPIView,
)
from rest_framework.routers import DefaultRouter

app_name = "analysis"

router = DefaultRouter()
router.register(r'payment-master', PaymentMasterViewSet, basename='payment-master')
router.register(r"invoices", InvoiceListViewSet, basename="invoice")

urlpatterns = [
    path('', include(router.urls)),
    path("salary/", SalaryAnalysisAPIView.as_view(), name="salary-analysis"),
    path('attendance/', UserAttendanceAPIView.as_view(), name='attendance-analysis'),
    path('dashboard-kpis/', DashboardKPIAPIView.as_view(), name='dashboard-kpis'),

]
