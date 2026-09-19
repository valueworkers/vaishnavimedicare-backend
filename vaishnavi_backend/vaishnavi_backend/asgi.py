import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vaishnavi_backend.settings')

from django.core.asgi import get_asgi_application

# Step 1: Initialize Django FIRST
django_asgi_app = get_asgi_application()

# Step 2: Import AFTER Django setup
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from notification.routing import notification_websocket_urlpatterns
from payroll.routing import payroll_websocket_urlpatterns

# Step 3: Combine all websocket routes
websocket_urlpatterns = (
    notification_websocket_urlpatterns +
    payroll_websocket_urlpatterns
)

# Step 4: Define application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})
