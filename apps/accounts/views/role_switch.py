from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.urls import reverse

@login_required
@require_POST
def switch_role(request):
    """
    Switch the user's active role.
    """
    role_name = request.POST.get('role')
    next_url = request.POST.get('next', 'dashboard')
    
    if not role_name:
        messages.error(request, 'No role selected.')
        return redirect(next_url)
    
    success = request.user.set_active_role(role_name)
    
    if success:
        request.session.modified = True
        messages.success(request, f'Switched to {request.user.get_active_role_display()} view.')
    else:
        messages.error(request, f'You do not have the {role_name} role.')
    
    return redirect(next_url)


@login_required
def get_current_role(request):
    """
    Returns the current active role for the user (AJAX).
    """
    active_role = request.user.get_active_role()
    all_roles = request.user.roles.all()
    
    return JsonResponse({
        'active_role': {
            'name': active_role.name if active_role else None,
            'display_name': active_role.display_name if active_role else None,
        },
        'available_roles': [
            {'name': r.name, 'display_name': r.display_name} 
            for r in all_roles
        ]
    })