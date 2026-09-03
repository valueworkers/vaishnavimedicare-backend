from django.urls import path,include
from .views import NotificationViewSet, NotificationTemplateViewSet,NotificationSubscriberView
from rest_framework import routers

app_name = 'notifications'

router = routers.DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'templates', NotificationTemplateViewSet, basename='notification-template')

urlpatterns = [
    path('', include(router.urls), name='notifications'),
    path('subcriber-notifications/', NotificationSubscriberView.as_view(), name='subcriber-notifications'),
]