# apps/maintenance/admin.py
from django.contrib import admin
from .models import (
    MaintenanceSchedule, MaintenanceActivityLog, MaintenanceChecklistTemplate,
    MaintenanceAssetConfirmation, Vendor,
)


class MaintenanceAssetConfirmationInline(admin.TabularInline):
    model = MaintenanceAssetConfirmation
    extra = 0
    readonly_fields = ['asset', 'status', 'confirmed_by', 'confirmed_at', 'notes', 'dispute_reason', 'technician_completed_at']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(MaintenanceSchedule)
class MaintenanceScheduleAdmin(admin.ModelAdmin):
    list_display = ['title', 'target_departments', 'scheduled_date', 'status', 'assigned_to']
    list_filter = ['status', 'scheduled_date']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at', 'completed_at', 'confirmed_at']
    filter_horizontal = ['additional_assignees', 'target_assets', 'vendors']
    inlines = [MaintenanceAssetConfirmationInline]
    fieldsets = (
        ('Basic Info', {'fields': ('title', 'description', 'departments')}),
        ('Schedule', {'fields': ('scheduled_date', 'start_time', 'end_time')}),
        ('Assignment', {'fields': ('assigned_to', 'additional_assignees')}),
        ('Target', {'fields': ('target_assets', 'facility_location', 'vendors')}),
        ('Status', {'fields': ('status',)}),
        ('Checklist', {'fields': ('checklist_items', 'completed_checklist')}),
        ('Confirmation (deprecated — see MaintenanceAssetConfirmation below)', {
            'fields': ('confirmed_by', 'confirmed_at', 'confirmation_comment'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {'fields': ('created_at', 'updated_at', 'completed_at', 'email_sent', 'email_sent_at')}),
    )

    @admin.display(description='Target Department(s)')
    def target_departments(self, obj):
        return obj.departments_display


@admin.register(MaintenanceChecklistTemplate)
class MaintenanceChecklistTemplateAdmin(admin.ModelAdmin):
    list_display = ['text', 'department', 'is_active', 'order']
    list_filter = ['department', 'is_active']
    search_fields = ['text']


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_person', 'phone', 'email', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'contact_person', 'email']


@admin.register(MaintenanceActivityLog)
class MaintenanceActivityLogAdmin(admin.ModelAdmin):
    list_display = ['schedule', 'action', 'actor', 'created_at']
    list_filter = ['action']
    readonly_fields = ['schedule', 'action', 'actor', 'details', 'created_at']
    def has_add_permission(self, request):
        return False


@admin.register(MaintenanceAssetConfirmation)
class MaintenanceAssetConfirmationAdmin(admin.ModelAdmin):
    list_display = ['schedule', 'asset', 'status', 'confirmed_by', 'confirmed_at']
    list_filter = ['status']
    search_fields = ['schedule__title', 'asset__name', 'asset__tracking_id']
    readonly_fields = ['schedule', 'asset', 'created_at', 'updated_at', 'technician_completed_at']

    def has_add_permission(self, request):
        return False