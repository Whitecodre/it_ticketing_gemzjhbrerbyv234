# apps/form_builder/models.py

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class FormDefinition(models.Model):
    """Main form definition - stores form structure as JSON."""
    
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PUBLISHED = 'PUBLISHED', 'Published'
        ARCHIVED = 'ARCHIVED', 'Archived'
    
    class FormType(models.TextChoices):
        SERVICE_REQUEST = 'SERVICE_REQUEST', 'Service Request'
        INCIDENT = 'INCIDENT', 'Incident'
        MOBILIZATION = 'MOBILIZATION', 'Job Mobilization'
        RETURN = 'RETURN', 'Job Return'
        SURVEY = 'SURVEY', 'Survey'
        INSPECTION = 'INSPECTION', 'Inspection'
        FEEDBACK = 'FEEDBACK', 'Feedback'
        OTHER = 'OTHER', 'Other'
    
    class TemplateType(models.TextChoices):
        BLANK = 'BLANK', 'Blank Form'
        CONTACT = 'CONTACT', 'Contact Form'
        INCIDENT_REPORT = 'INCIDENT_REPORT', 'Incident Report'
        JOB_MOBILIZATION = 'JOB_MOBILIZATION', 'Job Mobilization'
        EMPLOYEE_ONBOARDING = 'EMPLOYEE_ONBOARDING', 'Employee Onboarding'
        FEEDBACK = 'FEEDBACK', 'Feedback Form'
        SURVEY = 'SURVEY', 'Survey'
    
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    form_type = models.CharField(max_length=20, choices=FormType.choices, default=FormType.OTHER)
    template_type = models.CharField(max_length=30, choices=TemplateType.choices, default=TemplateType.BLANK)
    
    # The form schema (JSON)
    schema = models.JSONField(default=dict, help_text="Form field definitions")
    
    # Settings
    require_login = models.BooleanField(default=True)
    confirmation_message = models.TextField(blank=True, default="Thank you! Your submission has been received.")
    redirect_url = models.URLField(blank=True)
    
    # Submission settings
    max_submissions = models.PositiveIntegerField(default=0, help_text="0 = unlimited")
    submission_limit_per_user = models.PositiveIntegerField(default=0, help_text="0 = unlimited")
    
    # Design settings
    theme_color = models.CharField(max_length=7, default='#0D9488', help_text="Primary color for form")
    logo_enabled = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='forms_created')
    published_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
    
    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while FormDefinition.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        
        if self.status == self.Status.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        
        super().save(*args, **kwargs)
    
    @property
    def submission_count(self):
        return self.submissions.count()


class FormTemplate(models.Model):
    """Pre-built form templates."""
    
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=50, choices=FormDefinition.FormType.choices)
    schema = models.JSONField(default=dict, help_text="Template form schema")
    icon = models.CharField(max_length=50, default='📝')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.name


class FormSubmission(models.Model):
    """Stores submitted form data."""
    
    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name='submissions')
    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='form_submissions')
    data = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-submitted_at']
    
    def __str__(self):
        submitter = self.submitted_by.get_full_name() if self.submitted_by else 'Anonymous'
        return f"{self.form.title} - {submitter} ({self.submitted_at.date()})"
    
    def get_field_value(self, field_key):
        return self.data.get(field_key)