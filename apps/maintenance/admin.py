# apps/maintenance/admin.py
from django.contrib import admin
from .models import MaintenanceSchedule, MaintenanceActivityLog


@admin.register(MaintenanceSchedule)
class MaintenanceScheduleAdmin(admin.ModelAdmin):
    list_display = ['title', 'department', 'scheduled_date', 'status', 'assigned_to', 'confirmed_by']
    list_filter = ['department', 'status', 'scheduled_date']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at', 'completed_at', 'confirmed_at']
    fieldsets = (
        ('Basic Info', {'fields': ('title', 'description', 'department')}),
        ('Schedule', {'fields': ('scheduled_date', 'start_time', 'end_time')}),
        ('Assignment', {'fields': ('assigned_to',)}),
        ('Status', {'fields': ('status',)}),
        ('Checklist', {'fields': ('checklist_items', 'completed_checklist')}),
        ('Confirmation', {'fields': ('confirmed_by', 'confirmed_at', 'confirmation_comment')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at', 'completed_at', 'email_sent', 'email_sent_at')}),
    )


@admin.register(MaintenanceActivityLog)
class MaintenanceActivityLogAdmin(admin.ModelAdmin):
    list_display = ['schedule', 'action', 'actor', 'created_at']
    list_filter = ['action']
    readonly_fields = ['schedule', 'action', 'actor', 'details', 'created_at']
    def has_add_permission(self, request):
        return False