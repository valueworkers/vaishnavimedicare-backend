from rest_framework import viewsets, generics, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from rest_framework.views import APIView
from rest_framework import status
from .models import Notification, NotificationTemplate
from accounts.models import CustomUser
from django.db import transaction
from .utils import push_notification

from .serializers import (
    NotificationSerializer,
    NotificationCreateSerializer,
    NotificationTemplateSerializer,
    MarkReadSerializer,
    NotificationSubscriberSerializer
)



# --------------NOTIFICATION TEMPLATE VIEWSET------------------------
class NotificationTemplateViewSet(viewsets.ModelViewSet):
    """CRUD for notification templates. Owners see only their own templates."""
    serializer_class = NotificationTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['channel', 'category', 'is_active']
    search_fields = ['name', 'subject', 'body']
    ordering_fields = ['name', 'created_at']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        return NotificationTemplate.objects.filter(owner=user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

# ------------------NOTIFICATION VIEWSET-----------------------------
class NotificationViewSet(viewsets.ModelViewSet):
    """
    Full CRUD for notifications.

    Extra actions:
      POST /notifications/{id}/mark_read/   — mark a single notification as read
      POST /notifications/mark_read_bulk/   — mark multiple notifications as read
      GET  /notifications/unread_count/     — count of unread notifications for the user
    """
    
    filterset_fields = ['channel', 'category', 'priority', 'status']
    search_fields = ['title', 'message']
    ordering_fields = ['created_at', 'priority', 'status']
    ordering = ['-created_at']
    queryset = Notification.objects.select_related(
                'owner', 'recipient', 'template'
            )
    def get_queryset(self):
        
        user = self.request.user

        queryset = self.queryset.filter(recipient=user)
        
        if user.is_owner or user.is_superuser:
            queryset = self.queryset.filter(owner=user)

        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return NotificationCreateSerializer
        return NotificationSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=['post'], url_path='mark_read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        
        push_notification(notification)

        return Response(
            {'detail': 'Notification marked as read.'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['post'], url_path='mark_read_bulk')
    def mark_read_bulk(self, request):
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data['ids']
        updated = (
            Notification.objects
            .filter(id__in=ids, recipient=request.user)
            .exclude(status=Notification.Status.READ)
        )
        from django.utils import timezone
        count = updated.update(status=Notification.Status.READ, read_at=timezone.now())
        return Response(
            {'detail': f'{count} notification(s) marked as read.'},
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=['get'], url_path='unread_count')
    def unread_count(self, request):
        count = Notification.objects.filter(
            recipient=request.user
        ).exclude(status=Notification.Status.READ).count()
        return Response({'unread_count': count}, status=status.HTTP_200_OK)
    
# ------------------NOTIFICATION SUBCRIPTION VIEWSET-----------------------------
class NotificationSubscriberView(APIView):
    """
    Receives events from n8n and creates Notification records.
    """
    

    def post(self, request):
        serializer = NotificationSubscriberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            recipient = CustomUser.objects.get(id=data['recipient_id'])
        except CustomUser.DoesNotExist:
            return Response({"error": "Recipient not found"}, status=404)

        template = None
        message = data.get("message", "")
        title = data.get("title", "")

        # ---- Template Handling ----
        if data.get("template_name"):
            template = NotificationTemplate.objects.filter(
                name=data["template_name"],
                channel=data["channel"],
                is_active=True
            ).first()

            if template:
                message = self.render_template(template.body, data.get("extra_data", {}))
                title = template.subject or title

        # ---- Create Notification ----
        notification = Notification.objects.create(
            recipient=recipient,
            template=template,
            channel=data["channel"],
            category=data["category"],
            title=title,
            message=message,
            extra_data=data.get("extra_data", {}),
            recipient_email=recipient.email,
            recipient_phone=getattr(recipient, "phone", ""),
            status=Notification.Status.PENDING
        )

        return Response({
            "message": "Notification created",
            "id": notification.id
        }, status=status.HTTP_201_CREATED)

    def render_template(self, body, context):
        """
        Simple template renderer: replaces {{ key }}
        """
        for key, value in context.items():
            body = body.replace(f"{{{{ {key} }}}}", str(value))
        return body
   