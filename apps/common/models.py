from django.db import models
from django.conf import settings


def get_role_choices():
    """Role choices for fields that need them, without importing the User
    model directly (same pattern as apps/tickets/models.py::get_role_choices,
    duplicated locally rather than cross-imported since common is the
    lower-level app other apps depend on, not the reverse)."""
    return [
        ('SUPERADMIN', 'Super Admin'),
        ('ADMIN', 'Admin'),
        ('TEAM_LEAD', 'Team Lead'),
        ('AGENT', 'Support Team'),
        ('END_USER', 'User'),
    ]


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text='Lucide icon name, e.g. "book-open"')

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class Notification(models.Model):
    class Type(models.TextChoices):
        GENERAL = 'GENERAL', 'General'
        TICKET = 'TICKET', 'Ticket'
        REMOTE_SESSION = 'REMOTE_SESSION', 'Remote Session'
        MANAGER_REVIEW = 'MANAGER_REVIEW', 'Manager Review'
        APPROVAL = 'APPROVAL', 'Approval'
        RESOLUTION_CONFIRMATION = 'RESOLUTION_CONFIRMATION', 'Resolution Confirmation'

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications'
    )
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=500)
    is_read = models.BooleanField(default=False)
    url = models.URLField(blank=True)
    type = models.CharField(max_length=25, choices=Type.choices, default=Type.GENERAL)
    # Which of the recipient's roles this notification pertains to — null
    # means role-agnostic (system/general notifications), always shown
    # regardless of active role. Populated at creation time by whichever
    # view raises the notification; existing rows stay null (unscoped),
    # which is the safe default for anything created before this field
    # existed.
    role = models.CharField(max_length=20, choices=get_role_choices(), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read'], name='notif_recipient_is_read_idx'),
        ]

    def __str__(self):
        return f"Notification for {self.recipient.email}: {self.message[:50]}"


class PushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.URLField(unique=True)
    auth_key = models.CharField(max_length=255)
    p256dh_key = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'endpoint')

    def __str__(self):
        return f"PushSubscription for {self.user.email}"