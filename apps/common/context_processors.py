# apps/common/context_processors.py
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

CLIENT_SETTINGS_CACHE_KEY = 'client_settings_context'
CLIENT_SETTINGS_CACHE_TTL = 300  # branding rarely changes; self-heals within 5 min of an edit

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

    def _parse_expiry(value):
        """The banner's `date:"H:i"` filter needs a real datetime, but this
        value comes off the session/middleware as a plain ISO string — so
        without parsing it here, the filter silently rendered nothing and
        the banner never showed an expiry time at all."""
        if not value:
            return None
        try:
            return timezone.datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    # Prefer the data added by the middleware for the current request.
    if getattr(request, 'is_impersonating', False):
        data = getattr(request, 'impersonation_data', {})
        context['is_impersonating'] = True
        context['impersonation_target'] = data.get('target_user')
        context['impersonation_reason'] = data.get('reason')
        context['impersonation_expires'] = _parse_expiry(data.get('expires_at'))
        context['impersonation_original'] = data.get('original_user')
        return context

    # Fallback: read the active impersonation data from the session. This
    # only runs for paths ImpersonationMiddleware skips (login/logout/
    # static/impersonate/*), so it needs the same real end-of-session
    # handling as the middleware — not just deleting the session flag,
    # which used to leave the admin fully authenticated as the target.
    impersonate_data = request.session.get('impersonate')
    if impersonate_data:
        expires_at = impersonate_data.get('expires_at')
        try:
            if expires_at:
                expiry = timezone.datetime.fromisoformat(expires_at)
                if timezone.now() > expiry:
                    from apps.accounts.views.impersonate import end_impersonation
                    end_impersonation(request, impersonate_data)
                    return context
        except (TypeError, ValueError):
            pass

        context['is_impersonating'] = True
        context['impersonation_target'] = impersonate_data.get('target_user_email')
        context['impersonation_reason'] = impersonate_data.get('reason')
        context['impersonation_expires'] = _parse_expiry(expires_at)
        context['impersonation_original'] = impersonate_data.get('original_user_email')

    return context

def client_settings(request):
    """Add client settings (logo, company name) to context.

    This runs on every request (global context processor), so the lookup
    is cached — branding is effectively static and doesn't warrant a DB
    query on every single page load. See ClientSettings' post_save signal
    for cache invalidation on edit.
    """
    cached = cache.get(CLIENT_SETTINGS_CACHE_KEY)
    if cached is not None:
        return {'client_settings': cached}

    from apps.accounts.models import ClientSettings

    try:
        obj = ClientSettings.objects.first()
        data = {
            'company_name': obj.company_name,
            'logo': obj.logo,
            'logo_url': obj.logo.url if obj.logo else None,
        } if obj else {
            'company_name': 'My Company',
            'logo': None,
            'logo_url': None,
        }
    except Exception:
        data = {
            'company_name': 'My Company',
            'logo': None,
            'logo_url': None,
        }

    cache.set(CLIENT_SETTINGS_CACHE_KEY, data, CLIENT_SETTINGS_CACHE_TTL)
    return {'client_settings': data}


def mobilization_pending(request):
    """Whether this user has ever had anything mobilized-and-acknowledged
    on one of their own tickets — drives the sidebar 'Demobilization'
    link's visibility. Deliberately NOT scoped to still-outstanding items:
    the link (and the history it leads to) stays up permanently once
    earned, so the requester always has a timestamped record of what
    they've returned to point to if their return is ever disputed."""
    if not request.user.is_authenticated:
        return {'has_mobilization_history': False}

    cache_key = f'mobilization_pending:{request.user.pk}'
    cached = cache.get(cache_key)
    if cached is not None:
        return {'has_mobilization_history': cached}

    from apps.tickets.models import MobilizationItem

    has_history = MobilizationItem.objects.filter(
        mobilization__ticket__requester=request.user,
        acknowledged_at__isnull=False,
    ).exists()

    # Monotonic (per the docstring above): once true it never reverts, so
    # cache that outcome indefinitely; otherwise recheck periodically since
    # a new acknowledgement can flip it to true at any time.
    cache.set(cache_key, has_history, None if has_history else 60)
    return {'has_mobilization_history': has_history}

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