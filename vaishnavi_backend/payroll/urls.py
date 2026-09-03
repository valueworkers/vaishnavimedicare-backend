from rest_framework.routers import DefaultRouter
from django.urls import path, include
from . import views

app_name = 'payroll'

router = DefaultRouter()
router.register(r'salary-structures', views.SalaryStructureViewSet, basename='salary-structure')
router.register(r'salary-transactions', views.SalaryTransactionViewSet, basename='salary-transaction')

urlpatterns = [
    # Salary Structure endpoints
    path('', include(router.urls)),
    path("salary-report/", views.SalaryReportAPIView.as_view(),name="salary-report-list"),
    path("salary-report/<int:pk>/", views.SalaryReportAPIView.as_view(),name="salary-report-detail"),
]