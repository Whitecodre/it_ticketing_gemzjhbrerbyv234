# apps/organogram/api_views.py
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone
import json

from .models import OrgDraft, OrgApproval, OrgPublished, OrgAuditLog
from apps.common.permissions import is_admin, can_edit_org
from django.contrib.auth import get_user_model

User = get_user_model()


@login_required
@require_POST
def api_save_structure(request):
    """Save the structure of a draft."""
    
    if not can_edit_org(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    try:
        data = json.loads(request.body)
        draft_id = data.get('draft_id')
        structure = data.get('structure', {})
        
        draft = get_object_or_404(OrgDraft, pk=draft_id)
        
        if not draft.can_edit(request.user):
            return JsonResponse({'success': False, 'error': 'Cannot edit this draft'})
        
        draft.structure = structure
        draft.save()
        
        # Audit log
        OrgAuditLog.objects.create(
            draft=draft,
            user=request.user,
            action=OrgAuditLog.Action.DRAFT_UPDATED,
            details={'structure_updated': True}
        )
        
        return JsonResponse({'success': True, 'message': 'Structure saved'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_POST
def api_submit_approval(request):
    """Submit a draft for approval."""
    
    if not can_edit_org(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    draft_id = request.POST.get('draft_id')
    draft = get_object_or_404(OrgDraft, pk=draft_id)
    
    if draft.status != OrgDraft.Status.DRAFT:
        return JsonResponse({'success': False, 'error': 'Only drafts can be submitted'})
    
    if not draft.structure or not draft.structure.get('nodes'):
        return JsonResponse({'success': False, 'error': 'Cannot submit empty structure'})
    
    draft.status = OrgDraft.Status.PENDING
    draft.save()
    
    # Audit log
    OrgAuditLog.objects.create(
        draft=draft,
        user=request.user,
        action=OrgAuditLog.Action.SUBMITTED,
        details={'submitted_by': request.user.get_full_name()}
    )
    
    # Notify admins (you can add email notifications here)
    
    return JsonResponse({'success': True, 'message': 'Submitted for approval'})


@login_required
@require_POST
def api_approve(request):
    """Approve or reject a draft."""
    
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'error': 'Only admins can approve'})
    
    draft_id = request.POST.get('draft_id')
    approved = request.POST.get('approved') == 'true'
    reason = request.POST.get('reason', '').strip()
    
    draft = get_object_or_404(OrgDraft, pk=draft_id)
    
    if draft.status != OrgDraft.Status.PENDING:
        return JsonResponse({'success': False, 'error': 'Only pending drafts can be approved'})
    
    # Check if user already approved
    existing_approval = draft.org_approval_records.filter(user=request.user).first()
    
    if existing_approval:
        existing_approval.approved = approved
        existing_approval.comment = reason
        existing_approval.save()
    else:
        OrgApproval.objects.create(
            draft=draft,
            user=request.user,
            approved=approved,
            comment=reason
        )
    
    # Audit log
    action = OrgAuditLog.Action.APPROVED if approved else OrgAuditLog.Action.REJECTED
    OrgAuditLog.objects.create(
        draft=draft,
        user=request.user,
        action=action,
        details={'comment': reason}
    )
    
    # Check if fully approved
    if approved and draft.is_fully_approved():
        draft.status = OrgDraft.Status.APPROVED
        draft.approved_at = timezone.now()
        draft.save()
        
        # Audit log for full approval
        OrgAuditLog.objects.create(
            draft=draft,
            user=request.user,
            action=OrgAuditLog.Action.APPROVED,
            details={'fully_approved': True}
        )
        
        return JsonResponse({'success': True, 'message': 'Draft fully approved! Ready to publish.'})
    
    if not approved:
        draft.status = OrgDraft.Status.REJECTED
        draft.rejected_at = timezone.now()
        draft.rejected_by = request.user
        draft.rejection_reason = reason
        draft.save()
        
        return JsonResponse({'success': True, 'message': 'Draft rejected'})
    
    return JsonResponse({
        'success': True, 
        'message': f'Approval recorded ({draft.get_approval_status()["approved"]}/{draft.get_approval_status()["total"]})'
    })


@login_required
@require_POST
def api_publish(request):
    """Publish an approved draft."""
    
    if not is_admin(request.user):
        return JsonResponse({'success': False, 'error': 'Only admins can publish'})
    
    draft_id = request.POST.get('draft_id')
    draft = get_object_or_404(OrgDraft, pk=draft_id)
    
    if draft.status != OrgDraft.Status.APPROVED:
        return JsonResponse({'success': False, 'error': 'Only approved drafts can be published'})
    
    # Create published version
    published = OrgPublished.objects.create(
        draft=draft,
        structure=draft.structure,
        name=draft.name,
        description=draft.description,
        version=draft.version,
        department=draft.department,
        published_by=request.user
    )
    
    draft.status = OrgDraft.Status.PUBLISHED
    draft.published_at = timezone.now()
    draft.published_by = request.user
    draft.save()
    
    # Audit log
    OrgAuditLog.objects.create(
        draft=draft,
        user=request.user,
        action=OrgAuditLog.Action.PUBLISHED,
        details={'published_id': published.pk}
    )
    
    return JsonResponse({'success': True, 'message': 'Published successfully!'})


@login_required
@require_GET
def api_pending_count(request):
    """Return the count of pending approvals for the current admin."""
    
    if not is_admin(request.user):
        return HttpResponse('0')
    
    # Count drafts pending approval that the current user hasn't approved yet
    pending_drafts = OrgDraft.objects.filter(status=OrgDraft.Status.PENDING)
    
    pending_count = 0
    for draft in pending_drafts:
        if not draft.org_approval_records.filter(user=request.user, approved=True).exists():
            pending_count += 1
    
    return HttpResponse(str(pending_count))