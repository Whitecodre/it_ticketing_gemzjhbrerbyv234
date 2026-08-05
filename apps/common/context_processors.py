# apps/common/context_processors.py
from django.conf import settings
from django.utils import timezone

def vapid_keys(request):
    return {
        'VAPID_PUBLIC_KEY': settings.VAPID_PUBLIC_KEY,
        'VAPID_PRIVATE_KEY': settings.VAPID_PRIVATE_KEY,
        'VAPID_CLAIM_EMAIL': settings.VAPID_CLAIM_EMAIL,
    }

def impersonation_context(request):
    """Add impersonation data to context."""
    context = {
        'is_impersonating': False,
        'impersonation_target': None,
        'impersonation_reason': None,
        'impersonation_expires': None,
        'impersonation_original': None,
        'impersonation_expired': False,
    }

    # Prefer the data added by the middleware for the current request.
    if getattr(request, 'is_impersonating', False):
        data = getattr(request, 'impersonation_data', {})
        context['is_impersonating'] = True
        context['impersonation_target'] = data.get('target_user')
        context['impersonation_reason'] = data.get('reason')
        context['impersonation_expires'] = data.get('expires_at')
        context['impersonation_original'] = data.get('original_user')
        return context

    # Fallback: read the active impersonation data from the session.
    impersonate_data = request.session.get('impersonate')
    if impersonate_data:
        expires_at = impersonate_data.get('expires_at')
        try:
            if expires_at:
                expiry = timezone.datetime.fromisoformat(expires_at)
                if timezone.now() > expiry:
                    request.session.pop('impersonate', None)
                    return context
        except (TypeError, ValueError):
            pass

        context['is_impersonating'] = True
        context['impersonation_target'] = impersonate_data.get('target_user_email')
        context['impersonation_reason'] = impersonate_data.get('reason')
        context['impersonation_expires'] = expires_at
        context['impersonation_original'] = impersonate_data.get('original_user_email')

    return context

def client_settings(request):
    """Add client settings (logo, company name) to context."""
    from apps.accounts.models import ClientSettings
    
    try:
        settings = ClientSettings.objects.first()
        if settings:
            return {
                'client_settings': {
                    'company_name': settings.company_name,
                    'logo': settings.logo,
                    'logo_url': settings.logo.url if settings.logo else None,
                }
            }
    except:
        pass
    
    return {
        'client_settings': {
            'company_name': 'My Company',
            'logo': None,
            'logo_url': None,
        }
    }

def active_role_context(request):
    """
    Add active role information to template context for all authenticated users.
    This enables dynamic role-based UI switching.
    """
    context = {
        'active_role': None,
        'active_role_name': None,
        'active_role_display': None,
        'available_roles': [],
        'sidebar_template': None,
    }
    
    if request.user.is_authenticated:
        # Get active role
        active_role = request.user.get_active_role()
        context['active_role'] = active_role
        
        if active_role:
            context['active_role_name'] = active_role.name
            context['active_role_display'] = active_role.display_name
        
        # Get all available roles
        context['available_roles'] = request.user.roles.all().order_by('priority')
        
        # Determine sidebar template based on active role
        role_name = context['active_role_name']
        if role_name == 'SUPERADMIN':
            context['sidebar_template'] = 'partials/sidebar_superadmin.html'
        elif role_name == 'ADMIN':
            context['sidebar_template'] = 'partials/sidebar_admin.html'
        elif role_name == 'TEAM_LEAD':
            context['sidebar_template'] = 'partials/sidebar_team_lead.html'
        elif role_name == 'AGENT':
            context['sidebar_template'] = 'partials/sidebar_agent.html'
        else:
            context['sidebar_template'] = 'partials/sidebar_end_user.html'
    
    return context