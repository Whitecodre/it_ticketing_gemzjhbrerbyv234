from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class UserAdmin(BaseUserAdmin):
    ordering = ['email']
    inlines = (UserProfileInline,)

    list_display = ('email', 'first_name', 'last_name', 'department', 'role', 'is_staff', 'created_by')
    list_filter = ('role', 'is_staff', 'is_superuser', 'department')   # optional: filter by department

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

    # ----- RBAC protections -----
    def has_delete_permission(self, request, obj=None):
        if obj and obj.role == User.Role.SUPERADMIN:
            return request.user.role == User.Role.SUPERADMIN
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj and obj.role == User.Role.SUPERADMIN:
            return request.user.role == User.Role.SUPERADMIN
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by:
            obj.created_by = request.user if request.user.is_authenticated else None
        super().save_model(request, obj, form, change)


admin.site.register(User, UserAdmin)