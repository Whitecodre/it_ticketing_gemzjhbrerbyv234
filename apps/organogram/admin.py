# apps/organogram/admin.py
from django.contrib import admin
from .models import SystemOrgConfig


@admin.register(SystemOrgConfig)
class SystemOrgConfigAdmin(admin.ModelAdmin):
    list_display = ['department', 'color', 'icon', 'is_active', 'display_order']
    list_filter = ['is_active']
    list_editable = ['color', 'icon', 'is_active', 'display_order']
