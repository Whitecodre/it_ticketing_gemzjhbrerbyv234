from django.contrib import admin
from .models import FormDefinition, FormSubmission


@admin.register(FormDefinition)
class FormDefinitionAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'status', 'submission_count', 'created_at']
    list_filter = ['status']
    search_fields = ['title', 'description']
    readonly_fields = ['slug', 'created_at', 'updated_at', 'published_at']


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = ['form', 'submitted_by', 'submitted_at']
    list_filter = ['form']
    readonly_fields = ['form', 'submitted_by', 'data', 'submitted_at']