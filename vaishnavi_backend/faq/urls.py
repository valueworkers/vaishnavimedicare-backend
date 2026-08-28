from rest_framework.routers import DefaultRouter
from .views import FAQViewSet
from .views import VideoViewSet

app_name = "faq"

router = DefaultRouter()
router.register(r"faq", FAQViewSet, basename="faq")
router.register(r"video", VideoViewSet, basename="faq-video")

urlpatterns = router.urls