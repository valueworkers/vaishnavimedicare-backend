from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

class NotificationTemplate(models.Model):
    """
    Reusable message templates per channel/category.
    Body supports {{ variable }} placeholders for runtime substitution.
    """

    class Channel(models.TextChoices):
        WHATSAPP = 'whatsapp', 'WhatsApp'
        SMS = 'sms', 'SMS'
        EMAIL = 'email', 'Email'
        ALERT = 'alert', 'In-App Alert'

    class Category(models.TextChoices):
        OPERATIONAL = 'operational', 'Operational'
        SYSTEM = 'system', 'System'
        ALERT = 'alert', 'Alert'
        TASK = 'task', 'Task'

    owner = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='notification_templates',
        null=True, blank=True,
        help_text="Owning account. Null means this is a platform-level template."
    )
    name = models.CharField(max_length=120, help_text="Internal reference name for this template.")
    channel = models.CharField(max_length=20, choices=Channel.choices)
    category = models.CharField(max_length=20, choices=Category.choices)
    subject = models.CharField(
        max_length=255, blank=True, default='',
        help_text="Used as the email subject line. Ignored for SMS/WhatsApp/Alert."
    )
    body = models.TextField(
        help_text="Message body. Use {{ variable_name }} for dynamic substitution."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Template"
        verbose_name_plural = "Notification Templates"
        unique_together = ('owner', 'name', 'channel')
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_channel_display()}] {self.name}"

class Notification(models.Model):
    """
    Central notification record for all channels: WhatsApp, SMS, Email, Alert.
    Categories: Operational, System, Alert, Task.
    Tracks full delivery lifecycle from creation through to read.
    """

    class Channel(models.TextChoices):
        WHATSAPP = 'whatsapp', 'WhatsApp'
        SMS = 'sms', 'SMS'
        EMAIL = 'email', 'Email'
        VOICE = 'voice', 'Voice'
        IN_APP = 'in_app', 'In-App Alert'

    class Category(models.TextChoices):
        OPERATIONAL = 'operational', 'Operational'
        FUNCTIONAL = 'functional', 'Functional'
        ALERT = 'alert', 'Alert'
        TASK = 'task', 'Task'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        DELIVERED = 'delivered', 'Delivered'
        READ = 'read', 'Read'
        FAILED = 'failed', 'Failed'

    # ---- Ownership & Recipients ----
    owner = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='sent_notifications',
        null=True, blank=True,
        help_text="The VSRE owner under whose account this notification was triggered."
    )
    recipient = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='received_notifications',
        help_text="User receiving this notification."
    )
    template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications',
        help_text="Optional template this notification was generated from."
    )

    # ---- Classification ----
    channel = models.CharField(max_length=20, choices=Channel.choices, db_index=True)
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.PENDING, db_index=True
    )

    # ---- Content ----
    title = models.CharField(max_length=255)
    message = models.TextField()
    extra_data = models.JSONField(
        null=True, blank=True,
        help_text="Optional structured payload (e.g. action URLs, deep links, task IDs)."
    )

    # ---- Captured Contact Info (snapshot at send time) ----
    recipient_email = models.EmailField(
        blank=True, default='',
        help_text="Email address captured at notification creation time."
    )
    recipient_phone = models.CharField(
        max_length=20, blank=True, default='',
        help_text="Phone number captured at notification creation time (E.164 preferred)."
    )

    # ---- Source Object (Generic Relation) ----
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="ContentType of the model that triggered this notification."
    )
    object_id = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="PK of the object that triggered this notification."
    )
    source_object = GenericForeignKey('content_type', 'object_id')

    # ---- Scheduling ----
    scheduled_at = models.DateTimeField(
        null=True, blank=True,
        help_text="If set, notification should be dispatched at this time."
    )

    # ---- Delivery Timestamps ----
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # ---- Error Tracking ----
    failure_reason = models.TextField(
        blank=True, default='',
        help_text="Error detail if delivery failed."
    )
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="Number of delivery attempts made."
    )

    # ---- Audit ----
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'status']),
            models.Index(fields=['channel', 'category']),
            models.Index(fields=['owner', 'created_at']),
            models.Index(fields=['scheduled_at']),
        ]

    def __str__(self):
        return (
            f"[{self.get_channel_display()}|{self.get_category_display()}] "
            f"{self.title} → {self.recipient}"
        )

    # ---- Lifecycle helpers ----

    def mark_sent(self):
        self.status = self.Status.SENT
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at', 'updated_at'])

    def mark_delivered(self):
        self.status = self.Status.DELIVERED
        self.delivered_at = timezone.now()
        self.save(update_fields=['status', 'delivered_at', 'updated_at'])

    def mark_read(self):
        if self.status != self.Status.READ:
            self.status = self.Status.READ
            self.read_at = timezone.now()
            self.save(update_fields=['status', 'read_at', 'updated_at'])

    def mark_failed(self, reason=''):
        self.status = self.Status.FAILED
        self.failure_reason = reason
        self.retry_count += 1
        self.save(update_fields=['status', 'failure_reason', 'retry_count', 'updated_at'])

    @property
    def is_read(self):
        return self.status == self.Status.READ

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING
