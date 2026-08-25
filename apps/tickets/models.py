import calendar
import datetime
from django.db import models
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone
from apps.common.storage import raw_file_storage
from apps.accounts.models import User

# ================================================================
# IMPORT USER AFTER MODELS ARE DEFINED (Avoid circular import)
# ================================================================
# We'll use settings.AUTH_USER_MODEL or get_user_model() in fields
# For choices, we'll define them inline

def get_role_choices():
    """Get role choices for fields that need them."""
    return [
        ('SUPERADMIN', 'Super Admin'),
        ('ADMIN', 'Admin'),
        ('TEAM_LEAD', 'Team Lead'),
        ('AGENT', 'Support Team'),
        ('END_USER', 'User'),
    ]


class Vessel(models.Model):
    """A vessel in the client's fleet, selectable (multi) on vessel-related
    service requests. Admin-managed data — no fixed/hardcoded vessel list,
    since it's real per-client business data, not structural taxonomy.

    Also doubles as the target for third-party vessels proposed inline on a
    mobilization (see Mobilization/MobilizationItem in this file): proposing
    one creates a row here with is_active=False, same propose-and-approve
    shape as JobNumber.proposed_by below."""
    name = models.CharField(max_length=150, unique=True)
    imo_number = models.CharField(max_length=20, blank=True, help_text="IMO number, if known")
    is_active = models.BooleanField(default=True)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='proposed_vessels'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class DiveSystem(models.Model):
    """An admin-managed named diving equipment/support set, selectable
    (multi) on any service request — same shape as Vessel."""
    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class JobNumber(models.Model):
    """Admin-curated job number list. A requester can also propose a new
    job number inline on the service request form — that creates a row here
    with is_active=False (invisible in future dropdowns) and notifies admins;
    an admin approves it by flipping is_active to True in System Settings."""
    number = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='proposed_job_numbers'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.number


class ServiceCategory(models.Model):
    """Drives the dynamic fields shown on the Service Request form. Only
    `field_group` is code-mapped (apps.tickets.service_request_fields); name,
    description, icon, active state, and order are admin-editable data."""

    class FieldGroup(models.TextChoices):
        ASSET = 'ASSET', 'Asset / Equipment'
        JOB = 'JOB', 'Job / Work Order'
        VESSEL = 'VESSEL', 'Vessel / Marine Operations'
        PROCUREMENT = 'PROCUREMENT', 'Procurement / Purchase'
        HR = 'HR', 'HR / Personnel'
        LOGISTICS = 'LOGISTICS', 'Logistics / Freight'
        GENERAL = 'GENERAL', 'General'

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    description = models.CharField(max_length=255, blank=True)
    field_group = models.CharField(max_length=20, choices=FieldGroup.choices, default=FieldGroup.GENERAL)
    icon = models.CharField(max_length=40, blank=True, help_text="lucide icon name")
    is_active = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'Service categories'

    def __str__(self):
        return self.name


class TicketDraft(models.Model):
    """One in-progress, unsubmitted Incident/Service Request form per user
    per ticket type — supports both auto-save (unstable network resilience)
    and manual "Save Draft"."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ticket_drafts')
    ticket_type = models.CharField(max_length=20)
    form_data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'ticket_type')


class Ticket(models.Model):
    class Type(models.TextChoices):
        INCIDENT = 'INCIDENT', 'Incident'
        SERVICE_REQUEST = 'SERVICE_REQUEST', 'Service Request'
    
    def sla_status(self):
        now = timezone.now()
        result = {'response': 'ok', 'resolution': 'ok', 'response_pct': 0, 'resolution_pct': 0}

        try:
            sla = SLA.objects.get(priority=self.priority)
        except SLA.DoesNotExist:
            return result  # no policy → always ok

        # Response. Breach is judged directly against the deadline (now >=
        # due_at) rather than only from the elapsed/total percentage: when a
        # due_at is at or before created_at (e.g. a ticket whose response
        # SLA was already overdue when it was set), total_secs is <= 0 and
        # the old "only act if total_secs > 0" guard silently left this at
        # its default 'ok' — an overdue ticket reported as on-track.
        response_due = self.response_due_at or (
            self.created_at + datetime.timedelta(minutes=sla.response_minutes)
        )
        total_secs = (response_due - self.created_at).total_seconds()
        elapsed_secs = (now - self.created_at).total_seconds()
        pct = min(100, (elapsed_secs / total_secs) * 100) if total_secs > 0 else 100
        result['response_pct'] = round(pct, 1)
        if now >= response_due:
            result['response'] = 'breached'
        elif pct >= 75:
            result['response'] = 'warning'

        # Resolution — same logic.
        resolution_due = self.resolution_due_at or (
            self.created_at + datetime.timedelta(minutes=sla.resolution_minutes)
        )
        total_secs = (resolution_due - self.created_at).total_seconds()
        elapsed_secs = (now - self.created_at).total_seconds()
        pct = min(100, (elapsed_secs / total_secs) * 100) if total_secs > 0 else 100
        result['resolution_pct'] = round(pct, 1)
        if now >= resolution_due:
            result['resolution'] = 'breached'
        elif pct >= 75:
            result['resolution'] = 'warning'

        # Overall status
        if result['response'] == 'breached' or result['resolution'] == 'breached':
            result['overall'] = 'breached'
        elif result['response'] == 'warning' or result['resolution'] == 'warning':
            result['overall'] = 'warning'
        else:
            result['overall'] = 'ok'
        return result

    class Status(models.TextChoices):
        NEW = 'NEW', 'New'
        TRIAGED = 'TRIAGED', 'Triaged'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        PENDING_USER = 'PENDING_USER', 'Pending User'
        PENDING_VENDOR = 'PENDING_VENDOR', 'Pending Vendor'
        PENDING_APPROVAL = 'PENDING_APPROVAL', 'Pending Approval'
        PENDING_MANAGER_REVIEW = 'PENDING_MANAGER_REVIEW', 'Pending Manager Review'
        PENDING_FULFILLMENT = 'PENDING_FULFILLMENT', 'Pending Fulfillment'
        APPROVED = 'APPROVED', 'Approved'
        RESOLVED = 'RESOLVED', 'Resolved'
        CLOSED = 'CLOSED', 'Closed'
        ESCALATED = 'ESCALATED', 'Escalated' 

    class Impact(models.TextChoices):
        INDIVIDUAL = 'INDIVIDUAL', 'Individual'
        DEPARTMENT = 'DEPARTMENT', 'Department'
        SITE = 'SITE', 'Site'
        ORGANIZATION = 'ORGANIZATION', 'Organization'

    class Urgency(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        CRITICAL = 'CRITICAL', 'Critical'

    class Priority(models.TextChoices):
        P1 = 'P1', 'P1 - Critical'
        P2 = 'P2', 'P2 - High'
        P3 = 'P3', 'P3 - Medium'
        P4 = 'P4', 'P4 - Low'

    class IncidentCategory(models.TextChoices):
        HARDWARE_FAILURE = 'HARDWARE_FAILURE', 'Hardware Failure'
        SOFTWARE_ERROR = 'SOFTWARE_ERROR', 'Software / Application Error'
        NETWORK_CONNECTIVITY = 'NETWORK_CONNECTIVITY', 'Network / Connectivity'
        SECURITY_BREACH = 'SECURITY_BREACH', 'Security Breach / Unauthorized Access'
        DATA_LOSS = 'DATA_LOSS', 'Data Loss / Corruption'
        POWER_FAILURE = 'POWER_FAILURE', 'Power Failure'
        OTHER = 'OTHER', 'Other'

    class BusinessImpact(models.TextChoices):
        FULL_OUTAGE = 'FULL_OUTAGE', 'Full Outage'
        PARTIAL_OUTAGE = 'PARTIAL_OUTAGE', 'Partial Outage'
        DEGRADED_PERFORMANCE = 'DEGRADED_PERFORMANCE', 'Degraded Performance'
        NO_IMPACT = 'NO_IMPACT', 'No Immediate Impact'

    class DiscoveryMethod(models.TextChoices):
        MONITORING_ALERT = 'MONITORING_ALERT', 'Monitoring Tool / Alert'
        USER_COMPLAINT = 'USER_COMPLAINT', 'User Complaint'
        ROUTINE_CHECK = 'ROUTINE_CHECK', 'Routine Check'
        EXTERNAL_NOTIFICATION = 'EXTERNAL_NOTIFICATION', 'External Notification'
        OTHER = 'OTHER', 'Other'

    class RootCauseCategory(models.TextChoices):
        HUMAN_ERROR = 'HUMAN_ERROR', 'Human Error'
        CONFIGURATION_ERROR = 'CONFIGURATION_ERROR', 'Configuration Error'
        SOFTWARE_BUG = 'SOFTWARE_BUG', 'Software Bug / Patch Issue'
        HARDWARE_FAILURE = 'HARDWARE_FAILURE', 'Hardware Failure'
        CYBER_ATTACK = 'CYBER_ATTACK', 'Cyber Attack / Malware'
        POWER_INFRASTRUCTURE_FAILURE = 'POWER_INFRASTRUCTURE_FAILURE', 'Power / Infrastructure Failure'
        VENDOR_THIRD_PARTY = 'VENDOR_THIRD_PARTY', 'Vendor / Third-Party Issue'
        CHANGE_MANAGEMENT_FAILURE = 'CHANGE_MANAGEMENT_FAILURE', 'Change Management Failure'
        UNKNOWN = 'UNKNOWN', 'Unknown'

    # Core identification
    number = models.CharField(max_length=50, unique=True, editable=False)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.INCIDENT)
    title = models.CharField(max_length=255)
    description = models.TextField()

    # Categorization
    category = models.ForeignKey('common.Category', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='tickets')
    impact = models.CharField(max_length=20, choices=Impact.choices, default=Impact.INDIVIDUAL)
    urgency = models.CharField(max_length=20, choices=Urgency.choices, default=Urgency.MEDIUM)
    priority = models.CharField(max_length=2, choices=Priority.choices, editable=False)

    # Incident-report-specific fields (HDG-IT-FRM-086 Sections 1 & 3) — blank
    # for Service Request tickets and any ticket created before this field
    # set existed.
    incident_datetime = models.DateTimeField(null=True, blank=True, help_text="When the incident actually started")
    incident_category = models.CharField(max_length=25, choices=IncidentCategory.choices, blank=True)
    incident_category_other = models.CharField(max_length=100, blank=True)
    business_impact = models.CharField(max_length=25, choices=BusinessImpact.choices, blank=True)
    how_discovered = models.CharField(max_length=25, choices=DiscoveryMethod.choices, blank=True)
    how_discovered_other = models.CharField(max_length=100, blank=True)
    location_hostname = models.CharField(max_length=200, blank=True, help_text="Location / IP address / hostname, if known")
    immediate_actions = models.TextField(blank=True, help_text="Immediate/initial actions taken at the time of the incident")
    resolution_root_cause = models.TextField(blank=True, help_text="Root cause identified by the resolving agent")
    resolution_steps = models.TextField(blank=True, help_text="Steps taken by the resolving agent to fix the issue")
    resolution_root_cause_category = ArrayField(
        models.CharField(max_length=30, choices=RootCauseCategory.choices),
        blank=True, default=list, help_text="Root cause categories ticked by the resolving agent"
    )

    # Service-Request-specific fields — dynamic, category-driven (see
    # apps.tickets.service_request_fields). Left blank for Incident tickets
    # and any ticket created before this field set existed; the legacy
    # `category` field above is untouched so historical Service Requests
    # keep displaying correctly.
    service_category = models.ForeignKey(ServiceCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    purpose = models.CharField(max_length=255, blank=True)
    vessels = models.ManyToManyField(Vessel, blank=True, related_name='tickets')
    job_number = models.ForeignKey(JobNumber, on_delete=models.SET_NULL, null=True, blank=True, related_name='tickets')
    dive_systems = models.ManyToManyField(DiveSystem, blank=True, related_name='tickets')
    service_request_details = models.JSONField(default=dict, blank=True)

    # Best-effort device location captured client-side (browser Geolocation
    # API + reverse geocoding) at submission time. Optional and often blank
    # for offshore/at-sea coordinates, where reverse geocoding has no
    # address to return — the raw coordinates are kept as a fallback.
    submission_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    submission_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    submission_location_address = models.CharField(max_length=255, blank=True, default='')

    # Status & assignment
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NEW)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                  related_name='requested_tickets')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='assigned_tickets')
    queue = models.CharField(max_length=100, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # SLA targets
    response_due_at = models.DateTimeField(null=True, blank=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True)

    # Related asset
    asset_id = models.CharField(max_length=100, blank=True)
    
    # ========== NEW FIELDS FOR ASSET FULFILLMENT ==========
    is_asset_request = models.BooleanField(default=False)
    # Sub-flag of is_asset_request: this is asking for a batch of gear to go
    # out to a job/vessel/dive system (routed to the Mobilization flow) as
    # opposed to a single item for the requester personally (routed to
    # fulfill_asset_request). Always False when is_asset_request is False.
    is_mobilization_request = models.BooleanField(default=False)
    assigned_asset = models.ForeignKey(
        'Asset',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets'
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    fulfilled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fulfilled_tickets'
    )

    # ========== RESOLUTION CONFIRMATION & FEEDBACK ==========
    resolution_confirmed_at = models.DateTimeField(null=True, blank=True)
    feedback_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    feedback_comment = models.TextField(blank=True)
    feedback_submitted_at = models.DateTimeField(null=True, blank=True)
    resolution_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_resolutions'
    )

    # ========== INCIDENT REPORT — IT MANAGER / HEAD OF IT SIGN-OFF ==========
    # Merged approval: IT Manager and Head of IT are the same role in this
    # org, so a single approval satisfies both sign-off rows on the report.
    incident_approved_at = models.DateTimeField(null=True, blank=True)
    incident_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'queue']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['requester', 'created_at']),
            models.Index(fields=['number']),
            models.Index(fields=['status', 'is_asset_request']),
            models.Index(fields=['status', 'is_mobilization_request']),
        ]

    def __str__(self):
        return f"{self.number} - {self.title}"

    def save(self, *args, **kwargs):
        # Compute priority based on impact x urgency. Recomputes not just on
        # first save but whenever impact/urgency have changed since the last
        # save — otherwise correcting a ticket's impact/urgency post-creation
        # (e.g. via /admin/) leaves priority, and the SLA due dates derived
        # from it, silently stale.
        recompute_priority = not self.priority
        if self.pk and not recompute_priority:
            old = Ticket.objects.filter(pk=self.pk).values('impact', 'urgency').first()
            if old and (old['impact'] != self.impact or old['urgency'] != self.urgency):
                recompute_priority = True

        if recompute_priority:
            impact_score = {
                self.Impact.INDIVIDUAL: 1,
                self.Impact.DEPARTMENT: 2,
                self.Impact.SITE: 3,
                self.Impact.ORGANIZATION: 4
            }.get(self.impact, 1)

            urgency_score = {
                self.Urgency.LOW: 1,
                self.Urgency.MEDIUM: 2,
                self.Urgency.HIGH: 3,
                self.Urgency.CRITICAL: 4
            }.get(self.urgency, 1)

            if impact_score == 1:
                if urgency_score <= 3:
                    self.priority = self.Priority.P4
                else:
                    self.priority = self.Priority.P3
            elif impact_score == 2:
                if urgency_score <= 2:
                    self.priority = self.Priority.P4
                elif urgency_score == 3:
                    self.priority = self.Priority.P3
                else:
                    self.priority = self.Priority.P2
            elif impact_score == 3:
                if urgency_score == 1:
                    self.priority = self.Priority.P4
                elif urgency_score == 2:
                    self.priority = self.Priority.P3
                elif urgency_score == 3:
                    self.priority = self.Priority.P2
                else:
                    self.priority = self.Priority.P1
            else:  # impact = Organization
                if urgency_score == 1:
                    self.priority = self.Priority.P3
                elif urgency_score == 2:
                    self.priority = self.Priority.P2
                else:
                    self.priority = self.Priority.P1
        super().save(*args, **kwargs)


class TicketComment(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = 'PUBLIC', 'Public'
        INTERNAL = 'INTERNAL', 'Internal'

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    body = models.TextField()
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author} on {self.ticket}"


class Attachment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='attachments')
    comment = models.ForeignKey(TicketComment, on_delete=models.SET_NULL, null=True, blank=True)
    file = models.FileField(upload_to='attachments/%Y/%m/%d/', storage=raw_file_storage())
    filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    hash = models.CharField(max_length=64, blank=True)
    # Cached LibreOffice-converted PDF for Office attachments (doc/docx/xls/
    # xlsx/ppt/pptx) so the preview modal can embed it natively instead of
    # depending on Google Docs Viewer, which can't reach a local/private
    # file URL at all and is unreliable generally. Generated lazily on first
    # preview request — see apps/tickets/views.py's attachment_preview.
    preview_pdf = models.FileField(upload_to='attachments/previews/%Y/%m/%d/', storage=raw_file_storage(), blank=True, null=True)

    def __str__(self):
        return self.filename


class TicketActivityLog(models.Model):
    """Immutable audit trail for ticket changes (append-only)."""
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=50)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    details = models.JSONField(default=dict, blank=True)
    correlation_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} on {self.ticket} by {self.actor}"
    

class BusinessCalendar(models.Model):
    name = models.CharField(max_length=100)
    workdays = models.JSONField(default=list)
    work_start = models.TimeField(default=datetime.time(8, 0))
    work_end = models.TimeField(default=datetime.time(18, 0))
    holidays = models.JSONField(default=list)

    @property
    def workday_names(self):
        mapping = {
            0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'
        }
        return [mapping.get(int(d), str(d)) for d in self.workdays]

    def __str__(self):
        return self.name


class SLA(models.Model):
    priority = models.CharField(max_length=2, choices=Ticket.Priority.choices, unique=True)
    response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()
    calendar = models.ForeignKey(BusinessCalendar, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"SLA for {self.get_priority_display()}"
    
    def get_response_display(self):
        return self._format_minutes(self.response_minutes)
    
    def get_resolution_display(self):
        return self._format_minutes(self.resolution_minutes)
    
    def _format_minutes(self, minutes):
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        mins = minutes % 60
        if mins == 0:
            return f"{hours}h"
        return f"{hours}h {mins}m"

    @property
    def response_hours(self):
        return round(self.response_minutes / 60, 1)
    
    @property
    def resolution_hours(self):
        return round(self.resolution_minutes / 60, 1)


def add_business_minutes(start, minutes, business_calendar):
    """Advance `start` by `minutes` of business time per `business_calendar`
    (workdays/work_start/work_end/holidays), rolling over to the next open
    workday once a day's window is used up.

    Falls back to naive calendar-time addition — used by apply_sla() when an
    SLA has no calendar attached, or the calendar itself is unusable (no
    workdays selected, or work_end <= work_start) — rather than looping
    forever trying to find a business window that doesn't exist.
    """
    if business_calendar is None:
        return start + datetime.timedelta(minutes=minutes)

    try:
        workdays = {int(d) for d in business_calendar.workdays}
    except (TypeError, ValueError):
        workdays = set()
    holidays = set(business_calendar.holidays or [])
    work_start = business_calendar.work_start
    work_end = business_calendar.work_end

    daily_window_minutes = (
        datetime.datetime.combine(datetime.date.min, work_end)
        - datetime.datetime.combine(datetime.date.min, work_start)
    ).total_seconds() / 60
    if not workdays or daily_window_minutes <= 0:
        return start + datetime.timedelta(minutes=minutes)

    current = timezone.localtime(start)

    def is_business_day(dt):
        return dt.weekday() in workdays and dt.date().isoformat() not in holidays

    def at_time(dt, t):
        return dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)

    # Snap forward to the start of the next open business window.
    while not is_business_day(current) or current.time() >= work_end:
        current = at_time(current + datetime.timedelta(days=1), work_start)
    if current.time() < work_start:
        current = at_time(current, work_start)

    remaining = minutes
    while remaining > 0:
        window_close = at_time(current, work_end)
        available = (window_close - current).total_seconds() / 60
        if remaining <= available:
            current = current + datetime.timedelta(minutes=remaining)
            remaining = 0
        else:
            remaining -= available
            current = at_time(current + datetime.timedelta(days=1), work_start)
            while not is_business_day(current):
                current = at_time(current + datetime.timedelta(days=1), work_start)

    return current


class EscalationRule(models.Model):
    TIMER_CHOICES = [('response', 'Response'), ('resolution', 'Resolution')]
    ACTION_CHOICES = [
        ('notify', 'Notify'),
        ('reassign', 'Reassign'),
        ('add_watcher', 'Add Watcher'),
    ]

    priority = models.CharField(max_length=2, choices=Ticket.Priority.choices)
    timer_type = models.CharField(max_length=20, choices=TIMER_CHOICES)
    threshold_percent = models.PositiveIntegerField()
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES)
    notify_role = models.CharField(max_length=20, choices=get_role_choices(), null=True, blank=True)
    reassign_to_role = models.CharField(max_length=20, choices=get_role_choices(), null=True, blank=True)

    def __str__(self):
        return f"Escalation {self.get_action_type_display()} at {self.threshold_percent}% of {self.get_timer_type_display()} for {self.get_priority_display()}"
    

class Macro(models.Model):
    class Type(models.TextChoices):
        COMMENT = 'COMMENT', 'Comment'
        REASSIGN_REASON = 'REASSIGN_REASON', 'Reassign Reason'
        RETURN_REASON = 'RETURN_REASON', 'Return Reason'
    class Visibility(models.TextChoices):
        PUBLIC = 'PUBLIC', 'Public'
        INTERNAL = 'INTERNAL', 'Internal'
        PRIVATE = 'PRIVATE', 'Private (only me)'

    title = models.CharField(max_length=100)
    body = models.TextField()
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.COMMENT)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PUBLIC)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

# apps/tickets/models.py - Replace your Asset model section with this

# ==========================================================================
# ASSET CATEGORY (NEW)
# ==========================================================================

class AssetCategory(models.Model):
    """Hierarchical asset categorization (e.g., IT → Hardware → Laptops → MacBook)"""
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='children'
    )
    description = models.TextField(blank=True)
    
    # Visual
    icon = models.CharField(
        max_length=50, 
        blank=True, 
        help_text="Icon name from Lucide (e.g., 'laptop', 'monitor', 'printer')"
    )
    color = models.CharField(
        max_length=7, 
        default='#64748B',
        help_text="Hex color code for category badge"
    )
    
    # Default settings
    default_warranty_months = models.PositiveIntegerField(default=12)
    default_depreciation_years = models.PositiveIntegerField(default=3)

    # Bulk/consumable stock (cable ties, PPE, etc.) vs. individually-tracked
    # assets (laptops, radios — default, unchanged behavior). When True,
    # assets in this category represent a stock-count SKU rather than one
    # unique physical unit each.
    is_consumable = models.BooleanField(default=False)

    # Assets that renew on a recurring cadence regardless of physical
    # condition (software licenses, subscriptions, support contracts) rather
    # than being acquired once. When True, assets in this category expose
    # the renewal date/cost/vendor field group below.
    is_renewable = models.BooleanField(default=False)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Asset Categories"
        ordering = ['name']
    
    def __str__(self):
        return self.full_name()
    
    def full_name(self):
        if self.parent:
            return f"{self.parent.full_name()} → {self.name}"
        return self.name
    
    def get_children_count(self):
        return self.children.count()
    
    def get_asset_count(self):
        return self.assets.count()
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


def _add_months(start_date, months):
    """Calendar-correct month addition (no python-dateutil dependency),
    clamping to the last valid day of the target month (e.g. Jan 31 + 1
    month -> Feb 28/29, not an invalid Feb 31)."""
    month_index = start_date.month - 1 + months
    year = start_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start_date.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


# ==========================================================================
# ASSET MODEL (UPDATED)
# ==========================================================================

def _notify_it_admins(message, url):
    """Shared by every asset-custody step that needs to reach 'the admins'
    (checkout acceptance/dispute, return request/cancel, low-stock alerts).
    Narrows via the legacy `role` field or the roles M2M (either can lag
    right after account creation), then resolves each candidate's true
    active role in Python — a raw role__in=[...] filter misses/wrongly-
    includes admins whose active role has diverged from the legacy field."""
    from django.db.models import Q
    from apps.common.models import Notification
    from apps.common.utils import role_of
    from apps.common.permissions import effective_role_name

    candidates = User.objects.filter(
        Q(role__in=['ADMIN', 'SUPERADMIN']) | Q(roles__name__in=['ADMIN', 'SUPERADMIN']),
        is_active=True,
    ).distinct()
    for recipient in candidates:
        if effective_role_name(recipient) in ('ADMIN', 'SUPERADMIN'):
            Notification.objects.create(recipient=recipient, role=role_of(recipient), message=message, url=url)


class Asset(models.Model):
    # ================================================================
    # LOCATIONS
    # ================================================================
    class Location(models.TextChoices):
        HQ = 'HQ', 'Headquarters'
        BRANCH_A = 'BRANCH_A', 'Branch A - Lagos'
        BRANCH_B = 'BRANCH_B', 'Branch B - Abuja'
        BRANCH_C = 'BRANCH_C', 'Branch C - Port Harcourt'
        WAREHOUSE = 'WAREHOUSE', 'Warehouse'
        DATA_CENTER = 'DATA_CENTER', 'Data Center'
        OTHER = 'OTHER', 'Other'

    # ================================================================
    # STATUS (Enhanced workflow)
    # ================================================================
    class Status(models.TextChoices):
        # Procurement
        REQUESTED = 'REQUESTED', 'Requested'
        APPROVED = 'APPROVED', 'Approved'
        ORDERED = 'ORDERED', 'Ordered'
        RECEIVED = 'RECEIVED', 'Received'
        
        # Availability
        IN_STORE = 'IN_STORE', 'In Store'
        READY = 'READY', 'Ready for Deployment'
        
        # Active Use
        CHECKED_OUT = 'CHECKED_OUT', 'Checked Out'
        IN_USE = 'IN_USE', 'In Use'
        MOBILIZED = 'MOBILIZED', 'Mobilized'
        
        # Maintenance
        MAINTENANCE = 'MAINTENANCE', 'Maintenance'
        REPAIR = 'REPAIR', 'Repair'
        DAMAGED = 'DAMAGED', 'Damaged'

        # End of Life
        RETURNED = 'RETURNED', 'Returned'
        RETIRED = 'RETIRED', 'Retired'
        SCRAPPED = 'SCRAPPED', 'Scrapped'
        LOST = 'LOST', 'Lost'
        STOLEN = 'STOLEN', 'Stolen'
        DISPOSED = 'DISPOSED', 'Disposed'

    # ================================================================
    # RETURN REASONS
    # ================================================================
    class ReturnReason(models.TextChoices):
        DISPOSAL = 'DISPOSAL', 'Disposal'
        TERMINATION = 'TERMINATION', 'Employee Termination'
        SCRAPPED = 'SCRAPPED', 'Scrapped'
        UPGRADED = 'UPGRADED', 'Upgraded'
        DAMAGED = 'DAMAGED', 'Damaged'
        RETURNED = 'RETURNED', 'Returned'
        REPURPOSED = 'REPURPOSED', 'Repurposed'
        LOST = 'LOST', 'Lost'
        STOLEN = 'STOLEN', 'Stolen'
        OTHER = 'OTHER', 'Other'

    # ================================================================
    # CONDITION CHOICES
    # ================================================================
    class Condition(models.TextChoices):
        EXCELLENT = 'EXCELLENT', 'Excellent'
        GOOD = 'GOOD', 'Good'
        FAIR = 'FAIR', 'Fair'
        POOR = 'POOR', 'Poor'
        DAMAGED = 'DAMAGED', 'Damaged'
        UNUSABLE = 'UNUSABLE', 'Unusable'

    # ================================================================
    # BASIC IDENTIFICATION
    # ================================================================
    name = models.CharField(max_length=200)
    tracking_id = models.CharField(max_length=50, unique=True, editable=False)
    
    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='assets'
    )
    
    # Technical details
    serial_number = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True, default=Location.HQ)

    # Meaningful only when category.is_consumable — the number of units
    # currently in stock for this bulk/consumable SKU. Individually-tracked
    # assets (the default) leave this at 1 and never show/edit it; their
    # identity is the unique tracking_id, not a count.
    quantity_in_stock = models.PositiveIntegerField(default=1)

    # Low-stock alerting — asset-lifecycle infrastructure, not tied to any
    # one workflow. low_stock_notified guards against re-notifying on every
    # single change while stock stays under threshold; refresh_low_stock_alert()
    # below is the single place that reads/writes it, called from wherever
    # quantity_in_stock changes.
    low_stock_threshold = models.PositiveIntegerField(null=True, blank=True)
    low_stock_notified = models.BooleanField(default=False)

    # ================================================================
    # RENEWAL (software licenses, subscriptions, support contracts) —
    # meaningful only when category.is_renewable. Same "flag-gated field
    # group" shape as the consumable-stock fields above.
    # ================================================================
    next_renewal_date = models.DateField(null=True, blank=True)
    renewal_interval_months = models.PositiveIntegerField(null=True, blank=True)
    renewal_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    renewal_vendor = models.ForeignKey(
        'maintenance.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asset_renewals'
    )
    renewal_reference = models.CharField(max_length=100, blank=True)
    auto_renews = models.BooleanField(default=False)
    # Reset together by mark_renewed() so the next cycle's reminders fire
    # again — unlike send_maintenance_reminders' one-shot flags, these are
    # recurring per renewal cycle, same reset-on-clear idea as
    # low_stock_notified above.
    renewal_reminder_90d_sent = models.BooleanField(default=False)
    renewal_reminder_30d_sent = models.BooleanField(default=False)
    renewal_reminder_7d_sent = models.BooleanField(default=False)
    # Date of the last "this renewal is overdue" nag — unlike the 90/30/7d
    # flags above (one-shot per cycle), overdue nagging repeats every 7
    # days until the renewal is actually actioned, so this stores *when*
    # rather than *whether*.
    renewal_reminder_overdue_last_sent = models.DateField(null=True, blank=True)

    # ================================================================
    # PURCHASE / WARRANTY
    # ================================================================
    purchase_date = models.DateField(null=True, blank=True)

    # ================================================================
    # WARRANTY
    # ================================================================
    warranty_expiry = models.DateField(null=True, blank=True)
    warranty_duration_years = models.PositiveSmallIntegerField(
        default=0, 
        help_text="Warranty duration in years"
    )
    warranty_provider = models.CharField(max_length=200, blank=True)
    warranty_notes = models.TextField(blank=True)

    # ================================================================
    # ASSIGNMENT
    # ================================================================
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='assigned_assets'
    )
    assigned_to_department = models.CharField(max_length=50, blank=True)

    # The asset's owning department — distinct from assigned_to_department
    # (free text describing whoever currently holds it). Used to scope
    # assets to a department elsewhere (e.g. maintenance target-asset picker).
    department = models.CharField(max_length=30, choices=User.DEPARTMENT_CHOICES, blank=True)

    # ================================================================
    # STATUS & WORKFLOW (Enhanced)
    # ================================================================
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_STORE)
    status_updated_at = models.DateTimeField(null=True, blank=True)
    status_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='asset_status_updates'
    )
    
    # ================================================================
    # CONDITION (NEW)
    # ================================================================
    condition = models.CharField(
        max_length=20,
        choices=Condition.choices,
        default=Condition.GOOD
    )
    condition_notes = models.TextField(blank=True)

    # ================================================================
    # CHECK-IN/CHECK-OUT
    # ================================================================
    checked_out_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='checked_out_assets'
    )
    checked_out_at = models.DateTimeField(null=True, blank=True)
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assets_checked_out'
    )
    expected_return_date = models.DateField(null=True, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assets_returned'
    )
    
    # Return details
    return_reason = models.CharField(
        max_length=20,
        choices=ReturnReason.choices,
        null=True,
        blank=True
    )
    return_comment = models.TextField(blank=True)
    return_condition = models.CharField(
        max_length=50,
        blank=True,
        help_text="Condition of asset upon return"
    )

    # ================================================================
    # SCRAP WORKFLOW (Existing)
    # ================================================================
    scrap_approved = models.BooleanField(default=False)
    scrap_approved_at = models.DateTimeField(null=True, blank=True)
    scrap_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='approved_scraps'
    )
    scrap_reason = models.TextField(blank=True)

    # ================================================================
    # NOTES & TIMESTAMPS
    # ================================================================
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assets_created'
    )

    # Audit trail back to the vendor procurement request this asset was
    # received against, if any — set only at receiving time, never edited
    # afterward. Null for assets that were already in inventory / created
    # directly rather than procured through AssetProcurementRequest.
    procurement_request = models.ForeignKey(
        'AssetProcurementRequest',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_assets'
    )

    # ================================================================
    # PROPERTIES
    # ================================================================
    
    @property
    def is_checked_out(self):
        """Check if asset is currently checked out."""
        return self.checked_out_to is not None and self.returned_at is None

    @property
    def is_consumable(self):
        """True for bulk/consumable stock (cable ties, PPE) — a stock-count
        SKU rather than one individually-tracked physical unit."""
        return bool(self.category_id and self.category.is_consumable)

    @property
    def is_available(self):
        """Check if asset is available for checkout/mobilization. Consumable
        stock is available purely based on remaining count — its status
        stays IN_STORE throughout (the SKU record persists even when
        partially mobilized, only quantity_in_stock changes)."""
        if self.is_consumable:
            return self.quantity_in_stock > 0
        return self.status in [self.Status.IN_STORE, self.Status.READY] and self.checked_out_to_id is None

    @property
    def is_available_for_assignment(self):
        """Single source of truth for 'can this asset be handed to someone
        new' — via checkout, ticket fulfillment, or reassignment. Unlike
        is_available (checked_out_to only), this also requires assigned_to
        to be clear, since checkout/fulfillment/reassign used to mutate
        checked_out_to and assigned_to independently and could disagree
        about who currently has the asset. Individually-tracked assets only
        — consumables are stock-count SKUs, not something one person 'has'."""
        if self.is_consumable:
            return False
        return (
            self.status in [self.Status.IN_STORE, self.Status.READY]
            and self.checked_out_to_id is None
            and self.assigned_to_id is None
        )

    @property
    def can_reassign(self):
        """Reassign only makes sense when someone actually has the asset —
        gating it on 'status is IN_STORE/READY' too (like is_available_for_
        assignment does) would let Reassign silently double as a second
        Checkout for an asset nobody holds, which defeats the point of the
        two being separate actions."""
        if self.is_consumable:
            return False
        return self.checked_out_to_id is not None or self.assigned_to_id is not None

    @property
    def pending_scrap_requested_by(self):
        """The user who filed the currently-pending scrap request, or None.
        Valid exactly when status == DAMAGED, since that's the only status
        SCRAP_REQUESTED ever produces (checkin's condition-based DAMAGED/
        UNUSABLE routes to MAINTENANCE, not DAMAGED) — so the most recent
        SCRAP_REQUESTED log's actor is reliably the pending request's
        requester. Used for the scrap-approval self-approval guard."""
        if self.status != self.Status.DAMAGED:
            return None
        last_request = self.logs.filter(action=AssetLog.Action.SCRAP_REQUESTED).order_by('-created_at').first()
        return last_request.actor if last_request else None

    @property
    def assignment_blocked_reason(self):
        """Human-readable reason is_available_for_assignment is False, or
        None if it's actually available. Shared by assign_to()'s ValueError
        and the checkout-modal pre-check, so the two never drift apart."""
        if self.is_available_for_assignment:
            return None
        if self.is_consumable:
            return 'it is a consumable/stock item'
        if self.status not in [self.Status.IN_STORE, self.Status.READY]:
            # `status` has no choices= at the field level (a pre-existing
            # looseness elsewhere on this model), so there's no Django-
            # generated get_status_display() — use the model's own
            # status_display property instead.
            return f'it is currently {self.status_display["label"]}'
        return 'it is already assigned to someone'

    def assign_to(self, user, actor, expected_return_date=None, notes='', previous_holder_name=None):
        """Hand this asset to `user`. The single place that sets
        checked_out_to/assigned_to/status/AssetCheckoutHistory/AssetLog
        together — used by checkout, ticket fulfillment, and reassignment,
        so those three paths can no longer independently disagree about
        who currently has the asset (or hand out something that's damaged,
        retired, scrapped, or already assigned to someone else). Raises
        ValueError if the asset isn't available. `previous_holder_name`
        is purely for the AssetLog's 'from' field (get_reassignment_count()/
        get_assignment_history() key off it) — pass it from a reassign flow
        that knows who had the asset before release(); omit it for a plain
        checkout/fulfillment of an asset that had no prior holder."""
        reason = self.assignment_blocked_reason
        if reason:
            raise ValueError(f'"{self.name}" cannot be assigned — {reason}.')

        now = timezone.now()
        self.checked_out_to = user
        self.checked_out_at = now
        self.returned_at = None
        self.returned_by = None
        self.assigned_to = user
        self.status = self.Status.CHECKED_OUT
        self.status_updated_at = now
        self.status_updated_by = actor
        if expected_return_date:
            self.expected_return_date = expected_return_date
        self.save()

        AssetCheckoutHistory.objects.create(
            asset=self, checked_out_by=actor, checked_out_to=user,
            checked_out_at=now, expected_return_date=self.expected_return_date,
            notes=notes,
        )
        log_details = {'to': user.get_full_name(), 'notes': notes}
        if previous_holder_name is not None:
            log_details['from'] = previous_holder_name
        AssetLog.objects.create(
            asset=self, action=AssetLog.Action.ASSIGNED, actor=actor,
            details=log_details,
        )

        # Every handover notifies the recipient to confirm receipt — the
        # open AssetCheckoutHistory row's acknowledged_at stays null until
        # they Accept (or gets disputed_at instead if they Dispute).
        from apps.common.models import Notification
        from apps.common.utils import role_of
        Notification.objects.create(
            recipient=user, role=role_of(user),
            message=f'"{self.name}" ({self.tracking_id}) has been checked out to you — please confirm you received it.',
            url='/tickets/my-assets/',
        )

    def release(self, actor, return_reason=None, return_comment='', return_condition=''):
        """Take this asset back from whoever currently has it. The single
        place that clears checked_out_to/assigned_to, closes the open
        AssetCheckoutHistory row, and writes AssetLog — used by check-in and
        by reassignment away from a current holder. Status is decided from
        BOTH return_condition (DAMAGED/UNUSABLE -> MAINTENANCE) and
        return_reason (LOST/STOLEN -> that exact terminal status) — a lost
        or stolen asset no longer silently re-enters the available pool via
        a default/blank condition. Any other reason falls back to IN_STORE;
        reasons implying disposal/scrap intentionally do NOT bypass the
        separate scrap-approval workflow (asset_scrap_request/approve)."""
        previous_holder = self.checked_out_to or self.assigned_to
        now = timezone.now()

        self.return_reason = return_reason or self.return_reason
        self.return_comment = return_comment
        self.return_condition = return_condition
        self.returned_at = now
        self.checked_out_to = None
        self.assigned_to = None

        condition_upper = (return_condition or '').upper()
        if condition_upper in [self.Condition.DAMAGED, self.Condition.UNUSABLE]:
            self.status = self.Status.MAINTENANCE
        elif return_reason == self.ReturnReason.LOST:
            self.status = self.Status.LOST
        elif return_reason == self.ReturnReason.STOLEN:
            self.status = self.Status.STOLEN
        else:
            self.status = self.Status.IN_STORE
        self.status_updated_at = now
        self.status_updated_by = actor
        self.save()

        open_history = self.checkout_history.filter(checked_in_at__isnull=True).first()
        if open_history:
            open_history.checked_in_by = actor
            open_history.checked_in_at = now
            open_history.return_reason = return_reason
            open_history.return_comment = return_comment
            open_history.return_condition = return_condition
            open_history.save()

        AssetLog.objects.create(
            asset=self, action=AssetLog.Action.UNASSIGNED, actor=actor,
            details={
                'from': previous_holder.get_full_name() if previous_holder else 'Unassigned',
                'reason': self.get_return_reason_display() if self.return_reason else '',
                'condition': return_condition,
                'comment': return_comment,
            },
        )
        return previous_holder

    def _open_checkout_history(self):
        """The currently-open AssetCheckoutHistory row (checked_in_at is
        null), if any — the row every custody sub-state (acknowledged,
        disputed, return-requested) lives on."""
        return self.checkout_history.filter(checked_in_at__isnull=True).order_by('-checked_out_at').first()

    def acknowledge_checkout(self, actor):
        """The recipient confirms they actually received this asset (from
        a checkout or a reassignment handover). Raises ValueError if there's
        no open checkout for them to confirm."""
        history = self._open_checkout_history()
        if not history or history.checked_out_to_id != actor.id:
            raise ValueError('You have no pending checkout to confirm for this asset.')
        if history.acknowledged_at:
            raise ValueError('This checkout has already been confirmed.')
        history.acknowledged_at = timezone.now()
        history.acknowledged_by = actor
        history.save(update_fields=['acknowledged_at', 'acknowledged_by'])
        _notify_it_admins(
            f'{actor.get_full_name()} confirmed receipt of "{self.name}" ({self.tracking_id}).',
            f'/tickets/assets/{self.pk}/detail/',
        )

    def dispute_checkout(self, actor, reason=''):
        """The recipient says they did NOT actually receive this asset.
        Does not auto-revert custody — an admin resolves it manually via
        Reassign/Check-in once they've sorted out what actually happened."""
        history = self._open_checkout_history()
        if not history or history.checked_out_to_id != actor.id:
            raise ValueError('You have no pending checkout to dispute for this asset.')
        if history.acknowledged_at:
            raise ValueError('This checkout has already been confirmed.')
        history.disputed_at = timezone.now()
        history.dispute_reason = reason
        history.save(update_fields=['disputed_at', 'dispute_reason'])
        _notify_it_admins(
            f'{actor.get_full_name()} disputes receiving "{self.name}" ({self.tracking_id})'
            f'{": " + reason if reason else ""} — needs manual review.',
            f'/tickets/assets/{self.pk}/detail/',
        )

    def request_return(self, actor, reason, comment=''):
        """Holder self-initiates a return — does NOT change checked_out_to/
        assigned_to/status yet (the asset is still physically theirs until
        an admin retrieves it and confirms via release()). Just flags the
        open AssetCheckoutHistory row and notifies admins to arrange
        pickup. release()'s caller pre-fills from these fields but the
        admin's own return_condition assessment at confirm time is what
        actually decides the post-return status."""
        history = self._open_checkout_history()
        if not history or history.checked_out_to_id != actor.id:
            raise ValueError('You have no checked-out asset to return.')
        if history.return_requested_at:
            raise ValueError('A return has already been requested for this asset.')
        history.return_requested_at = timezone.now()
        history.return_requested_reason = reason
        history.return_requested_comment = comment
        history.save(update_fields=['return_requested_at', 'return_requested_reason', 'return_requested_comment'])
        _notify_it_admins(
            f'{actor.get_full_name()} requested to return "{self.name}" ({self.tracking_id}).',
            '/tickets/assets/pending-returns/',
        )

    def cancel_return_request(self, actor):
        """Withdraw a self-initiated return request before an admin has
        confirmed it — the escape hatch for 'I clicked that by mistake' or
        'actually I'll keep it a bit longer'."""
        history = self._open_checkout_history()
        if not history or history.checked_out_to_id != actor.id or not history.return_requested_at:
            raise ValueError('There is no pending return request for this asset.')
        history.return_requested_at = None
        history.return_requested_reason = None
        history.return_requested_comment = ''
        history.save(update_fields=['return_requested_at', 'return_requested_reason', 'return_requested_comment'])
        _notify_it_admins(
            f'{actor.get_full_name()} cancelled their return request for "{self.name}" ({self.tracking_id}).',
            f'/tickets/assets/{self.pk}/detail/',
        )

    @property
    def is_active(self):
        """Check if asset is actively in use."""
        return self.status in [self.Status.CHECKED_OUT, self.Status.IN_USE, self.Status.MOBILIZED]

    @property
    def is_low_stock(self):
        """True when a consumable's remaining count is at or below its
        configured reorder threshold. Always False for non-consumables or
        when no threshold is set."""
        return (
            self.is_consumable
            and self.low_stock_threshold is not None
            and self.quantity_in_stock <= self.low_stock_threshold
        )

    def refresh_low_stock_alert(self):
        """Call this after anything changes quantity_in_stock (mobilize,
        demobilize/restock, manual edit) — the single place that decides
        whether a low-stock notification is due, so the alert is correct
        regardless of which workflow moved the number. Notifies
        Admin/Superadmin once per dip below threshold; resets so a later
        dip notifies again once stock has recovered above it."""
        if not self.is_consumable or self.low_stock_threshold is None:
            return

        from django.db.models import Q
        from apps.common.models import Notification
        from apps.common.utils import role_of, notify_recipients_by_email
        from apps.common.permissions import effective_role_name
        from apps.accounts.models import User

        if self.quantity_in_stock <= self.low_stock_threshold:
            if not self.low_stock_notified:
                # Narrow via the legacy field or the roles M2M (either can
                # lag right after account creation), then resolve each
                # candidate's true active role in Python — a raw
                # role__in=[...] filter misses/wrongly-includes admins
                # whose active role has diverged from the legacy field.
                candidates = User.objects.filter(
                    Q(role__in=['ADMIN', 'SUPERADMIN']) | Q(roles__name__in=['ADMIN', 'SUPERADMIN']),
                    is_active=True,
                ).distinct()
                recipients = [u for u in candidates if effective_role_name(u) in ('ADMIN', 'SUPERADMIN')]
                message = (
                    f'Stock for "{self.name}" is low: {self.quantity_in_stock} left '
                    f'(threshold {self.low_stock_threshold}).'
                )
                url = f'/tickets/assets/{self.pk}/detail/'
                for recipient in recipients:
                    Notification.objects.create(
                        recipient=recipient,
                        role=role_of(recipient),
                        message=message,
                        url=url,
                        type=Notification.Type.GENERAL,
                    )
                # Email is a supplementary channel alongside the in-app/push
                # Notification above — push requires a subscribed device,
                # so a stock-out can otherwise go unnoticed until someone
                # next opens the app.
                notify_recipients_by_email(recipients, f'Low stock: {self.name}', message, url)
                self.low_stock_notified = True
                self.save(update_fields=['low_stock_notified'])
        elif self.low_stock_notified:
            self.low_stock_notified = False
            self.save(update_fields=['low_stock_notified'])

    def adjust_stock(self, new_quantity, reason, actor):
        """Audited correction of quantity_in_stock for a consumable —
        the single place a manual stock correction (stocktake, shrinkage,
        breakage found in storage) should go through, instead of silently
        overwriting the number via the general Edit Asset form. Records
        the old/new quantity and the reason on an AssetLog entry, and
        re-checks the low-stock alert like every other quantity-changing
        action does."""
        if not self.is_consumable:
            raise ValueError('Stock can only be adjusted for consumable assets.')
        new_quantity = max(0, int(new_quantity))
        old_quantity = self.quantity_in_stock
        if new_quantity == old_quantity:
            return
        self.quantity_in_stock = new_quantity
        self.save(update_fields=['quantity_in_stock'])
        self.refresh_low_stock_alert()

        AssetLog.objects.create(
            asset=self,
            action=AssetLog.Action.STOCK_ADJUSTED,
            actor=actor,
            details={
                'old_quantity': old_quantity,
                'new_quantity': new_quantity,
                'delta': new_quantity - old_quantity,
                'reason': reason,
            },
        )

    @property
    def is_renewable(self):
        """True when this asset's category tracks recurring renewal dates
        (software licenses, subscriptions, support contracts)."""
        return bool(self.category_id and self.category.is_renewable)

    @property
    def is_renewal_due_soon(self):
        """True when a renewable asset's next renewal is within 30 days —
        including already overdue."""
        return (
            self.is_renewable
            and self.next_renewal_date is not None
            and self.next_renewal_date <= timezone.now().date() + datetime.timedelta(days=30)
        )

    def mark_renewed(self, actor, new_cost=None):
        """Record that this renewal was actually paid/actioned — advances
        next_renewal_date forward by renewal_interval_months, resets the
        reminder flags so the next cycle can notify again, and logs an
        audit-trail AssetLog entry."""
        if not self.is_renewable or not self.renewal_interval_months:
            return

        today = timezone.now().date()
        base_date = self.next_renewal_date if self.next_renewal_date and self.next_renewal_date > today else today
        self.next_renewal_date = _add_months(base_date, self.renewal_interval_months)
        if new_cost is not None:
            self.renewal_cost = new_cost
        self.renewal_reminder_90d_sent = False
        self.renewal_reminder_30d_sent = False
        self.renewal_reminder_7d_sent = False
        self.renewal_reminder_overdue_last_sent = None
        self.save(update_fields=[
            'next_renewal_date', 'renewal_cost',
            'renewal_reminder_90d_sent', 'renewal_reminder_30d_sent', 'renewal_reminder_7d_sent',
            'renewal_reminder_overdue_last_sent',
        ])

        AssetLog.objects.create(
            asset=self,
            action=AssetLog.Action.RENEWED,
            actor=actor,
            details={
                'renewed_until': self.next_renewal_date.isoformat(),
                'cost': str(self.renewal_cost) if self.renewal_cost is not None else None,
            }
        )

    @property
    def is_mobilized(self):
        """Check if asset is currently mobilized to a job/vessel/dive system."""
        return self.status == self.Status.MOBILIZED
    
    @property
    def is_end_of_life(self):
        """Check if asset is at end of life."""
        return self.status in [
            self.Status.RETIRED, self.Status.SCRAPPED, 
            self.Status.LOST, self.Status.STOLEN, self.Status.DISPOSED
        ]
    
    @property
    def checkout_duration(self):
        """Get the duration of the current checkout."""
        if self.checked_out_at and self.returned_at:
            return self.returned_at - self.checked_out_at
        if self.checked_out_at:
            return timezone.now() - self.checked_out_at
        return None
    
    @property
    def days_checked_out(self):
        """Get number of days checked out."""
        duration = self.checkout_duration
        if duration:
            return duration.days
        return 0
    
    @property
    def is_overdue(self):
        """Check if asset is overdue."""
        if self.expected_return_date and self.is_checked_out:
            return timezone.now().date() > self.expected_return_date
        return False
    
    @property
    def warranty_status(self):
        """Get warranty status (Valid, Expiring Soon, Expired)."""
        if not self.warranty_expiry:
            return 'UNKNOWN'
        
        today = timezone.now().date()
        if self.warranty_expiry < today:
            return 'EXPIRED'
        elif (self.warranty_expiry - today).days <= 30:
            return 'EXPIRING_SOON'
        return 'VALID'
    
    @property
    def status_display(self):
        """Get status with color indicator for UI. `color` values must match
        one of the real `.status-chip-{color}` CSS classes in theme.css
        (success/warning/info/danger/neutral/accent) — there is no
        'primary' variant, unlike some other status-chip usages in this
        app."""
        colors = {
            'REQUESTED': 'info',
            'APPROVED': 'info',
            'ORDERED': 'info',
            'RECEIVED': 'success',
            'IN_STORE': 'success',
            'READY': 'success',
            'CHECKED_OUT': 'warning',
            'IN_USE': 'accent',
            'MOBILIZED': 'accent',
            'MAINTENANCE': 'warning',
            'REPAIR': 'danger',
            'RETURNED': 'success',
            'RETIRED': 'neutral',
            'SCRAPPED': 'neutral',
            'LOST': 'danger',
            'STOLEN': 'danger',
            'DISPOSED': 'neutral',
        }
        # `status` has no choices= at the field level, so Django never
        # generates get_status_display() for it — resolve the label from
        # the Status enum's own choices instead. (This property was
        # previously unused anywhere, which is how that AttributeError
        # went unnoticed.)
        return {
            'label': dict(self.Status.choices).get(self.status, self.status),
            'color': colors.get(self.status, 'neutral')
        }

    # ================================================================
    # EXISTING METHODS
    # ================================================================
    
    def get_reassignment_count(self):
        # Deliberately not cached on the instance: this asset can be
        # reassigned (new AssetLog rows created) via a separate query/request
        # while this Python object is still alive — e.g. immediately after a
        # reassign POST in the same view, or across a refresh_from_db(),
        # which only reloads field values and would leave a cached count
        # stale.
        #
        # An ASSIGNED log only counts as a *re*assignment if it recorded a
        # real previous holder in details['from']. Assets created with
        # assigned_to already set get no log at all (see asset_reassign()),
        # so the first ASSIGNED log for such an asset is a genuine handover,
        # not an "initial assignment" — counting "all ASSIGNED logs minus
        # one" assumed a baseline log that doesn't actually exist and
        # undercounted the very first real reassignment.
        assigned_logs = self.logs.filter(action=AssetLog.Action.ASSIGNED)
        return sum(
            1 for log in assigned_logs
            if (log.details or {}).get('from') and log.details['from'] != 'Unassigned'
        )

    def has_been_reassigned(self):
        return self.get_reassignment_count() > 0

    def get_first_assignment(self):
        first_log = self.logs.filter(
            action=AssetLog.Action.ASSIGNED
        ).order_by('created_at').first()
        if first_log and first_log.details:
            return first_log.details.get('to')
        return None

    def get_assignment_history(self):
        history = []
        logs = self.logs.filter(
            action__in=[AssetLog.Action.ASSIGNED, AssetLog.Action.UNASSIGNED]
        ).order_by('created_at')
        for log in logs:
            details = log.details or {}
            history.append({
                'from_user': details.get('from'),
                'to_user': details.get('to'),
                'timestamp': log.created_at,
                'actor': log.actor.get_full_name() if log.actor else 'System',
                'action': log.action
            })
        return history

    def save(self, *args, **kwargs):
        # Auto-calculate warranty expiry
        if self.purchase_date and self.warranty_duration_years > 0:
            try:
                self.warranty_expiry = self.purchase_date.replace(
                    year=self.purchase_date.year + self.warranty_duration_years
                )
            except ValueError:
                # Handle Feb 29 edge case
                from datetime import timedelta
                self.warranty_expiry = self.purchase_date + timedelta(days=365 * self.warranty_duration_years)

        # Update status_updated_at if status changed
        if self.pk:
            try:
                old = Asset.objects.get(pk=self.pk)
                if old.status != self.status:
                    self.status_updated_at = timezone.now()
            except Asset.DoesNotExist:
                self.status_updated_at = timezone.now()
        else:
            self.status_updated_at = timezone.now()

        if self.tracking_id:
            super().save(*args, **kwargs)
            return

        # Auto-generate tracking ID, retrying on collision with a
        # concurrent create computing the same next number. Each attempt
        # runs in its own savepoint so a collision doesn't poison an
        # outer transaction the caller may be inside.
        from django.db import IntegrityError, transaction
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            year = timezone.now().year
            last_asset = Asset.objects.filter(tracking_id__startswith=f'AST-{year}').order_by('tracking_id').last()
            if last_asset:
                parts = last_asset.tracking_id.split('-')
                if len(parts) == 3:
                    try:
                        num = int(parts[2]) + 1
                    except ValueError:
                        num = 1
                else:
                    num = 1
            else:
                num = 1
            self.tracking_id = f'AST-{year}-{num:04d}'
            try:
                with transaction.atomic():
                    super().save(*args, **kwargs)
                return
            except IntegrityError:
                self.tracking_id = ''
                if attempt == max_attempts:
                    raise

    def __str__(self):
        status_icon = "🔴" if self.is_checked_out else "🟢"
        return f"{self.tracking_id} - {self.name} ({status_icon})"


# ==========================================================================
# ASSET CHECKOUT HISTORY (Updated with new fields)
# ==========================================================================

class AssetCheckoutHistory(models.Model):
    """Audit trail for asset check-in/check-out."""
    
    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name='checkout_history'
    )
    checked_out_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='checkouts_initiated'
    )
    checked_out_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='assets_received'
    )
    checked_out_at = models.DateTimeField()
    expected_return_date = models.DateField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='checkins_initiated'
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.CharField(
        max_length=20,
        choices=Asset.ReturnReason.choices,
        null=True,
        blank=True
    )
    return_comment = models.TextField(blank=True)
    return_condition = models.CharField(max_length=50, blank=True)
    return_condition_rating = models.CharField(
        max_length=20,
        choices=Asset.Condition.choices,
        null=True,
        blank=True
    )
    notes = models.TextField(blank=True)

    # ================================================================
    # TWO-STEP CONFIRMATION — the recipient confirms they actually got the
    # asset (acknowledged_at) or says they didn't (disputed_at); the holder
    # can self-initiate a return (return_requested_at) which the admin then
    # confirms via checked_in_at/checked_in_by above. All null = the plain
    # "just checked out, nothing pending" state.
    # ================================================================
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='asset_checkouts_acknowledged'
    )
    disputed_at = models.DateTimeField(null=True, blank=True)
    dispute_reason = models.TextField(blank=True)

    return_requested_at = models.DateTimeField(null=True, blank=True)
    return_requested_reason = models.CharField(
        max_length=20,
        choices=Asset.ReturnReason.choices,
        null=True,
        blank=True
    )
    return_requested_comment = models.TextField(blank=True)

    class Meta:
        ordering = ['-checked_out_at']
        verbose_name_plural = "Asset Checkout History"

    def __str__(self):
        return f"{self.asset.name} → {self.checked_out_to.get_full_name()} ({self.checked_out_at.date()})"

    @property
    def is_active(self):
        return self.checked_in_at is None


# ==========================================================================
# MOBILIZATION / DEMOBILIZATION
# ==========================================================================

class Mobilization(models.Model):
    """A batch of assets sent out together to a job, vessel, and/or dive
    system. Individual assets are demobilized (returned) independently via
    MobilizationItem, so a mobilization can be partially returned."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        COMPLETED = 'COMPLETED', 'Completed'

    job_number = models.ForeignKey(
        JobNumber, on_delete=models.PROTECT, null=True, blank=True,
        related_name='mobilizations'
    )
    vessels = models.ManyToManyField(Vessel, blank=True, related_name='mobilizations')
    dive_systems = models.ManyToManyField(DiveSystem, blank=True, related_name='mobilizations')
    ticket = models.ForeignKey(
        'Ticket', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='mobilizations'
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    mobilized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='mobilizations_initiated'
    )
    mobilized_at = models.DateTimeField(default=timezone.now)
    # Current/effective return date — mutable, extended via
    # mobilization_extend_date (see MobilizationDateExtension below).
    expected_return_date = models.DateField(null=True, blank=True)
    # Snapshotted once at creation, equal to expected_return_date at the
    # time; never touched again. Lets the detail page show "original vs
    # current" without walking the extension history.
    original_expected_return_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-mobilized_at']

    def __str__(self):
        return f"Mobilization #{self.pk} — {self.job_number or 'No job'} ({self.mobilized_at.date()})"

    @property
    def destination_display(self):
        parts = []
        if self.job_number_id:
            parts.append(f"Job {self.job_number.number}")
        vessel_names = list(self.vessels.values_list('name', flat=True))
        if vessel_names:
            parts.append(' & '.join(vessel_names))
        system_names = list(self.dive_systems.values_list('name', flat=True))
        if system_names:
            parts.append(' & '.join(system_names))
        return ' · '.join(parts) if parts else 'No destination set'

    def refresh_status(self):
        """Flip to COMPLETED once no active items remain, back to ACTIVE otherwise."""
        new_status = (
            self.Status.COMPLETED
            if not self.items.filter(demobilized_at__isnull=True).exists()
            else self.Status.ACTIVE
        )
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=['status'])


class MobilizationItem(models.Model):
    """A single asset within a Mobilization, demobilized independently.

    For individually-tracked assets, quantity is always 1 (enforced in the
    view, not user-editable) — this row still means "this exact physical
    asset is out." For consumable/bulk assets, quantity is the number of
    units taken out of that asset's stock count."""

    mobilization = models.ForeignKey(Mobilization, on_delete=models.CASCADE, related_name='items')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='mobilization_items')
    quantity = models.PositiveIntegerField(default=1)

    demobilized_at = models.DateTimeField(null=True, blank=True)
    demobilized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='demobilizations_initiated'
    )
    return_condition = models.CharField(
        max_length=20, choices=Asset.Condition.choices, null=True, blank=True
    )
    return_notes = models.TextField(blank=True)
    # For consumables: how many of `quantity` units were actually returned
    # to stock (supports partial returns of damaged/used stock). Defaults to
    # the full quantity when unset at demobilize time. Irrelevant for
    # individually-tracked assets (quantity is always 1 there anyway).
    return_quantity = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-mobilization__mobilized_at']

    def __str__(self):
        return f"{self.asset.tracking_id} — {self.mobilization.destination_display}"

    @property
    def is_active(self):
        return self.demobilized_at is None


class MobilizationDateExtension(models.Model):
    """Immutable record of a demobilization-date extension. The
    Mobilization's own expected_return_date is updated to `new_date` when
    this is created, but nothing is overwritten — each extension keeps its
    own from/to/who/why row, same "append-only history" shape as
    AssetCheckoutHistory."""

    mobilization = models.ForeignKey(Mobilization, on_delete=models.CASCADE, related_name='date_extensions')
    previous_date = models.DateField(null=True, blank=True)
    new_date = models.DateField()
    reason = models.TextField(blank=True)
    extended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='mobilization_extensions_made'
    )
    extended_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-extended_at']

    def __str__(self):
        return f"{self.mobilization} — extended to {self.new_date}"


# ==========================================================================
# VENDOR PROCUREMENT (assets not yet in inventory)
# ==========================================================================

class AssetProcurementRequest(models.Model):
    """Tracks that an item needed for a Service Request or a Mobilization
    isn't currently in inventory and is being sourced from a vendor.

    This does NOT place orders or manage purchase orders — the org's actual
    procurement system (an external PMS) does that. This is inventory
    bookkeeping only: a record of what's expected, and a Receiving step
    where it becomes a real, trackable Asset — at which point whatever
    originally needed it (the linked ticket or mobilization) is fulfilled
    automatically, the same as if it had been picked from existing stock.
    """

    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', 'Requested'
        ORDERED = 'ORDERED', 'Ordered'
        RECEIVED = 'RECEIVED', 'Received'
        CANCELLED = 'CANCELLED', 'Cancelled'

    item_name = models.CharField(max_length=255)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT, related_name='procurement_requests')
    quantity = models.PositiveIntegerField(default=1)
    vendor = models.ForeignKey(
        'maintenance.Vendor', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='procurement_requests'
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    expected_arrival_date = models.DateField(null=True, blank=True)

    # Free-text PO/request number from the org's separate Procurement
    # Management System (pms.hydrodive.com). No API integration exists yet —
    # this is a plain reference field so a future sync/webhook can populate
    # or reconcile against it without a schema change.
    external_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    # Where the received asset(s) should go, if anywhere — a standalone
    # restock request tied to nothing is valid, so both may be null, but
    # never both set at once (enforced below by a CheckConstraint).
    ticket = models.ForeignKey(
        'Ticket', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='procurement_requests'
    )
    mobilization = models.ForeignKey(
        'Mobilization', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='procurement_requests'
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='procurement_requests_made'
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='procurement_requests_received'
    )
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']
        constraints = [
            models.CheckConstraint(
                check=models.Q(ticket__isnull=True) | models.Q(mobilization__isnull=True),
                name='procurement_request_not_both_ticket_and_mobilization',
            ),
        ]

    def __str__(self):
        return f"{self.item_name} x{self.quantity} ({self.get_status_display()})"

    @property
    def is_open(self):
        return self.status in (self.Status.REQUESTED, self.Status.ORDERED)


# ==========================================================================
# ASSET MAINTENANCE LOG (NEW)
# ==========================================================================

class AssetMaintenanceLog(models.Model):
    """Log of maintenance activities for assets."""
    
    class Type(models.TextChoices):
        PREVENTIVE = 'PREVENTIVE', 'Preventive Maintenance'
        CORRECTIVE = 'CORRECTIVE', 'Corrective Maintenance'
        PREDICTIVE = 'PREDICTIVE', 'Predictive Maintenance'
        EMERGENCY = 'EMERGENCY', 'Emergency Repair'
        UPGRADE = 'UPGRADE', 'Upgrade'
        INSPECTION = 'INSPECTION', 'Inspection'
    
    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name='maintenance_logs'
    )
    maintenance_type = models.CharField(max_length=20, choices=Type.choices)
    title = models.CharField(max_length=200)
    description = models.TextField()
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='maintenance_performed'
    )
    performed_at = models.DateField()
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    parts_replaced = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-performed_at']
    
    def __str__(self):
        return f"{self.asset.name} - {self.get_maintenance_type_display()} ({self.performed_at})"


class AssetLog(models.Model):
    class Action(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        UPDATED = 'UPDATED', 'Updated'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        UNASSIGNED = 'UNASSIGNED', 'Unassigned'
        STATUS_CHANGED = 'STATUS_CHANGED', 'Status Changed'
        SCRAP_REQUESTED = 'SCRAP_REQUESTED', 'Scrap Requested'
        SCRAP_APPROVED = 'SCRAP_APPROVED', 'Scrap Approved'
        SCRAP_REJECTED = 'SCRAP_REJECTED', 'Scrap Rejected'
        MOBILIZED = 'MOBILIZED', 'Mobilized'
        DEMOBILIZED = 'DEMOBILIZED', 'Demobilized'
        RENEWED = 'RENEWED', 'Renewed'
        STOCK_ADJUSTED = 'STOCK_ADJUSTED', 'Stock Adjusted'

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} on {self.asset.tracking_id} by {self.actor}"


class AssetAttachment(models.Model):
    """Optional file attached to an asset — license agreements, renewal
    invoices, signed contracts, etc. Entirely free-form: nothing requires
    an asset to have one, and it isn't restricted to renewable assets.
    Mirrors Attachment (the ticket-attachment model) but simpler — plain
    download only, no LibreOffice preview conversion."""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='asset_attachments/%Y/%m/%d/', storage=raw_file_storage())
    filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.filename


