from rest_framework.routers import DefaultRouter
from .views import FAQViewSet, ContactViewSet, VideoViewSet

app_name = "faq"

router = DefaultRouter()
router.register(r"faq", FAQViewSet, basename="faq")
router.register(r"video", VideoViewSet, basename="faq-video")
router.register(r"contacts", ContactViewSet, basename="contact")

urlpatterns = router.urls