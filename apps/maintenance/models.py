# apps/maintenance/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinLengthValidator
from datetime import datetime, time as dt_time
import uuid


class MaintenanceSchedule(models.Model):
    """Maintenance schedule for IT infrastructure checks per department."""
    
    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
    
    class Department(models.TextChoices):
        MARINE = 'MARINE', 'Marine'
        IT = 'IT', 'IT'
        ACCOUNTING = 'ACCOUNTING', 'Accounting'
        LEGAL = 'LEGAL', 'Legal'
        QHSE = 'QHSE', 'QHSE'
        OPERATIONS = 'OPERATIONS', 'Operations'
        PROJECT = 'PROJECT', 'Project'
        VESSEL_CATERING = 'VESSEL_CATERING', 'Vessel Catering'
        PURCHASE_PROTOCOL = 'PURCHASE_PROTOCOL', 'Purchase/Protocol'
        FREIGHT = 'FREIGHT', 'Freight'
        STORE = 'STORE', 'Store'
        HR = 'HR', 'HR'
        ADMIN = 'ADMIN', 'Admin'
        COMMERCIAL = 'COMMERCIAL', 'Commercial'
    
    # Core fields
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    department = models.CharField(max_length=30, choices=Department.choices)
    
    # Scheduling
    scheduled_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    
    # Assignment
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_maintenance'
    )
    # Optional extra personnel beyond the primary assignee — lets a schedule
    # be worked by a small team while keeping assigned_to as the single
    # "owner" that existing email/permission logic is built around.
    additional_assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='additional_maintenance'
    )
    
    # Status
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    
    # Checklist (stored as JSON array)
    checklist_items = models.JSONField(default=list, blank=True)
    completed_checklist = models.JSONField(default=list, blank=True)
    
    # Confirmation
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_maintenance'
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmation_comment = models.TextField(blank=True)
    
    # Email tracking
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    # Due-date reminder tracking — set by the send_maintenance_reminders
    # management command as each threshold is crossed, so a reminder is
    # never sent twice for the same schedule.
    reminder_24h_sent = models.BooleanField(default=False)
    reminder_1h_sent = models.BooleanField(default=False)
    reminder_10m_sent = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-scheduled_date', '-created_at']
        indexes = [
            models.Index(fields=['department', 'status']),
            models.Index(fields=['scheduled_date']),
            models.Index(fields=['assigned_to', 'status']),
        ]
        verbose_name = 'Maintenance Schedule'
        verbose_name_plural = 'Maintenance Schedules'
    
    def __str__(self):
        return f"{self.title} - {self.get_department_display()} ({self.scheduled_date})"
    
    def due_datetime(self):
        """The scheduled date/time this maintenance is due to start, used for
        reminder scheduling. Falls back to the start of the scheduled date
        when no start_time is set."""
        naive = datetime.combine(self.scheduled_date, self.start_time or dt_time.min)
        return timezone.make_aware(naive) if timezone.is_naive(naive) else naive

    def is_overdue(self):
        """Check if schedule is overdue (past date and not completed)."""
        if self.status in [self.Status.COMPLETED, self.Status.CANCELLED]:
            return False
        return self.scheduled_date < timezone.now().date()
    
    def is_assigned_to(self, user):
        """True if user is the primary assignee or one of the additional ones."""
        if not user or not user.is_authenticated:
            return False
        if self.assigned_to_id == user.id:
            return True
        return self.additional_assignees.filter(pk=user.pk).exists()

    def can_confirm(self):
        """Check if schedule can be confirmed (completed but not confirmed)."""
        return self.status == self.Status.COMPLETED and not self.confirmed_by
    
    def get_progress_percentage(self):
        """Calculate progress based on checklist completion."""
        if not self.checklist_items:
            return 0
        total = len(self.checklist_items)
        completed = len(self.completed_checklist)
        return round((completed / total) * 100) if total > 0 else 0


class MaintenanceActivityLog(models.Model):
    """Audit trail for maintenance schedule changes."""
    
    class Action(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        UPDATED = 'UPDATED', 'Updated'
        STATUS_CHANGED = 'STATUS_CHANGED', 'Status Changed'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        COMPLETED = 'COMPLETED', 'Completed'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        EMAIL_SENT = 'EMAIL_SENT', 'Email Sent'
    
    schedule = models.ForeignKey(
        MaintenanceSchedule,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Maintenance Activity Log'
        verbose_name_plural = 'Maintenance Activity Logs'
    
    def __str__(self):
        return f"{self.action} on {self.schedule} by {self.actor or 'System'}"