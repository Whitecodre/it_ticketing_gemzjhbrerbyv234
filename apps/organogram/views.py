# apps/organogram/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET
from django.utils import timezone
from django.urls import reverse
import csv
import json

from apps.accounts.models import ClientSettings
from .models import SystemOrgConfig, OrgDraft, OrgApproval, OrgPublished, OrgAuditLog
from .forms import OrgDraftForm
from django.contrib.auth import get_user_model

User = get_user_model()
  

def get_sidebar_template(user):
    """Returns the correct sidebar partial based on user's active role."""
    mapping = {
        'END_USER': 'partials/sidebar_end_user.html',
        'AGENT': 'partials/sidebar_agent.html',
        'TEAM_LEAD': 'partials/sidebar_team_lead.html',
        'ADMIN': 'partials/sidebar_admin.html',
        'SUPERADMIN': 'partials/sidebar_superadmin.html',
    }
    active_role = user.get_active_role()
    role_name = active_role.name if active_role else user.role
    return mapping.get(role_name, 'partials/sidebar_end_user.html')


def is_admin(user):
    return user.role in ['ADMIN', 'SUPERADMIN']


def can_edit_org(user):
    return user.role in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']


# ================================================================
# SYSTEM ORGANOGRAM (Auto-generated)
# ================================================================

# apps/organogram/views.py

def build_system_tree(user, depth=0, max_depth=10, department=None, search_query=None):
    """Build hierarchical tree from user's subordinates with improved metadata."""
    if depth >= max_depth:
        return None
    
    # If search query, check if this user matches
    if search_query:
        search_lower = search_query.lower()
        name_match = search_lower in user.get_full_name().lower() or search_lower in user.email.lower()
        # If this user doesn't match and has no subordinates that match, skip
        if not name_match:
            # Check subordinates recursively before returning None
            subordinates = user.subordinates.filter(is_active=True)
            if department:
                subordinates = subordinates.filter(department=department)
            
            for sub in subordinates.order_by('first_name', 'last_name'):
                child_tree = build_system_tree(sub, depth + 1, max_depth, department, search_query)
                if child_tree:
                    # Found a match in subordinates - include this node
                    break
            else:
                return None
    
    subordinates = user.subordinates.filter(is_active=True)
    if department:
        subordinates = subordinates.filter(department=department)
    
    children = []
    for sub in subordinates.order_by('first_name', 'last_name'):
        child_tree = build_system_tree(sub, depth + 1, max_depth, department, search_query)
        if child_tree:
            children.append(child_tree)
    
    # Get department color
    color = '#64748B'
    try:
        config = SystemOrgConfig.objects.filter(department=user.department).first()
        if config:
            color = config.color
    except:
        pass
    
    return {
        'user': user,
        'children': children,
        'depth': depth,
        'has_children': len(children) > 0,
        'direct_report_count': user.subordinates.filter(is_active=True).count(),
        'department_color': color,
        'full_name': user.get_full_name() or user.email,
        'position': user.position or user.get_role_display(),
        'department_display': user.get_department_display(),
        'email': user.email,
        'avatar': user.avatar.url if user.avatar else None,
    }


def get_department_colors():
    """Get department color mapping."""
    colors = {}
    for choice in User.DEPARTMENT_CHOICES:
        colors[choice[0]] = '#64748B'
    
    for config in SystemOrgConfig.objects.filter(is_active=True):
        colors[config.department] = config.color
    
    return colors


# apps/organogram/views.py

