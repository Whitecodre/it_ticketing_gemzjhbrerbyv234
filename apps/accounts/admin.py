# apps/accounts/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, UserProfile
from apps.common.permissions import effective_role_name

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False

class UserAdmin(BaseUserAdmin):
    ordering = ['email']
    inlines = (UserProfileInline,)

    list_display = ('email', 'first_name', 'last_name', 'department', 'role', 'is_staff', 'created_by')
    list_filter = ('role', 'is_staff', 'is_superuser', 'department')
    
    # SUPERADMIN is the vendor/support-only account — hidden from everyone
    # else in the admin changelist, mirroring the app's own user management UI.
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if effective_role_name(request.user) == User.Role.SUPERADMIN:
            return qs
        return qs.exclude(role=User.Role.SUPERADMIN)

    # Strip SUPERADMIN out of the role/roles/active_role form fields for
    # non-superadmin staff. Since Django validates submitted values against
    # these choices/querysets regardless of what was rendered, this also
    # blocks a forged POST from granting SUPERADMIN, not just hiding the option.
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        requesting_user = getattr(request, 'user', None)
        if requesting_user is None or effective_role_name(requesting_user) != User.Role.SUPERADMIN:
            if 'role' in form.base_fields:
                form.base_fields['role'].choices = [
                    choice for choice in form.base_fields['role'].choices
                    if choice[0] != User.Role.SUPERADMIN
                ]
            if 'roles' in form.base_fields:
                form.base_fields['roles'].queryset = form.base_fields['roles'].queryset.exclude(name='SUPERADMIN')
            if 'active_role' in form.base_fields:
                form.base_fields['active_role'].queryset = form.base_fields['active_role'].queryset.exclude(name='SUPERADMIN')
        return form

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'department')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Roles', {
            'fields': ('role', 'roles', 'active_role'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
        ('Extra Info', {'fields': ('avatar', 'created_by')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'department', 'role', 'roles', 'active_role',
                       'password1', 'password2', 'created_by'),
        }),
    )

    def has_delete_permission(self, request, obj=None):
        if obj and obj.roles.filter(name=User.Role.SUPERADMIN).exists():
            return effective_role_name(request.user) == User.Role.SUPERADMIN
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.roles.filter(name=User.Role.SUPERADMIN).exists():
            return effective_role_name(request.user) == User.Role.SUPERADMIN
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by:
            obj.created_by = request.user if request.user.is_authenticated else None
        super().save_model(request, obj, form, change)

admin.site.register(User, UserAdmin)