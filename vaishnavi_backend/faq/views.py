from rest_framework import viewsets, filters
from .serializers import FAQTopicSerializer,ContactSerializer,VideoSerializer
from .permissions import IsSuperUserOrOwnerOrReadOnly
from .models import Video,Contact,FAQTopic
from rest_framework.parsers import MultiPartParser, FormParser



class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all().order_by("-created_at")
    serializer_class = ContactSerializer
    permission_classes = [IsSuperUserOrOwnerOrReadOnly]

    filterset_fields = ["platform"]
    search_fields = ["display_name", "email", "mobile_number"]
    ordering_fields = ["created_at", "display_name"]


class FAQViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperUserOrOwnerOrReadOnly]
    queryset = FAQTopic.objects.prefetch_related("qanda").all()
    serializer_class = FAQTopicSerializer
    search_fields = ["topic", "qanda__question", "qanda__answer"]
    ordering_fields = ["created_at", "updated_at", "topic"]
    ordering = ["-created_at"]

class VideoViewSet(viewsets.ModelViewSet):
    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    permission_classes = [IsSuperUserOrOwnerOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["video_name"]
    ordering_fields = ["created_at", "updated_at", "video_name"]
    ordering = ["-created_at"]