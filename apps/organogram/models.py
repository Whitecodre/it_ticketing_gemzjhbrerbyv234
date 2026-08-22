# apps/organogram/models.py
from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
import json

User = get_user_model()


# ================================================================
# SYSTEM ORGANOGRAM (Auto-generated from Users)
# ================================================================

class SystemOrgConfig(models.Model):
    """Configuration for system organogram display."""
    
    department = models.CharField(
        max_length=30,
        choices=User.DEPARTMENT_CHOICES,
        unique=True
    )
    color = models.CharField(max_length=7, default='#64748B')
    icon = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['display_order']
        verbose_name = 'System Org Config'
        verbose_name_plural = 'System Org Configs'
    
    def __str__(self):
        return f"{self.get_department_display()} - {self.color}"


# ================================================================
# ORGANIZATION ORGANOGRAM (Customizable with Approval)
# ================================================================

class OrgDraft(models.Model):
    """
    Draft version of the organization organogram.
    Editable by Admins/Team Leads, requires approval before publishing.
    """
    
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PENDING = 'PENDING', 'Pending Approval'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        PUBLISHED = 'PUBLISHED', 'Published'
        ARCHIVED = 'ARCHIVED', 'Archived'
    
    # Basic info
    name = models.CharField(max_length=100, default='Organization Structure')
    description = models.TextField(blank=True)
    department = models.CharField(
        max_length=30,
        choices=User.DEPARTMENT_CHOICES,
        blank=True,
        help_text="Department this org chart belongs to"
    )
    
    # The structure (JSON tree)
    structure = models.JSONField(default=dict, help_text="The org chart tree structure")
    
    # Status
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    
    # Versioning
    version = models.PositiveIntegerField(default=1)
    previous_version = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='next_versions'
    )
    change_summary = models.TextField(blank=True, help_text="Summary of changes made")
    
    # Metadata
    created_by = models.ForeignKey(
        User, 
        on_delete=models.PROTECT, 
        related_name='org_drafts_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Approval tracking
    approved_by = models.ManyToManyField(
        User, 
        through='OrgApproval', 
        related_name='org_approvals'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='org_rejections'
    )
    rejection_reason = models.TextField(blank=True)
    
    # Publish tracking
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='org_published'
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Organization Draft'
        verbose_name_plural = 'Organization Drafts'
    
    def __str__(self):
        return f"{self.name} v{self.version} ({self.get_status_display()})"
    
    def is_fully_approved(self):
        """Check if all admins have approved this draft."""
        admins = User.objects.filter(role__in=['ADMIN', 'SUPERADMIN'], is_active=True)
        if not admins.exists():
            return True
        approved_count = self.org_approval_records.filter(approved=True).count()
        return approved_count >= admins.count()
    
    def get_approval_status(self):
        """Get detailed approval status."""
        admins = User.objects.filter(role__in=['ADMIN', 'SUPERADMIN'], is_active=True)
        approvals = {}
        for admin in admins:
            approval = self.org_approval_records.filter(user=admin).first()
            approvals[admin.id] = {
                'user': admin,
                'approved': approval.approved if approval else False,
                'comment': approval.comment if approval else '',
                'updated_at': approval.updated_at if approval else None,
            }
        return {
            'total': len(admins),
            'approved': sum(1 for a in approvals.values() if a['approved']),
            'details': approvals
        }
    
    def can_edit(self, user):
        """Check if user can edit this draft."""
        if self.status in [self.Status.PENDING, self.Status.PUBLISHED, self.Status.ARCHIVED]:
            return False
        return user.role in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'] or user == self.created_by
    
    def can_approve(self, user):
        """Check if user can approve this draft."""
        if self.status != self.Status.PENDING:
            return False
        return user.role in ['ADMIN', 'SUPERADMIN']
    
    def get_node_count(self):
        """Count total nodes in the structure."""
        def count_nodes(node):
            if not node:
                return 0
            if isinstance(node, list):
                total = len(node)
                for child in node:
                    total += count_nodes(child.get('children', []))
                return total
            total = 1
            for child in node.get('children', []):
                total += count_nodes(child)
            return total
        return count_nodes(self.structure)


class OrgApproval(models.Model):
    """Approval record for organization organogram changes."""
    
    draft = models.ForeignKey(OrgDraft, on_delete=models.CASCADE, related_name='org_approval_records')
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='org_approval_records')
    approved = models.BooleanField(default=False)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['draft', 'user']
        verbose_name = 'Organization Approval'
        verbose_name_plural = 'Organization Approvals'
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.draft.name} - {'✅' if self.approved else '❌'}"


class OrgPublished(models.Model):
    """
    Published version of the organization organogram.
    Read-only, visible to all users.
    """
    
    draft = models.OneToOneField(OrgDraft, on_delete=models.PROTECT, null=True, blank=True, related_name='published_version')
    structure = models.JSONField(default=dict)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    version = models.PositiveIntegerField()
    department = models.CharField(max_length=30, choices=User.DEPARTMENT_CHOICES, blank=True)
    published_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='org_published_versions')
    
    class Meta:
        ordering = ['-published_at']
        verbose_name = 'Published Organization'
        verbose_name_plural = 'Published Organizations'
    
    def __str__(self):
        return f"{self.name} v{self.version} (Published {self.published_at.date()})"
    
    def get_node_count(self):
        def count_nodes(node):
            if not node:
                return 0
            if isinstance(node, list):
                total = len(node)
                for child in node:
                    total += count_nodes(child.get('children', []))
                return total
            total = 1
            for child in node.get('children', []):
                total += count_nodes(child)
            return total
        return count_nodes(self.structure)


class OrgAuditLog(models.Model):
    """Immutable audit log for all organogram actions."""
    
    class Action(models.TextChoices):
        DRAFT_CREATED = 'DRAFT_CREATED', 'Draft Created'
        DRAFT_UPDATED = 'DRAFT_UPDATED', 'Draft Updated'
        SUBMITTED = 'SUBMITTED', 'Submitted for Approval'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        PUBLISHED = 'PUBLISHED', 'Published'
        ARCHIVED = 'ARCHIVED', 'Archived'
        RESTRUCTURED = 'RESTRUCTURED', 'Restructured'
    
    draft = models.ForeignKey(OrgDraft, on_delete=models.CASCADE, related_name='audit_logs')
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='org_audit_logs')
    action = models.CharField(max_length=20, choices=Action.choices)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Organization Audit Log'
        verbose_name_plural = 'Organization Audit Logs'
    
    def __str__(self):
        return f"{self.get_action_display()} by {self.user.get_full_name()} at {self.created_at}"