@login_required
def system_org(request):
    """System organogram view - auto-generated from users with search."""
    
    user = request.user
    department = request.GET.get('department', '')
    search_query = request.GET.get('search', '').strip()
    
    # If no department selected, use user's department
    if not department and user.department:
        department = user.department
    
    roots = []
    
    if department:
        # Find top-level person for this department
        dept_users = User.objects.filter(
            department=department,
            is_active=True
        ).order_by('first_name')
        
        for dept_user in dept_users:
            if not dept_user.manager or dept_user.manager.department != department:
                tree = build_system_tree(dept_user, department=department, search_query=search_query)
                if tree:
                    roots.append(tree)
        
        if not roots and dept_users.exists():
            tree = build_system_tree(dept_users.first(), department=department, search_query=search_query)
            if tree:
                roots.append(tree)
    else:
        # Show all roots
        root_users = User.objects.filter(is_active=True, manager__isnull=True).order_by('first_name', 'last_name')
        for root in root_users:
            tree = build_system_tree(root, search_query=search_query)
            if tree:
                roots.append(tree)
    
     # Get IT stats
    it_dept_users = User.objects.filter(department='IT', is_active=True)
    it_dept_stats = {
        'total': it_dept_users.count(),
        'managers': it_dept_users.filter(role__in=['TEAM_LEAD', 'ADMIN']).count(),
        'agents': it_dept_users.filter(role='AGENT').count(),
        'end_users': it_dept_users.filter(role='END_USER').count(),
    }
    
    context = {
        'roots': roots,
        'department': department,
        'department_name': dict(User.DEPARTMENT_CHOICES).get(department, 'All') if department else 'All Departments',
        'department_choices': User.DEPARTMENT_CHOICES,
        'department_colors': get_department_colors(),
        'search_query': search_query,
        'it_dept_stats': it_dept_stats,
        'sidebar_template': get_sidebar_template(user),
        'user_role': user.role,
        'is_system': True,
    }

     # ================================================================
    # HTMX REQUEST: Return only the tree container
    # ================================================================
    if request.headers.get('HX-Request'):
        return render(request, 'organogram/partials/system_tree_container.html', context)
    
    return render(request, 'organogram/system.html', context)


# ================================================================
# ORGANIZATION ORGANOGRAM (Customizable)
# ================================================================

@login_required
def org_list(request):
    """Deprecated - Organization chart editing has been moved to DCC."""
    messages.warning(request, 'Organization chart editing is now handled by DCC.')
    return redirect('dashboard')


@login_required
def org_builder(request):
    """Deprecated - Organization chart editing has been moved to DCC."""
    messages.warning(request, 'Organization chart editing is now handled by DCC.')
    return redirect('dashboard')


@login_required
def org_preview(request, pk):
    """Preview organization organogram before publishing."""
    
    draft = get_object_or_404(OrgDraft, pk=pk)
    
    context = {
        'draft': draft,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'organogram/organization/preview.html', context)


@login_required
def org_view(request):
    """View the DCC-provided organization chart."""
    
    # Get the latest published version (from DCC upload)
    published = OrgPublished.objects.first()
    
    # Alternatively, if DCC provides via JSON file:
    # structure = load_dcc_structure()  # custom function
    
    context = {
        'published': published,
        'has_published': published is not None,
        'is_dcc_provided': True,
        'last_updated': published.published_at if published else None,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'organogram/organization/view.html', context)


@login_required
def org_approvals(request):
    """Deprecated - Organization chart editing has been moved to DCC."""
    messages.warning(request, 'Organization chart editing is now handled by DCC.')
    return redirect('dashboard')


@login_required
def org_publish_history(request):
    """Deprecated - Organization chart editing has been moved to DCC."""
    messages.warning(request, 'Organization chart editing is now handled by DCC.')
    return redirect('dashboard')

# apps/organogram/views.py - Add at the end

@login_required
def api_pending_count(request):
    """Return the count of pending approvals for the current admin."""
    
    if not is_admin(request.user):
        return HttpResponse('0')
    
    pending_count = OrgDraft.objects.filter(
        status=OrgDraft.Status.PENDING
    ).exclude(
        org_approval_records__user=request.user,
        org_approval_records__approved=True
    ).count()
    
    return HttpResponse(str(pending_count))