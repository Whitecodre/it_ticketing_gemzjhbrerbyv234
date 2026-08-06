import datetime
from django.db import models
from django.conf import settings
from django.utils import timezone

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

        # Response
        if self.response_due_at:
            total_secs = (self.response_due_at - self.created_at).total_seconds()
        else:
            total_secs = sla.response_minutes * 60   # fallback: use SLA target
        if total_secs > 0:
            elapsed_secs = (now - self.created_at).total_seconds()
            pct = min(100, (elapsed_secs / total_secs) * 100)
            result['response_pct'] = round(pct, 1)
            if pct >= 100:
                result['response'] = 'breached'
            elif pct >= 75:
                result['response'] = 'warning'

        # Resolution
        if self.resolution_due_at:
            total_secs = (self.resolution_due_at - self.created_at).total_seconds()
        else:
            total_secs = sla.resolution_minutes * 60
        if total_secs > 0:
            elapsed_secs = (now - self.created_at).total_seconds()
            pct = min(100, (elapsed_secs / total_secs) * 100)
            result['resolution_pct'] = round(pct, 1)
            if pct >= 100:
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

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'queue']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['requester', 'created_at']),
            models.Index(fields=['number']),
            models.Index(fields=['status', 'is_asset_request']),
        ]

    def __str__(self):
        return f"{self.number} - {self.title}"

    def save(self, *args, **kwargs):
        # Compute priority based on impact x urgency
        if not self.priority:
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
    file = models.FileField(upload_to='attachments/%Y/%m/%d/')
    filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)
    hash = models.CharField(max_length=64, blank=True)

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


# ==========================================================================
# ASSET MODEL (UPDATED)
# ==========================================================================

class Asset(models.Model):
    # ================================================================
    # TYPES (Kept for backward compatibility)
    # ================================================================
    class AssetType(models.TextChoices):
        COMPUTER = 'COMPUTER', 'Computer'
        LAPTOP = 'LAPTOP', 'Laptop'
        SERVER = 'SERVER', 'Server'
        NETWORK = 'NETWORK', 'Network Device'
        PRINTER = 'PRINTER', 'Printer'
        SOFTWARE = 'SOFTWARE', 'Software License'
        OTHER = 'OTHER', 'Other'

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
        
        # Maintenance
        MAINTENANCE = 'MAINTENANCE', 'Maintenance'
        REPAIR = 'REPAIR', 'Repair'
        
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
    
    # Category (NEW - replaces need for asset_type hierarchy)
    category = models.ForeignKey(
        AssetCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='assets'
    )
    
    # Kept for backward compatibility
    asset_type = models.CharField(max_length=20, blank=True, default='')
    
    # Technical details
    serial_number = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    manufacturer = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True, default=Location.HQ)

    # ================================================================
    # FINANCIAL TRACKING (NEW)
    # ================================================================
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Purchase price in your local currency"
    )
    current_value = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Current depreciated value (auto-calculated)"
    )
    depreciation_years = models.PositiveIntegerField(
        default=3,
        help_text="Number of years over which this asset depreciates"
    )
    salvage_value = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Estimated value at end of useful life"
    )

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

    # ================================================================
    # STATUS & WORKFLOW (Enhanced)
    # ================================================================
    status = models.CharField(max_length=20, default=Status.IN_STORE)
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
    # MAINTENANCE (NEW)
    # ================================================================
    last_maintenance = models.DateField(null=True, blank=True)
    next_maintenance = models.DateField(null=True, blank=True)
    maintenance_interval_months = models.PositiveIntegerField(
        default=6,
        help_text="Months between scheduled maintenance"
    )
    maintenance_notes = models.TextField(blank=True)

    # ================================================================
    # SUPPLIER/PURCHASING (NEW)
    # ================================================================
    supplier = models.CharField(max_length=200, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True)
    po_number = models.CharField(max_length=100, blank=True)
    purchase_order = models.CharField(max_length=100, blank=True, help_text="Purchase Order number")

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

    # ================================================================
    # PROPERTIES
    # ================================================================
    
    @property
    def is_checked_out(self):
        """Check if asset is currently checked out."""
        return self.checked_out_to is not None and self.returned_at is None
    
    @property
    def is_available(self):
        """Check if asset is available for checkout."""
        return self.status in [self.Status.IN_STORE, self.Status.READY]
    
    @property
    def is_active(self):
        """Check if asset is actively in use."""
        return self.status in [self.Status.CHECKED_OUT, self.Status.IN_USE]
    
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
    def current_value_calculated(self):
        """Calculate current value using straight-line depreciation."""
        if not self.purchase_price or not self.purchase_date:
            return self.current_value
        
        years_old = (timezone.now().date() - self.purchase_date).days / 365.25
        if years_old >= self.depreciation_years:
            return self.salvage_value or 0
        
        depreciation_per_year = self.purchase_price / self.depreciation_years
        depreciation = depreciation_per_year * years_old
        value = max(0, self.purchase_price - depreciation)
        return value if value > 0 else self.salvage_value or 0
    
    @property
    def status_display(self):
        """Get status with color indicator for UI."""
        colors = {
            'REQUESTED': 'info',
            'APPROVED': 'info',
            'ORDERED': 'info',
            'RECEIVED': 'success',
            'IN_STORE': 'success',
            'READY': 'success',
            'CHECKED_OUT': 'warning',
            'IN_USE': 'primary',
            'MAINTENANCE': 'warning',
            'REPAIR': 'danger',
            'RETURNED': 'success',
            'RETIRED': 'neutral',
            'SCRAPPED': 'neutral',
            'LOST': 'danger',
            'STOLEN': 'danger',
            'DISPOSED': 'neutral',
        }
        return {
            'label': self.get_status_display(),
            'color': colors.get(self.status, 'neutral')
        }

    # ================================================================
    # EXISTING METHODS
    # ================================================================
    
    def get_reassignment_count(self):
        if hasattr(self, '_reassignment_count'):
            return self._reassignment_count
        assigned_logs = self.logs.filter(
            action=AssetLog.Action.ASSIGNED
        ).order_by('created_at')
        count = max(0, assigned_logs.count() - 1)
        self._reassignment_count = count
        return count

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
        # Auto-generate tracking ID
        if not self.tracking_id:
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
        
        # Auto-calculate current value
        if self.purchase_price:
            self.current_value = self.current_value_calculated
        
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
        
        super().save(*args, **kwargs)

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
    
    class Meta:
        ordering = ['-checked_out_at']
        verbose_name_plural = "Asset Checkout History"
    
    def __str__(self):
        return f"{self.asset.name} → {self.checked_out_to.get_full_name()} ({self.checked_out_at.date()})"
    
    @property
    def is_active(self):
        return self.checked_in_at is None


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

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} on {self.asset.tracking_id} by {self.actor}"


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
    STATUS_CHOICES = [
        ('REQUESTED', 'Requested'),
        ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
        ('STARTED', 'Started'),
        ('ENDED', 'Ended'),
        ('EXPIRED', 'Expired'),
    ]
    ticket = models.ForeignKey('Ticket', on_delete=models.CASCADE, related_name='remote_sessions')
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='requested_remote_sessions')
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='agent_remote_sessions')
    connector = models.ForeignKey(RemoteConnector, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='REQUESTED')
    session_code = models.CharField(max_length=20, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Remote session for ticket {self.ticket.number} ({self.status})"