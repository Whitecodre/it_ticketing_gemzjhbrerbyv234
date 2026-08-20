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
from apps.common.permissions import is_admin, can_edit_org, get_sidebar_template
from .models import SystemOrgConfig, OrgDraft, OrgApproval, OrgPublished, OrgAuditLog
from .forms import OrgDraftForm
from django.contrib.auth import get_user_model

User = get_user_model()


# ================================================================
# SYSTEM ORGANOGRAM (Auto-generated)
# ================================================================

# apps/organogram/views.py

# Role tiers shown on the System Organogram, top to bottom. SUPERADMIN is
# intentionally excluded — it's a technical/system-level account, not a
# real org-chart position.
TIER_ROLES = [
    ('ADMIN', 'Admin'),
    ('TEAM_LEAD', 'Team Lead'),
    ('AGENT', 'Support Team'),
    ('END_USER', 'User'),
]


TIER_DISPLAY_LIMIT = 24


def _user_role_names(user):
    """All role names a user currently holds. Users with dual roles (the
    `roles` M2M) hold every one of those roles concurrently — the legacy
    `role` CharField only reflects whichever role is currently *active*
    (set_active_role() overwrites it), so it under-represents a dual-role
    user's other role(s) and can't be used alone for tier membership."""
    names = {r.name for r in user.roles.all()}
    if names:
        return names
    return {user.role}


def build_role_tiers(queryset):
    """Group a User queryset into the fixed role tiers for the org chart.

    A user appears in every tier matching a role they hold — a dual-role
    user (e.g. Team Lead + Support Team) shows up in both, regardless of
    which role they're currently logged in as.

    There's no data linking a specific Team Lead to specific Agents (or
    Agent to specific End Users) — `User.manager` exists but is never
    populated anywhere in the app — so each tier is rendered as one shared
    row rather than individually paired parent/child nodes.
    """
    users = list(queryset)
    tiers = []
    for role_key, role_label in TIER_ROLES:
        tier_users = sorted(
            (u for u in users if role_key in _user_role_names(u)),
            key=lambda u: (u.first_name, u.last_name),
        )
        tiers.append({
            'key': role_key,
            'label': role_label,
            'users': tier_users,
            'count': len(tier_users),
            'display_users': tier_users[:TIER_DISPLAY_LIMIT],
            'more_count': max(0, len(tier_users) - TIER_DISPLAY_LIMIT),
        })
    return tiers


def get_system_org_queryset(request):
    """Shared department/search filtering used by both the live chart and
    its print/export view, so exporting always matches what's on screen."""
    department = request.GET.get('department', '')
    search_query = request.GET.get('search', '').strip()

    # Only default to the user's own department on the initial page load
    # (no 'department' param at all). Once the filter dropdown has fired at
    # least once, an empty value means "All Departments" was picked
    # explicitly and must not be overridden.
    if 'department' not in request.GET and request.user.department:
        department = request.user.department

    qs = User.objects.filter(is_active=True).prefetch_related('roles')
    if department:
        qs = qs.filter(department=department)
    if search_query:
        qs = qs.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    return qs.order_by('first_name', 'last_name'), department, search_query


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
    """System organogram view - role tiers auto-generated from users, with department/search filters."""

    user = request.user
    qs, department, search_query = get_system_org_queryset(request)
    tiers = build_role_tiers(qs)
    has_results = any(tier['count'] for tier in tiers)

    # Get IT stats
    it_dept_users = User.objects.filter(department='IT', is_active=True)
    it_dept_stats = {
        'total': it_dept_users.count(),
        'managers': it_dept_users.filter(role__in=['TEAM_LEAD', 'ADMIN']).count(),
        'agents': it_dept_users.filter(role='AGENT').count(),
        'end_users': it_dept_users.filter(role='END_USER').count(),
    }

    context = {
        'tiers': tiers,
        'has_results': has_results,
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


@login_required
def system_org_print(request):
    """Standalone, print-friendly export of the System Organogram — mirrors
    whatever department/search filters are currently applied on screen."""

    qs, department, search_query = get_system_org_queryset(request)
    tiers = build_role_tiers(qs)
    has_results = any(tier['count'] for tier in tiers)

    context = {
        'tiers': tiers,
        'has_results': has_results,
        'department': department,
        'department_name': dict(User.DEPARTMENT_CHOICES).get(department, 'All') if department else 'All Departments',
        'department_colors': get_department_colors(),
        'search_query': search_query,
        'generated_at': timezone.now(),
        # When loaded inside the export preview modal's iframe, the modal
        # supplies its own Print/Close chrome — suppress this page's own.
        'embed': request.GET.get('embed') == '1',
    }
    return render(request, 'organogram/system_print.html', context)


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