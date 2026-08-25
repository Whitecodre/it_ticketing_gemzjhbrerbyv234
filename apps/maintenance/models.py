# apps/maintenance/models.py
from django.db import models
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone
from django.core.validators import MinLengthValidator
from datetime import datetime, time as dt_time
import uuid

from apps.accounts.models import User


class _DepartmentChoices:
    """Backward-compatible accessor mirroring apps.accounts.models.User
    .DEPARTMENT_CHOICES — sourced from there (not a hand-duplicated copy)
    so the two lists can't drift apart. Supports the same `.choices` and
    `.CODE` attribute access (e.g. `Department.IT`) that a TextChoices
    class would, since existing call sites across the codebase use both."""
    choices = User.DEPARTMENT_CHOICES


for _code, _label in User.DEPARTMENT_CHOICES:
    setattr(_DepartmentChoices, _code, _code)
del _code, _label


class Vendor(models.Model):
    """A third-party maintenance vendor/contractor — pure record-keeping,
    fully admin-managed (no hardcoded values). Not a schedule "assignee":
    attaching a vendor has no effect on who can start/complete/confirm a
    schedule's status, same as target_assets/facility_location."""

    name = models.CharField(max_length=200, unique=True)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    # Set when this vendor was created by someone typing an unrecognized
    # name into a procurement/mobilization form rather than by an admin —
    # same propose-and-approve shape as tickets.Vessel/JobNumber.proposed_by.
    # Null for vendors an admin added directly.
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='proposed_vendors'
    )
    # Which asset categories this vendor supplies — used to narrow the
    # vendor picker wherever a category is already known (procurement
    # requests, asset renewal). Lazy cross-app string reference (like the
    # reverse 'maintenance.Vendor' references in apps.tickets.models) avoids
    # any import-order coupling between the two apps. Empty = serves every
    # category (no filtering applied), so existing vendors aren't hidden
    # anywhere until an admin curates them.
    categories = models.ManyToManyField('tickets.AssetCategory', blank=True, related_name='vendors')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def categories_display(self):
        names = list(self.categories.values_list('name', flat=True))
        return ', '.join(names) if names else '—'


class MaintenanceSchedule(models.Model):
    """Maintenance schedule for IT infrastructure checks per department."""

    class Status(models.TextChoices):
        SCHEDULED = 'SCHEDULED', 'Scheduled'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    Department = _DepartmentChoices

    # Core fields
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # Multiple target departments — a single IT crew commonly covers several
    # under-loaded departments' maintenance in one schedule.
    departments = ArrayField(
        models.CharField(max_length=30, choices=Department.choices),
        default=list,
        blank=True,
    )

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

    # Target — what the maintenance work covers. target_assets links to
    # tracked Asset records; facility_location is free text for sites/rooms
    # that aren't tracked as assets (e.g. "Generator House").
    target_assets = models.ManyToManyField(
        'tickets.Asset',
        blank=True,
        related_name='maintenance_schedules',
    )
    facility_location = models.CharField(max_length=255, blank=True)

    # Third-party vendor(s) involved — descriptive only, see Vendor's
    # docstring above.
    vendors = models.ManyToManyField(Vendor, blank=True, related_name='maintenance_schedules')

    # Confirmation — DEPRECATED: superseded by per-asset MaintenanceAssetConfirmation
    # below (an asset's *owner*, not the technician, now confirms completion).
    # Retained only so historical schedules confirmed under the old schedule-level
    # flow keep meaningful data; do not write to these fields going forward.
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
            models.Index(fields=['status']),
            models.Index(fields=['scheduled_date']),
            models.Index(fields=['assigned_to', 'status']),
        ]
        verbose_name = 'Maintenance Schedule'
        verbose_name_plural = 'Maintenance Schedules'

    def __str__(self):
        return f"{self.title} - {self.departments_display} ({self.scheduled_date})"

    @property
    def departments_display(self):
        """Comma-joined display labels — replaces the choices-field-only
        get_department_display() now that departments is a multi-value list."""
        labels = dict(self.Department.choices)
        return ', '.join(labels.get(code, code) for code in self.departments) or '—'

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
        """DEPRECATED — schedule-level confirmation is superseded by per-asset
        MaintenanceAssetConfirmation. Left in place for backward compatibility
        with any external callers; not used by the current confirmation UI."""
        return self.status == self.Status.COMPLETED and not self.confirmed_by

    def get_progress_percentage(self):
        """Calculate progress based on checklist completion."""
        if not self.checklist_items:
            return 0
        total = len(self.checklist_items)
        completed = len(self.completed_checklist)
        return round((completed / total) * 100) if total > 0 else 0

    def confirmation_state(self):
        """Aggregate per-asset owner-confirmation state for this schedule.
        HAS_DISPUTE takes precedence over other statuses so a dispute is never
        hidden behind other confirmed/pending rows."""
        statuses = list(self.asset_confirmations.values_list('status', flat=True))
        if not statuses:
            return 'NOT_APPLICABLE'
        if MaintenanceAssetConfirmation.Status.DISPUTED in statuses:
            return 'HAS_DISPUTE'
        if all(s == MaintenanceAssetConfirmation.Status.CONFIRMED for s in statuses):
            return 'ALL_CONFIRMED'
        if all(s == MaintenanceAssetConfirmation.Status.PENDING for s in statuses):
            return 'ALL_PENDING'
        return 'PARTIALLY_CONFIRMED'


class MaintenanceActivityLog(models.Model):
    """Audit trail for maintenance schedule changes."""
    
    class Action(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        UPDATED = 'UPDATED', 'Updated'
        STATUS_CHANGED = 'STATUS_CHANGED', 'Status Changed'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        COMPLETED = 'COMPLETED', 'Completed'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        DISPUTED = 'DISPUTED', 'Disputed'
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


class MaintenanceAssetConfirmation(models.Model):
    """Per-asset owner confirmation that maintenance was actually carried out.

    One row per (schedule, asset), created once the technician marks the
    schedule COMPLETED. This is the anti-fraud control: the asset's owner
    (Asset.assigned_to) — not the technician who did the work — confirms or
    disputes completion. See apps.maintenance.views.can_confirm_asset_maintenance
    for who is allowed to act on a given row.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        DISPUTED = 'DISPUTED', 'Disputed'

    schedule = models.ForeignKey(
        MaintenanceSchedule,
        on_delete=models.CASCADE,
        related_name='asset_confirmations',
    )
    asset = models.ForeignKey(
        'tickets.Asset',
        on_delete=models.CASCADE,
        related_name='maintenance_confirmations',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    dispute_reason = models.TextField(blank=True)

    # Copied from schedule.completed_at when this row is created — anchors the
    # post-completion overdue-confirmation reminder independent of any later
    # change to the schedule's own completed_at.
    technician_completed_at = models.DateTimeField(null=True, blank=True)
    confirmation_reminder_sent = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['schedule', 'asset'], name='unique_schedule_asset_confirmation'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['confirmation_reminder_sent']),
        ]
        ordering = ['asset__name']
        verbose_name = 'Maintenance Asset Confirmation'
        verbose_name_plural = 'Maintenance Asset Confirmations'

    def __str__(self):
        return f"{self.asset} — {self.get_status_display()} ({self.schedule})"


class MaintenanceChecklistTemplate(models.Model):
    """Reusable, per-department checklist item text, offered as a picklist
    when scheduling maintenance. Admin-managed via System Settings; also
    grown automatically when a scheduler types a custom item."""

    Department = _DepartmentChoices

    department = models.CharField(max_length=30, choices=Department.choices)
    text = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['department', 'order', 'text']
        indexes = [models.Index(fields=['department', 'is_active'])]
        verbose_name = 'Maintenance Checklist Item'
        verbose_name_plural = 'Maintenance Checklist Items'

    def __str__(self):
        return f"{self.text} ({self.get_department_display()})"