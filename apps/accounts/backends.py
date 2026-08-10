# apps/accounts/backends.py

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get('email') or username
        if email is None:
            return None

        email = email.strip()
        if password:
            password = password.strip()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return None
        if user.check_password(password):
            return user
        return None

    def _get_effective_role_name(self, user_obj):
        active_role = user_obj.get_active_role()
        if active_role:
            return active_role.name
        if user_obj.roles.exists():
            highest_role = user_obj.get_highest_role()
            return highest_role.name if highest_role else None
        return user_obj.role
    
    def _is_support_user(self, user_obj):
        """Check if user is in IT department with a support role."""
        if user_obj.department != 'IT':
            return False
        role_name = self._get_effective_role_name(user_obj)
        return role_name in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    
    def has_perm(self, user_obj, perm, obj=None):
        """Check if user has permission based on the active role when available."""
        if not user_obj.is_authenticated:
            return False

        # Superadmin bypasses all checks
        if user_obj.role == 'SUPERADMIN':
            return True

        role_name = self._get_effective_role_name(user_obj)
        
        # Support permissions only available to IT department
        support_perms = [
            'can_manage_users', 'can_manage_sla', 'can_impersonate',
            'can_reassign_ticket', 'can_claim_tickets', 'can_view_reports',
            'can_manage_assets', 'can_approve_requests', 'can_export_data'
        ]
        
        if perm in support_perms:
            # Only IT department users can have support permissions
            if user_obj.department != 'IT':
                return False
        
        # Superadmin has all permissions
        if role_name == 'SUPERADMIN':
            return True
        
        # Check specific permissions based on roles
        if perm == 'can_manage_users':
            return role_name in ['ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_manage_sla':
            return role_name in ['ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_impersonate':
            return role_name in ['ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_reassign_ticket':
            return role_name in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_claim_tickets':
            return role_name in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_view_reports':
            return role_name in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_manage_assets':
            return role_name in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_approve_requests':
            return role_name in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        if perm == 'can_export_data':
            return role_name in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] and user_obj.department == 'IT'
        
        # Default: user has permission if they have any role that isn't END_USER
        # AND they are in IT department for support roles
        if role_name not in [None, 'END_USER']:
            # For END_USER, no special permissions
            return False
        
        return False