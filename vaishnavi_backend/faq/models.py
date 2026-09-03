from django.db import models
from cloudinary.models import CloudinaryField
from django.core.validators import RegexValidator


class Contact(models.Model):
    class Platform(models.TextChoices):
        FACEBOOK = "facebook", "Facebook"
        TWITTER = "twitter", "Twitter/X"
        INSTAGRAM = "instagram", "Instagram"
        LINKEDIN = "linkedin", "LinkedIn"
        YOUTUBE = "youtube", "YouTube"
        REDDIT = "reddit", "Reddit"
        QUORA = "quora", "Quora"
        WEBSITE = "website", "Website"
        OTHER = "other", "Other"

    mobile_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message="Mobile number must be entered in the format: '+999999999'. Up to 15 digits allowed."
    )

    display_name = models.CharField(max_length=255)
    mobile_number = models.CharField(
        validators=[mobile_regex],
        max_length=17,
        blank=True,
        null=True
    )
    email = models.EmailField(blank=True, null=True)
    platform = models.CharField(
        max_length=20,
        choices=Platform.choices,
        default=Platform.OTHER
    )
    url = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"

    def __str__(self):
        return self.display_name
    
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