class RemoteConnector(models.Model):
    name = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=False)
    instructions_for_requester = models.TextField(
        default="1. Open Quick Assist (search in Windows start menu).\n2. Click 'Get assistance'.\n3. Wait for the agent to provide a 6-digit code.\n4. Enter the code and allow screen sharing.\n5. The session will begin."
    )
    instructions_for_agent = models.TextField(
        default="1. Open Quick Assist.\n2. Click 'Help someone'.\n3. A 6-digit code appears – share it with the user.\n4. The code expires in about 10 minutes.\n5. Once the user enters the code, you will have control."
    )
    api_endpoint = models.CharField(max_length=200, blank=True)
    api_key = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class RemoteSession(models.Model):
    class Status(models.TextChoices):
        REQUESTED = 'REQUESTED', 'Requested'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        REJECTED = 'REJECTED', 'Rejected'
        STARTED = 'STARTED', 'Started'
        ENDED = 'ENDED', 'Ended'
        EXPIRED = 'EXPIRED', 'Expired'

    # Kept for any code still referencing the old plain-tuple name.
    STATUS_CHOICES = Status.choices

    ticket = models.ForeignKey('Ticket', on_delete=models.CASCADE, related_name='remote_sessions')
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='requested_remote_sessions')
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agent_remote_sessions')
    connector = models.ForeignKey(RemoteConnector, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    session_code = models.CharField(max_length=20, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Remote session for ticket {self.ticket.number} ({self.status})"

    @property
    def duration_display(self):
        """Elapsed time for a STARTED session (started_at to now), or the
        total for an ENDED one (started_at to ended_at) — used on the
        session card/detail so an active session's length is visible
        without opening the full record."""
        if not self.started_at:
            return None
        end = self.ended_at or timezone.now()
        total_seconds = int((end - self.started_at).total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes = remainder // 60
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"