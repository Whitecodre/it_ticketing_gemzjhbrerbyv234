# apps/documents_display/admin.py

from django.contrib import admin
from .models import DisplayCategory, DisplayDocument, DisplayVersion, DocumentDepartmentAccess, DocumentShare


class DisplayVersionInline(admin.TabularInline):
    model = DisplayVersion
    extra = 0
    readonly_fields = ['version_number', 'created_by', 'created_at']


class DocumentDepartmentAccessInline(admin.TabularInline):
    model = DocumentDepartmentAccess
    extra = 0


@admin.register(DisplayCategory)
class DisplayCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'icon', 'display_order', 'is_active']
    list_filter = ['is_active']
    prepopulated_fields = {'slug': ('name',)}
    list_editable = ['display_order', 'is_active']


@admin.register(DisplayDocument)
class DisplayDocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'version', 'created_by', 'created_at']
    list_filter = ['category', 'is_deleted', 'visibility']
    search_fields = ['title', 'file_name']  # Removed 'content'
    readonly_fields = ['version', 'slug', 'created_at', 'updated_at']
    inlines = [DocumentDepartmentAccessInline, DisplayVersionInline]
    filter_horizontal = ['editors', 'downloaders']


@admin.register(DocumentShare)
class DocumentShareAdmin(admin.ModelAdmin):
    list_display = ['document', 'recipient', 'shared_by', 'can_edit', 'can_download', 'created_at', 'accepted_at', 'revoked_at']
    list_filter = ['can_edit', 'can_download']
    search_fields = ['document__title', 'recipient__email']
    readonly_fields = ['token', 'created_at', 'accepted_at']
    autocomplete_fields = ['document', 'recipient', 'shared_by']


@admin.register(DisplayVersion)
class DisplayVersionAdmin(admin.ModelAdmin):
    list_display = ['document', 'version_number', 'created_by', 'created_at']
    readonly_fields = ['document', 'version_number', 'created_by', 'created_at']  # Removed 'content'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False