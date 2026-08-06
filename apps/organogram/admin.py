# apps/organogram/admin.py
from django.contrib import admin
from .models import (
    SystemOrgConfig,
    OrgDraft, 
    OrgApproval, 
    OrgPublished, 
    OrgAuditLog
)


@admin.register(SystemOrgConfig)
class SystemOrgConfigAdmin(admin.ModelAdmin):
    list_display = ['department', 'color', 'icon', 'is_active', 'display_order']
    list_filter = ['is_active']
    list_editable = ['color', 'icon', 'is_active', 'display_order']


@admin.register(OrgDraft)
class OrgDraftAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'status', 'department', 'created_by', 'created_at']
    list_filter = ['status', 'department']
    search_fields = ['name', 'description', 'change_summary']
    readonly_fields = ['created_at', 'updated_at', 'version']


@admin.register(OrgApproval)
class OrgApprovalAdmin(admin.ModelAdmin):
    list_display = ['draft', 'user', 'approved', 'created_at', 'updated_at']
    list_filter = ['approved']
    search_fields = ['comment']


@admin.register(OrgPublished)
class OrgPublishedAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'department', 'published_at', 'published_by']
    list_filter = ['department']
    readonly_fields = ['structure', 'name', 'description', 'version', 'published_at', 'published_by']


@admin.register(OrgAuditLog)
class OrgAuditLogAdmin(admin.ModelAdmin):
    list_display = ['draft', 'user', 'action', 'created_at']
    list_filter = ['action']
    readonly_fields = ['draft', 'user', 'action', 'details', 'created_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False