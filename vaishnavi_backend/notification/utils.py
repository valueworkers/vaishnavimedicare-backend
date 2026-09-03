from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .serializers import NotificationSerializer


def push_notification(notification):
    channel_layer = get_channel_layer()
    
    group_name = f"Public"

    serializer = NotificationSerializer(notification)
    
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "send_notification",
            "data": serializer.data
        }
    )