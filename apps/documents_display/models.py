# apps/documents_display/models.py

import secrets

from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.text import slugify

User = get_user_model()


def generate_share_token():
    return secrets.token_urlsafe(32)


class DisplayCategory(models.Model):
    """Categories matching your WhatsApp list"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    icon = models.CharField(max_length=50, blank=True, help_text="Lucide icon name")
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'name']
        verbose_name_plural = "Display Categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class DisplayDocumentQuerySet(models.QuerySet):
    def not_deleted(self):
        return self.filter(is_deleted=False)

    def viewable_by(self, user):
        """Queryset of documents a user may view, filtered at the DB level."""
        qs = self.not_deleted()
        if user.is_superuser or user.role == User.Role.ADMIN:
            return qs
        return qs.filter(
            Q(visibility=DisplayDocument.Visibility.PUBLIC) |
            Q(editors=user) |
            Q(downloaders=user) |
            Q(department_access__department=user.department) |
            Q(shares__recipient=user, shares__revoked_at__isnull=True)
        ).distinct()


class DisplayDocument(models.Model):
    """Simplified document with inline viewer support"""

    class Visibility(models.TextChoices):
        PUBLIC = 'PUBLIC', 'Public (All Users)'
        RESTRICTED = 'RESTRICTED', 'Restricted (Specific Departments)'

    # Core fields
    title = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    category = models.ForeignKey(
        DisplayCategory,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    
    # File (required)
    file = models.FileField(
        upload_to='display_docs/%Y/%m/%d/',
        validators=[FileExtensionValidator(['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv', 'zip', 'png', 'jpg', 'jpeg', 'gif', 'webp'])]
    )
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    
    # Version tracking
    version = models.PositiveIntegerField(default=1)
    
    # Metadata
    document_date = models.DateField(null=True, blank=True)
    
    # Permissions
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='display_documents_created'
    )
    editors = models.ManyToManyField(
        User,
        blank=True,
        related_name='editable_documents',
        help_text="Per-user edit override, independent of department grants"
    )
    downloaders = models.ManyToManyField(
        User,
        blank=True,
        related_name='downloadable_documents',
        help_text="Per-user download override, independent of department grants"
    )

    # The converted preview document
    preview_pdf = models.FileField(
        upload_to='display_docs/previews/%Y/%m/%d/',
        blank=True,
        null=True,
        help_text="Automatically generated PDF preview for Office documents"
    )

    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
    # Only meaningful when visibility == PUBLIC. Read is unconditional for PUBLIC docs.
    public_can_edit = models.BooleanField(default=False)
    public_can_download = models.BooleanField(default=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Soft delete for audit
    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deleted_display_documents'
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = DisplayDocumentQuerySet.as_manager()

    class Meta:
        ordering = ['category__display_order', 'title']
        indexes = [
            models.Index(fields=['category', 'is_deleted']),
            models.Index(fields=['created_by', 'created_at']),
        ]

    def __str__(self):
        return f"{self.title} (v{self.version})"

    def save(self, *args, **kwargs):
        if not self.slug:
            import time
            self.slug = slugify(self.title) + '-' + str(int(time.time()))
        
        if self.file and not self.pk:
            self.file_name = self.file.name
            self.file_size = self.file.size
        
        super().save(*args, **kwargs)

    def _active_shares_for(self, user):
        """Shares for `user` that are neither revoked nor expired - the
        queryset equivalent of DocumentShare.is_active, since these permission
        checks filter at the DB level rather than iterating instances."""
        return self.shares.filter(recipient=user, revoked_at__isnull=True).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        )

    def is_viewable_by(self, user):
        """Check if a user can view (read) this document."""
        if self.is_deleted:
            return False
        if user.is_superuser or user.role == User.Role.ADMIN:
            return True
        if self.visibility == self.Visibility.PUBLIC:
            return True
        if self.editors.filter(pk=user.pk).exists() or self.downloaders.filter(pk=user.pk).exists():
            return True
        if self._active_shares_for(user).exists():
            return True
        return self.department_access.filter(department=user.department).exists()

    def is_editable_by(self, user):
        """Check if user can edit this document (rename, replace file, delete)"""
        if user.is_superuser or user.role == User.Role.ADMIN:
            return True
        if self.editors.filter(pk=user.pk).exists():
            return True
        if self.visibility == self.Visibility.PUBLIC and self.public_can_edit:
            return True
        if self._active_shares_for(user).filter(can_edit=True).exists():
            return True
        return self.department_access.filter(department=user.department, can_edit=True).exists()

    def is_downloadable_by(self, user):
        """Check if user can download this document's file."""
        if user.is_superuser or user.role == User.Role.ADMIN:
            return True
        if self.downloaders.filter(pk=user.pk).exists():
            return True
        if self.visibility == self.Visibility.PUBLIC and self.public_can_download:
            return True
        if self._active_shares_for(user).filter(can_download=True).exists():
            return True
        return self.department_access.filter(department=user.department, can_download=True).exists()

    @property
    def file_extension(self):
        """Get file extension without the dot"""
        if self.file_name:
            return self.file_name.split('.')[-1].lower()
        return ''
    
    @property
    def is_viewable_inline(self):
        """Check if file can be viewed inline"""
        viewable_extensions = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'txt', 'csv']
        return self.file_extension in viewable_extensions
    
    @property
    def is_office_file(self):
        """Check if file is an Office document (needs Google Docs viewer)"""
        office_extensions = ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx']
        return self.file_extension in office_extensions


