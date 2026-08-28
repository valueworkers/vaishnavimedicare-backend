from django.db import models
from cloudinary.models import CloudinaryField

class FAQTopic(models.Model):
    topic = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.topic

class FAQItem(models.Model):
    topic = models.ForeignKey(
        FAQTopic,
        related_name="qanda",
        on_delete=models.CASCADE
    )
    question = models.TextField()
    answer = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.question[:50]
    
class Video(models.Model):
    video_name = models.CharField(max_length=255)
    video_file = CloudinaryField(resource_type="video", null=True, blank=True)
    video_url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.video_name