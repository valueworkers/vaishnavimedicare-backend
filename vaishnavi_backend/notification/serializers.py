from rest_framework import serializers
from .models import Notification, NotificationTemplate


# -------------------------------------------------------------------
#                   NOTIFICATION TEMPLATE SERIALIZERS
# -------------------------------------------------------------------
class NotificationTemplateSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source='get_channel_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'owner', 'name', 'channel', 'channel_display',
            'category', 'category_display', 'subject', 'body',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# -------------------------------------------------------------------
#                     NOTIFICATION SERIALIZERS
# -------------------------------------------------------------------
class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            'id',
            'owner', 'recipient', 'template',
            'channel', 'category', 'priority', 
            'status', 'title', 'message', 'extra_data',
            'recipient_email', 'recipient_phone',
            'content_type', 'object_id',
            'scheduled_at',
            'sent_at', 'delivered_at', 'read_at',
            'failure_reason', 'retry_count',
            'is_read',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'sent_at', 'delivered_at', 'read_at',
            'failure_reason', 'retry_count', 'created_at', 'updated_at',
        ]


class NotificationCreateSerializer(serializers.ModelSerializer):
    """Slim serializer for creating notifications programmatically."""

    class Meta:
        model = Notification
        fields = [
            'recipient', 'template',
            'channel', 'category', 'priority',
            'title', 'message', 'extra_data',
            'recipient_email', 'recipient_phone',
            'content_type', 'object_id',
            'scheduled_at',
        ]

    def validate(self, attrs):
        channel = attrs.get('channel')
        recipient_email = attrs.get('recipient_email', '')
        recipient_phone = attrs.get('recipient_phone', '')

        if channel == Notification.Channel.EMAIL and not recipient_email:
            raise serializers.ValidationError(
                {"recipient_email": "recipient_email is required for Email notifications."}
            )
        if channel in (Notification.Channel.SMS, Notification.Channel.WHATSAPP) and not recipient_phone:
            raise serializers.ValidationError(
                {"recipient_phone": "recipient_phone is required for SMS/WhatsApp notifications."}
            )
        return attrs


class MarkReadSerializer(serializers.Serializer):
    """Used to bulk-mark notifications as read."""
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        help_text="List of Notification IDs to mark as read."
    )

class NotificationSubscriberSerializer(serializers.Serializer):
    recipient_id = serializers.IntegerField()
    template_name = serializers.CharField(required=False)
    channel = serializers.CharField()
    category = serializers.CharField()
    title = serializers.CharField(required=False)
    message = serializers.CharField(required=False)
    extra_data = serializers.JSONField(required=False)

    def validate(self, data):
        if not data.get('template_name') and not data.get('message'):
            raise serializers.ValidationError(
                "Either template_name or message is required"
            )
        return data
