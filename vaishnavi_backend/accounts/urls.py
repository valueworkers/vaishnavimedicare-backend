from django.urls import path, include
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework import routers
from .views import *
app_name = 'venue_manager'

router = routers.DefaultRouter()

router.register(r'vsre-owner', OwnerViewSet, basename='vsre-owner')
router.register(r'vsre-manager', ManagerViewSet, basename='vsre-manager')
router.register(r'vsre-staff', StaffViewSet, basename='vsre-staff')
router.register(r'customers', CustomerViewSet, basename='customers')
router.register(r'user-documents', UserDocumentViewSet, basename='user-documents')
router.register(r'pricing-models', PricingModelViewSet, basename='pricing-models')
router.register(r'user-plans', UserPlanViewSet, basename='user-plans')
router.register(r'staff-for-hire', StaffForHireViewSet, basename='staff-for-hire')

urlpatterns = router.urls


urlpatterns += [
    path('register/customer/', CustomerRegistrationView.as_view()),
    path('register/owner/', VSREOwnerRegistrationView.as_view()),
    path('login/', LoginView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('change-password/', ChangePasswordView.as_view()),
    path("request-otp/", RequestPasswordResetOTPView.as_view(), name="request-otp"),
    path("verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    path("password-reset/", ResetPasswordView.as_view(), name="reset-password"),
    path('token/refresh/', TokenRefreshView.as_view()),
    path('profile/', UserProfileView.as_view()),
    path("assign/<user_id>/parent/", ParentAssignmentView.as_view()),
    
]