class DocumentDepartmentAccess(models.Model):
    """Grants a department read access to a document, plus optional edit/download."""

    document = models.ForeignKey(
        DisplayDocument,
        on_delete=models.CASCADE,
        related_name='department_access'
    )
    department = models.CharField(max_length=30, choices=User.DEPARTMENT_CHOICES)
    can_edit = models.BooleanField(default=False)
    can_download = models.BooleanField(default=False)

    class Meta:
        unique_together = ('document', 'department')
        indexes = [models.Index(fields=['department'])]
        verbose_name_plural = "Document department access"

    def __str__(self):
        return f"{self.document.title} → {self.get_department_display()}"


class DocumentShare(models.Model):
    """Grants access to a document to either an in-system user (`recipient`)
    or an external email address (`external_email`) with no account,
    plus optional edit/download, independent of their department. Created
    by an Admin and delivered via an emailed link. Exactly one of
    recipient/external_email is ever set - see the exactly-one-target
    CheckConstraint below (also enforced in ShareDocumentForm.clean())."""

    document = models.ForeignKey(
        DisplayDocument,
        on_delete=models.CASCADE,
        related_name='shares'
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='document_shares',
        null=True,
        blank=True,
    )
    external_email = models.EmailField(
        null=True,
        blank=True,
        help_text="For sharing with someone outside the organization - no account required."
    )
    shared_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='shared_documents'
    )
    can_edit = models.BooleanField(default=False)
    can_download = models.BooleanField(default=False)
    token = models.CharField(max_length=64, unique=True, default=generate_share_token)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Optional. Required for external shares.")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True, help_text="First time the recipient opened the emailed link")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'recipient'],
                condition=models.Q(recipient__isnull=False),
                name='uniq_document_recipient_share',
            ),
            models.UniqueConstraint(
                fields=['document', 'external_email'],
                condition=models.Q(external_email__isnull=False),
                name='uniq_document_external_email_share',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(recipient__isnull=False, external_email__isnull=True) |
                    models.Q(recipient__isnull=True, external_email__isnull=False)
                ),
                name='document_share_exactly_one_target',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.document.title} → {self.display_target}"

    @property
    def display_target(self):
        """Null-safe display label for whichever kind of share this is -
        use this in templates instead of chaining `|default:` filters on
        `recipient`/`external_email` directly, since Django's template
        engine raises (rather than silently falling through) when a
        `default:` filter's argument itself dereferences an attribute on
        None."""
        if self.recipient:
            return self.recipient.get_full_name() or self.recipient.email
        return self.external_email

    @property
    def is_expired(self):
        return self.expires_at is not None and timezone.now() > self.expires_at

    @property
    def is_active(self):
        return self.revoked_at is None and not self.is_expired

    def revoke(self):
        self.revoked_at = timezone.now()
        self.save(update_fields=['revoked_at'])


class DisplayVersion(models.Model):
    """Version history for documents"""
    
    document = models.ForeignKey(
        DisplayDocument,
        on_delete=models.CASCADE,
        related_name='versions'
    )
    version_number = models.PositiveIntegerField()
    file = models.FileField(upload_to='display_docs/versions/%Y/%m/%d/', blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    comment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['document', 'version_number']

    def __str__(self):
        return f"{self.document.title} - v{self.version_number}"