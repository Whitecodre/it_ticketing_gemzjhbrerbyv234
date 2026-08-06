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

def build_system_tree(user, depth=0, max_depth=5, department=None):
    """Build hierarchical tree from user's subordinates."""
    if depth >= max_depth:
        return None
    
    subordinates = user.subordinates.filter(is_active=True)
    if department:
        subordinates = subordinates.filter(department=department)
    
    children = []
    for sub in subordinates.order_by('first_name', 'last_name'):
        child_tree = build_system_tree(sub, depth + 1, max_depth, department)
        if child_tree:
            children.append(child_tree)
    
    return {
        'user': user,
        'children': children,
        'depth': depth,
        'has_children': len(children) > 0
    }


def get_department_colors():
    """Get department color mapping."""
    colors = {}
    for choice in User.DEPARTMENT_CHOICES:
        colors[choice[0]] = '#64748B'
    
    for config in SystemOrgConfig.objects.filter(is_active=True):
        colors[config.department] = config.color
    
    return colors


@login_required
def system_org(request):
    """System organogram view - auto-generated from users."""
    
    user = request.user
    department = request.GET.get('department', '')
    
    # If no department selected, use user's department
    if not department and user.department:
        department = user.department
    
    if department:
        # Find top-level person for this department
        dept_users = User.objects.filter(
            department=department,
            is_active=True
        ).order_by('first_name')
        
        roots = []
        for dept_user in dept_users:
            if not dept_user.manager or dept_user.manager.department != department:
                tree = build_system_tree(dept_user, department=department)
                if tree:
                    roots.append(tree)
        
        if not roots and dept_users.exists():
            tree = build_system_tree(dept_users.first(), department=department)
            if tree:
                roots.append(tree)
    else:
        # Show all roots
        roots = []
        root_users = User.objects.filter(is_active=True, manager__isnull=True).order_by('first_name', 'last_name')
        for root in root_users:
            tree = build_system_tree(root)
            if tree:
                roots.append(tree)
    
    context = {
        'roots': roots,
        'department': department,
        'department_name': dict(User.DEPARTMENT_CHOICES).get(department, 'All') if department else 'All Departments',
        'department_choices': User.DEPARTMENT_CHOICES,
        'department_colors': get_department_colors(),
        'sidebar_template': get_sidebar_template(user),
        'user_role': user.role,
        'is_system': True,
    }
    
    return render(request, 'organogram/system.html', context)


# ================================================================
# ORGANIZATION ORGANOGRAM (Customizable)
# ================================================================

@login_required
def org_list(request):
    """List all organization organogram drafts."""
    
    if not can_edit_org(request.user):
        messages.warning(request, 'You do not have permission to manage organization organograms.')
        return redirect('dashboard')
    
    drafts = OrgDraft.objects.all().order_by('-created_at')
    
    # Get approval status for each draft
    for draft in drafts:
        draft.approval_status = draft.get_approval_status()
    
    context = {
        'drafts': drafts,
        'sidebar_template': get_sidebar_template(request.user),
        'user_role': request.user.role,
    }
    return render(request, 'organogram/organization/list.html', context)


@login_required
def org_builder(request, pk=None):
    """Build/edit organization organogram."""
    
    if not can_edit_org(request.user):
        messages.warning(request, 'You do not have permission to edit organization organograms.')
        return redirect('dashboard')
    
    draft = None
    is_new = False
    
    if pk:
        draft = get_object_or_404(OrgDraft, pk=pk)
        if not draft.can_edit(request.user):
            messages.warning(request, 'This draft cannot be edited in its current state.')
            return redirect('organogram:org_list')
    else:
        is_new = True
        draft = OrgDraft.objects.create(
            name='New Organization Structure',
            created_by=request.user,
            structure={'nodes': []},
            status=OrgDraft.Status.DRAFT
        )
        return redirect('organogram:org_builder', pk=draft.pk)
    
    # Check if user can approve (for showing approve buttons)
    can_approve = draft.can_approve(request.user)
    
    # Get approval status
    approval_status = draft.get_approval_status()
    
    context = {
        'draft': draft,
        'can_approve': can_approve,
        'can_publish': draft.status == OrgDraft.Status.APPROVED and request.user.role in ['ADMIN', 'SUPERADMIN'],
        'approval_status': approval_status,
        'sidebar_template': get_sidebar_template(request.user),
        'user_role': request.user.role,
        'is_edit': not is_new,
    }
    return render(request, 'organogram/organization/builder.html', context)


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
    """View the published organization organogram."""
    
    published = OrgPublished.objects.first()  # Get latest published version
    
    if not published:
        context = {
            'has_published': False,
            'sidebar_template': get_sidebar_template(request.user),
        }
        return render(request, 'organogram/organization/view.html', context)
    
    context = {
        'published': published,
        'has_published': True,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'organogram/organization/view.html', context)


@login_required
def org_approvals(request):
    """Approval dashboard for organization organograms."""
    
    if not is_admin(request.user):
        messages.warning(request, 'Only admins can view the approval dashboard.')
        return redirect('dashboard')
    
    pending_drafts = OrgDraft.objects.filter(
        status=OrgDraft.Status.PENDING
    ).order_by('-created_at')
    
    # Get approval status for each
    for draft in pending_drafts:
        draft.approval_status = draft.get_approval_status()
        draft.user_has_approved = draft.org_approval_records.filter(
            user=request.user, 
            approved=True
        ).exists()
    
    context = {
        'pending_drafts': pending_drafts,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'organogram/organization/approvals.html', context)


@login_required
def org_publish_history(request):
    """View history of published organization organograms."""
    
    if not can_edit_org(request.user):
        return redirect('dashboard')
    
    published_versions = OrgPublished.objects.all().order_by('-published_at')
    
    context = {
        'published_versions': published_versions,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'organogram/organization/history.html', context)

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