# apps/maintenance/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
from django.db import transaction
from datetime import datetime, timedelta, date
import calendar
import logging

from .models import (
    MaintenanceSchedule, MaintenanceActivityLog, MaintenanceChecklistTemplate,
    MaintenanceAssetConfirmation, Vendor,
)
from .forms import MaintenanceScheduleForm, MaintenanceStatusForm, MaintenanceAssetConfirmForm
from apps.accounts.models import User
from apps.tickets.models import Asset

ASSET_EXCLUDED_STATUSES = [
    Asset.Status.RETIRED, Asset.Status.SCRAPPED, Asset.Status.DISPOSED,
    Asset.Status.LOST, Asset.Status.STOLEN,
]
from apps.common.utils import send_email_via_brevo, role_of
from apps.common.models import Notification
from apps.common.permissions import get_sidebar_template, effective_role_name

logger = logging.getLogger(__name__)


def notify_maintenance_assignees(schedule, message):
    """In-app notification for the primary assignee and any additional
    personnel on a schedule — the existing email helpers only ever reach
    schedule.assigned_to, so this is the only place additional_assignees
    hear about anything."""
    recipients = list(schedule.additional_assignees.all())
    if schedule.assigned_to:
        recipients.append(schedule.assigned_to)
    url = reverse('maintenance:detail', kwargs={'pk': schedule.pk})
    for recipient in {r.pk: r for r in recipients}.values():
        Notification.objects.create(
            recipient=recipient,
            role=role_of(recipient),
            message=message,
            url=url,
            type=Notification.Type.GENERAL,
        )

def notify_maintenance_management(schedule, message, actor):
    """Notify Admin/Superadmin org-wide plus any of the target departments'
    Team Leads when a schedule starts or completes — excludes the acting
    user so nobody gets notified about their own action."""
    recipients = User.objects.filter(
        Q(role=User.Role.TEAM_LEAD, department__in=schedule.departments) |
        Q(role__in=[User.Role.ADMIN, User.Role.SUPERADMIN]),
        is_active=True,
    )
    if actor:
        recipients = recipients.exclude(pk=actor.pk)
    url = reverse('maintenance:detail', kwargs={'pk': schedule.pk})
    for recipient in {r.pk: r for r in recipients}.values():
        Notification.objects.create(
            recipient=recipient,
            role=role_of(recipient),
            message=message,
            url=url,
            type=Notification.Type.GENERAL,
        )


def _asset_confirmation_recipients(asset):
    """Who is eligible to confirm/dispute maintenance on this asset — mirrors
    can_confirm_asset_maintenance's resolution so 'who is notified' matches
    'who may act': asset.assigned_to if set, else every Team Lead of the
    asset's department, plus (always) every Admin/Superadmin."""
    if asset.assigned_to_id:
        recipients = [asset.assigned_to]
    else:
        recipients = list(User.objects.filter(
            role=User.Role.TEAM_LEAD, department=asset.department, is_active=True,
        ))
    recipients += list(User.objects.filter(
        role__in=[User.Role.ADMIN, User.Role.SUPERADMIN], is_active=True,
    ))
    return list({r.pk: r for r in recipients}.values())


def _asset_review_url(asset, schedule, recipient):
    """Where a confirmation notification/email should send its recipient.
    The asset's OWNER lands on their own My Assets page with the relevant
    confirm modal deep-linked open (?schedule=&asset=) — never the
    IT-internal maintenance detail page, which would expose personnel,
    activity log, and notification-status info that isn't this person's
    business. A department-Team-Lead/Admin fallback confirmer, by contrast,
    IS IT-side staff with legitimate access, so they go to the normal
    schedule detail page (same as every other IT notification)."""
    if asset.assigned_to_id == recipient.pk:
        return f"{reverse('tickets:my_assets')}?schedule={schedule.pk}&asset={asset.pk}"
    return reverse('maintenance:detail', kwargs={'pk': schedule.pk})


def notify_asset_confirmers(asset, schedule, message, exclude=None):
    """In-app notification to everyone eligible to confirm/dispute
    maintenance on a given asset (see _asset_confirmation_recipients)."""
    recipients = _asset_confirmation_recipients(asset)
    if exclude:
        recipients = [r for r in recipients if r.pk != exclude.pk]
    for recipient in recipients:
        Notification.objects.create(
            recipient=recipient,
            role=role_of(recipient),
            message=message,
            url=_asset_review_url(asset, schedule, recipient),
            type=Notification.Type.GENERAL,
        )


def notify_asset_owners_completion(schedule):
    """Fired once from schedule_update_status when a schedule is marked
    COMPLETED — tells each target asset's owner (or fallback confirmer) that
    the schedule is now awaiting their confirmation."""
    for asset in schedule.target_assets.all():
        notify_asset_confirmers(
            asset, schedule,
            f'"{schedule.title}" was marked complete — please confirm or dispute the work done on {asset.name} ({asset.tracking_id}).',
        )


def notify_department_team_leads(schedule, departments, request, actor=None):
    """One-time, informational notice to the Team Lead(s) of the given
    departments when maintenance is scheduled for their department — in-app
    + email. Callers pass only the departments that should be notified now
    (e.g. all of them on create, or just the newly-added ones on edit)."""
    if not departments:
        return
    team_leads = User.objects.filter(
        role=User.Role.TEAM_LEAD, department__in=departments, is_active=True,
    )
    if actor:
        team_leads = team_leads.exclude(pk=actor.pk)
    url = reverse('maintenance:detail', kwargs={'pk': schedule.pk})
    for tl in team_leads:
        Notification.objects.create(
            recipient=tl,
            role=role_of(tl),
            message=f'New maintenance scheduled for {tl.get_department_display()}: "{schedule.title}" ({schedule.scheduled_date}).',
            url=url,
            type=Notification.Type.GENERAL,
        )
        send_maintenance_teamlead_notice_email(schedule, tl, request)


def sync_checklist_templates(departments, items, user):
    """Ensure every checklist item text used on a schedule exists as a
    reusable MaintenanceChecklistTemplate for each of the schedule's target
    departments, reusing an existing item if one already matches
    case-insensitively. A schedule covering multiple departments grows the
    picklist for each of them (a checklist item is still a single
    department's content — the schedule's picker just unions across all its
    target departments)."""
    for department in departments:
        for item in items:
            exists = MaintenanceChecklistTemplate.objects.filter(
                department=department, text__iexact=item
            ).exists()
            if not exists:
                MaintenanceChecklistTemplate.objects.create(
                    department=department, text=item, created_by=user
                )


def get_user_role(request):
    """Helper to get user's active role name."""
    role = request.user.get_active_role()
    return role.name if role else request.user.role

# get_sidebar_template is imported from apps.common.permissions (see top of file).


def can_manage_maintenance(user):
    """Check if user can manage maintenance (create, edit, delete).

    A Team Lead outside IT is scoped solely to the service-request approval
    flow for now, so maintenance management stays IT-only regardless of
    role name."""
    role = user.get_active_role()
    role_name = role.name if role else user.role
    if role_name not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return False
    if role_name == 'TEAM_LEAD':
        return user.department == 'IT'
    return True


def can_change_maintenance_status(user, schedule):
    """Who may transition a schedule's status (start/complete/cancel):
    the assigned officer(s), or one of the schedule's OWN target
    departments' Team Lead. Admin/Superadmin can view but not directly
    change status — asset owners confirm completion separately via
    can_confirm_asset_maintenance."""
    if schedule.is_assigned_to(user):
        return True
    role = user.get_active_role()
    role_name = role.name if role else user.role
    if role_name == 'TEAM_LEAD' and user.department in schedule.departments:
        return True
    return False


def can_confirm_asset_maintenance(user, asset, schedule):
    """Who may confirm/dispute maintenance completion on ONE target asset —
    this is the anti-fraud control: the technician who did the work is never
    the confirmer.

    Resolution: asset.assigned_to (the owner) if set, else any Team Lead of
    the asset's own department (not schedule.departments — a schedule can
    span several). Admin/Superadmin can ALWAYS confirm/override/dispute
    regardless of the above, since they scheduled the maintenance and are
    accountable for it — this also automatically covers the "zero Team
    Leads for this department" fallback, since Admin/Superadmin are
    unconditionally eligible whether or not a Team Lead exists."""
    role = user.get_active_role()
    role_name = role.name if role else user.role
    if role_name in ('ADMIN', 'SUPERADMIN'):
        return True
    if asset.assigned_to_id:
        return asset.assigned_to_id == user.id
    return role_name == 'TEAM_LEAD' and user.department == asset.department


def log_activity(schedule, action, actor=None, details=None):
    """Helper to create activity log entry."""
    MaintenanceActivityLog.objects.create(
        schedule=schedule,
        action=action,
        actor=actor,
        details=details or {}
    )


@login_required
def schedule_list(request):
    """List all maintenance schedules with filters."""
    if effective_role_name(request.user) not in ('AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'):
        return HttpResponse(status=403)

    schedules = MaintenanceSchedule.objects.all()
    
    # Filters
    department = request.GET.get('department', '')
    status = request.GET.get('status', '')
    month = request.GET.get('month', '')
    mine = request.GET.get('mine') == '1'

    if mine:
        schedules = schedules.filter(
            Q(assigned_to=request.user) | Q(additional_assignees=request.user)
        ).distinct()
    if department:
        schedules = schedules.filter(departments__contains=[department])
    if status:
        schedules = schedules.filter(status=status)
    if month:
        try:
            year, mon = month.split('-')
            schedules = schedules.filter(
                scheduled_date__year=int(year),
                scheduled_date__month=int(mon)
            )
        except ValueError:
            pass
    
    # If team lead, only see schedules that target their department
    role = request.user.get_active_role()
    if role and role.name == 'TEAM_LEAD':
        schedules = schedules.filter(departments__contains=[request.user.department])

    schedules = schedules.order_by('-scheduled_date', '-created_at')
    
    # Pagination
    paginator = Paginator(schedules, 15)
    page = request.GET.get('page', 1)
    try:
        schedules_page = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        schedules_page = paginator.page(1)
    
    # Stats
    stats = {
        'total': schedules.count(),
        'scheduled': schedules.filter(status=MaintenanceSchedule.Status.SCHEDULED).count(),
        'in_progress': schedules.filter(status=MaintenanceSchedule.Status.IN_PROGRESS).count(),
        'completed': schedules.filter(status=MaintenanceSchedule.Status.COMPLETED).count(),
    }
    
    # Department choices for filter
    department_choices = MaintenanceSchedule.Department.choices
    
    context = {
        'schedules': schedules_page,
        'stats': stats,
        'department_choices': department_choices,
        'selected_department': department,
        'selected_status': status,
        'selected_month': month,
        'mine': mine,
        'sidebar_template': get_sidebar_template(request.user),
        'user_role': get_user_role(request)
    }
    
    if request.headers.get('HX-Request'):
        return render(request, 'maintenance/partials/schedule_table.html', context)
    
    return render(request, 'maintenance/schedule_list.html', context)


@login_required
@user_passes_test(can_manage_maintenance)
def schedule_create(request):
    """Create a new maintenance schedule."""
    
    if request.method == 'POST':
        form = MaintenanceScheduleForm(request.POST)
        if form.is_valid():
            schedule = form.save(commit=False)
            schedule.save()
            form.save_m2m()

            # Set checklist items
            schedule.checklist_items = form.cleaned_data.get('checklist_items', [])
            schedule.save(update_fields=['checklist_items'])
            sync_checklist_templates(schedule.departments, schedule.checklist_items, request.user)

            # Log creation
            log_activity(schedule, MaintenanceActivityLog.Action.CREATED, request.user)

            # Send email to assigned IT personnel
            if schedule.assigned_to:
                send_maintenance_assignment_email(schedule, request)
            notify_maintenance_assignees(schedule, f'You were assigned to maintenance: "{schedule.title}" ({schedule.scheduled_date}).')

            # Inform each target department's Team Lead(s) — informational,
            # fires once at creation for every department on the schedule.
            notify_department_team_leads(schedule, schedule.departments, request, actor=request.user)

            messages.success(request, f'Maintenance schedule "{schedule.title}" created successfully.')

            detail_url = reverse('maintenance:detail', kwargs={'pk': schedule.pk})
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Redirect': detail_url})
            return redirect(detail_url)
        else:
            messages.error(request, 'Please correct the errors below.')
            if request.headers.get('HX-Request'):
                it_roles = ['SUPERADMIN', 'ADMIN', 'TEAM_LEAD', 'AGENT']
                context = {
                    'form': form,
                    'schedule': schedule if 'schedule' in locals() and isinstance(schedule, MaintenanceSchedule) else None,
                    'it_users': User.objects.filter(role__in=it_roles, is_active=True).order_by('first_name', 'last_name'),
                    'vendors': Vendor.objects.filter(is_active=True).order_by('name'),
                    'department_choices': MaintenanceSchedule.Department.choices,
                    'checklist_items': form.data.getlist('checklist_items') if hasattr(form.data, 'getlist') else [],
                }
                return render(request, 'maintenance/partials/schedule_form_fields.html', context)
    else:
        form = MaintenanceScheduleForm()
    
    # Get IT users for dropdown
    it_roles = ['SUPERADMIN', 'ADMIN', 'TEAM_LEAD', 'AGENT']
    it_users = User.objects.filter(role__in=it_roles, is_active=True).order_by('first_name', 'last_name')

    context = {
        'form': form,
        'schedule': None,
        'it_users': it_users,
        'vendors': Vendor.objects.filter(is_active=True).order_by('name'),
        'department_choices': MaintenanceSchedule.Department.choices,
        'sidebar_template': get_sidebar_template(request.user),
        'checklist_items': [],
        'user_role': get_user_role(request)
    }

    return render(request, 'maintenance/schedule_form.html', context)


@login_required
@user_passes_test(can_manage_maintenance)
def schedule_edit(request, pk):
    """Edit an existing maintenance schedule."""
    
    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)
    
    # Only allow editing if not completed or cancelled
    if schedule.status in [MaintenanceSchedule.Status.COMPLETED, MaintenanceSchedule.Status.CANCELLED]:
        messages.error(request, 'Cannot edit a completed or cancelled schedule.')
        return redirect('maintenance:detail', pk=pk)
    
    if request.method == 'POST':
        old_departments = set(schedule.departments)
        form = MaintenanceScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            old_status = schedule.status
            schedule = form.save()

            # Update checklist
            schedule.checklist_items = form.cleaned_data.get('checklist_items', [])
            schedule.save(update_fields=['checklist_items'])
            sync_checklist_templates(schedule.departments, schedule.checklist_items, request.user)

            # Log update
            log_activity(schedule, MaintenanceActivityLog.Action.UPDATED, request.user)

            # Send email if assigned_to changed
            if schedule.assigned_to:
                send_maintenance_assignment_email(schedule, request)
            notify_maintenance_assignees(schedule, f'Maintenance schedule updated: "{schedule.title}" ({schedule.scheduled_date}).')

            # Only notify Team Leads of departments newly added to the
            # schedule — avoids re-notifying on every unrelated edit.
            newly_added_departments = [d for d in schedule.departments if d not in old_departments]
            notify_department_team_leads(schedule, newly_added_departments, request, actor=request.user)

            messages.success(request, f'Maintenance schedule "{schedule.title}" updated successfully.')

            detail_url = reverse('maintenance:detail', kwargs={'pk': schedule.pk})
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Redirect': detail_url})
            return redirect(detail_url)
        else:
            messages.error(request, 'Please correct the errors below.')
            if request.headers.get('HX-Request'):
                it_roles = ['SUPERADMIN', 'ADMIN', 'TEAM_LEAD', 'AGENT']
                context = {
                    'form': form,
                    'schedule': schedule if 'schedule' in locals() and isinstance(schedule, MaintenanceSchedule) else None,
                    'it_users': User.objects.filter(role__in=it_roles, is_active=True).order_by('first_name', 'last_name'),
                    'vendors': Vendor.objects.filter(is_active=True).order_by('name'),
                    'department_choices': MaintenanceSchedule.Department.choices,
                    'checklist_items': form.data.getlist('checklist_items') if hasattr(form.data, 'getlist') else [],
                }
                return render(request, 'maintenance/partials/schedule_form_fields.html', context)
    else:
        form = MaintenanceScheduleForm(instance=schedule)
        # Pre-populate checklist_items as text
        if schedule.checklist_items:
            form.initial['checklist_items'] = '\n'.join(schedule.checklist_items)
    
    it_roles = ['SUPERADMIN', 'ADMIN', 'TEAM_LEAD', 'AGENT']
    it_users = User.objects.filter(role__in=it_roles, is_active=True).order_by('first_name', 'last_name')
    
    context = {
        'form': form,
        'schedule': schedule,
        'it_users': it_users,
        'vendors': Vendor.objects.filter(is_active=True).order_by('name'),
        'department_choices': MaintenanceSchedule.Department.choices,
        'sidebar_template': get_sidebar_template(request.user),
        'checklist_items': schedule.checklist_items,
        'user_role': get_user_role(request),
    }
    
    return render(request, 'maintenance/schedule_form.html', context)


@login_required
def schedule_detail(request, pk):
    """View maintenance schedule details."""
    
    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)
    
    # Security: Team Lead can only view schedules targeting their department
    role = request.user.get_active_role()
    if role and role.name == 'TEAM_LEAD' and request.user.department not in schedule.departments:
        messages.error(request, 'You do not have permission to view this schedule.')
        return redirect('maintenance:list')
    
    # Activity logs
    logs = schedule.activity_logs.all()[:20]

    asset_confirmations = [
        {
            'row': row,
            'can_confirm': can_confirm_asset_maintenance(request.user, row.asset, schedule),
        }
        for row in schedule.asset_confirmations.select_related('asset', 'confirmed_by')
    ]
    context = {
        'schedule': schedule,
        'activity_logs': logs,
        'asset_confirmations': asset_confirmations,
        'confirmation_state': schedule.confirmation_state(),
        'can_change_status': can_change_maintenance_status(request.user, schedule),
        'user_can_manage': can_manage_maintenance(request.user),
        'sidebar_template': get_sidebar_template(request.user),
         'user_role': get_user_role(request),
    }

    return render(request, 'maintenance/schedule_detail.html', context)


@login_required
@require_POST
def schedule_update_status(request, pk):
    """Update schedule status via HTMX modal."""
    
    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)

    # Security: only the assigned officer(s) or the target department's
    # Team Lead may change status — Admin/Superadmin can view but not act.
    if not can_change_maintenance_status(request.user, schedule):
        return HttpResponse(status=403)

    # COMPLETED/CANCELLED are terminal — completing already creates one
    # MaintenanceAssetConfirmation per target asset and emails owners, so
    # allowing a further transition out of it risks duplicate confirmations
    # and a misleading completed_at/notification trail.
    if schedule.status in (MaintenanceSchedule.Status.COMPLETED, MaintenanceSchedule.Status.CANCELLED):
        messages.error(request, f'This schedule is already {schedule.get_status_display()} and cannot be changed further.')
        return redirect('maintenance:detail', pk=pk)

    form = MaintenanceStatusForm(request.POST)
    if form.is_valid():
        new_status = form.cleaned_data['status']
        comment = form.cleaned_data.get('comment', '')
        
        if new_status == schedule.status:
            messages.info(request, 'Status is already set to that.')
            return redirect('maintenance:detail', pk=pk)
        
        old_status = schedule.status
        schedule.status = new_status
        
        # Set completed_at if status is COMPLETED
        if new_status == MaintenanceSchedule.Status.COMPLETED:
            schedule.completed_at = timezone.now()
            # There's no per-item toggle UI today — completing the task
            # marks every checklist item done, so progress reflects reality
            # instead of staying stuck at 0%.
            schedule.completed_checklist = list(schedule.checklist_items)
            # Send email to manager — informational; the schedule isn't
            # actually closed until each target asset's owner confirms below.
            send_maintenance_completion_email(schedule, request)

        schedule.save()

        # Technician's "mark complete" only starts the confirmation process —
        # create one PENDING confirmation row per target asset, to be
        # resolved by that asset's owner (not the technician), per
        # can_confirm_asset_maintenance.
        if new_status == MaintenanceSchedule.Status.COMPLETED:
            for asset in schedule.target_assets.all():
                MaintenanceAssetConfirmation.objects.get_or_create(
                    schedule=schedule, asset=asset,
                    defaults={'technician_completed_at': schedule.completed_at},
                )
            notify_asset_owners_completion(schedule)
        
        # Log status change
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.STATUS_CHANGED,
            request.user,
            {'from': old_status, 'to': new_status, 'comment': comment}
        )

        # Notify admins + the target department's Team Lead when work
        # actually starts or finishes.
        if new_status == MaintenanceSchedule.Status.IN_PROGRESS:
            notify_maintenance_management(
                schedule,
                f'"{schedule.title}" was started by {request.user.get_full_name()}.',
                request.user,
            )
        elif new_status == MaintenanceSchedule.Status.COMPLETED:
            notify_maintenance_management(
                schedule,
                f'"{schedule.title}" was marked complete by {request.user.get_full_name()} — pending owner confirmation.',
                request.user,
            )

        messages.success(request, f'Status updated to {schedule.get_status_display()}.')
        
        if request.headers.get('HX-Request'):
            return HttpResponse('')
        
        return redirect('maintenance:detail', pk=pk)
    
    return render(request, 'maintenance/partials/status_modal.html', {
        'schedule': schedule,
        'form': form,
    })


@login_required
def schedule_status_modal(request, pk):
    """Return the status update modal (HTMX)."""
    
    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)

    if not can_change_maintenance_status(request.user, schedule):
        return HttpResponse(status=403)

    form = MaintenanceStatusForm(initial={'status': schedule.status})

    return render(request, 'maintenance/partials/status_modal.html', {
        'schedule': schedule,
        'form': form,
    })


def _simple_modal_notice(request, message):
    """A minimal modal-shell notice, styled to match the real confirm modal,
    for cases the modal can't proceed (permission/state) — used instead of a
    bare-text error response so a mistimed deep-link (e.g. a pre-maintenance
    reminder email opened before the technician has marked the work
    complete) doesn't dump raw error text into the page."""
    return render(request, 'maintenance/partials/simple_modal_notice.html', {'message': message})


@login_required
def asset_confirm_modal(request, pk, asset_pk):
    """Return the per-asset confirm/dispute modal (HTMX)."""

    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)
    asset = get_object_or_404(schedule.target_assets, pk=asset_pk)

    if not can_confirm_asset_maintenance(request.user, asset, schedule):
        return _simple_modal_notice(request, 'You do not have permission to confirm this asset\'s maintenance.')

    row = schedule.asset_confirmations.filter(asset=asset).first()
    if not row:
        return _simple_modal_notice(request, 'This maintenance hasn\'t been marked complete yet — there\'s nothing to confirm just yet. You\'ll be notified again once it is.')

    # A resolved row can only be re-opened by Admin/Superadmin (their
    # permanent override) — the owner's confirmation is otherwise final.
    role = request.user.get_active_role()
    role_name = role.name if role else request.user.role
    if row.status != MaintenanceAssetConfirmation.Status.PENDING and role_name not in ('ADMIN', 'SUPERADMIN'):
        return _simple_modal_notice(request, 'This asset has already been confirmed/disputed.')

    form = MaintenanceAssetConfirmForm()

    return render(request, 'maintenance/partials/asset_confirmation_modal.html', {
        'schedule': schedule,
        'asset': asset,
        'row': row,
        'form': form,
    })


@login_required
@require_POST
def asset_confirm(request, pk, asset_pk):
    """Confirm or dispute maintenance completion for one target asset
    (asset owner, department Team Lead fallback, or Admin/Superadmin
    override — see can_confirm_asset_maintenance)."""

    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)
    asset = get_object_or_404(schedule.target_assets, pk=asset_pk)

    # Non-HTMX fallback only (the real modal flow always submits via HTMX
    # and never reaches these redirects) — sends the asset's owner back to
    # My Assets rather than the IT-internal schedule detail page.
    fallback_redirect = (
        redirect('tickets:my_assets') if asset.assigned_to_id == request.user.pk
        else redirect('maintenance:detail', pk=pk)
    )

    if not can_confirm_asset_maintenance(request.user, asset, schedule):
        messages.error(request, 'You do not have permission to confirm this asset\'s maintenance.')
        return fallback_redirect

    row = schedule.asset_confirmations.filter(asset=asset).first()
    if not row:
        messages.error(request, 'This maintenance is not ready for confirmation.')
        return fallback_redirect

    role = request.user.get_active_role()
    role_name = role.name if role else request.user.role
    if row.status != MaintenanceAssetConfirmation.Status.PENDING and role_name not in ('ADMIN', 'SUPERADMIN'):
        messages.error(request, 'This asset has already been confirmed/disputed.')
        return fallback_redirect

    form = MaintenanceAssetConfirmForm(request.POST)
    if form.is_valid():
        decision = form.cleaned_data['decision']
        row.status = decision
        row.confirmed_by = request.user
        row.confirmed_at = timezone.now()
        row.notes = form.cleaned_data.get('notes', '')
        row.dispute_reason = form.cleaned_data.get('dispute_reason', '') if decision == 'DISPUTED' else ''
        row.save()

        log_activity(
            schedule,
            MaintenanceActivityLog.Action.CONFIRMED if decision == 'CONFIRMED' else MaintenanceActivityLog.Action.DISPUTED,
            request.user,
            {'asset': asset.tracking_id, 'status': decision, 'notes': row.notes, 'dispute_reason': row.dispute_reason},
        )

        send_asset_confirmation_email(schedule, asset, row, request)
        if decision == 'CONFIRMED':
            notify_maintenance_assignees(schedule, f'{asset.name} ({asset.tracking_id}) was confirmed complete by {request.user.get_full_name()}.')
            messages.success(request, f'Maintenance on {asset.name} confirmed successfully.')
        else:
            notify_maintenance_assignees(schedule, f'{asset.name} ({asset.tracking_id}) maintenance was disputed by {request.user.get_full_name()}: {row.dispute_reason}')
            messages.warning(request, f'Maintenance on {asset.name} marked as disputed.')

        if request.headers.get('HX-Request'):
            return HttpResponse('')

        return fallback_redirect

    return render(request, 'maintenance/partials/asset_confirmation_modal.html', {
        'schedule': schedule,
        'asset': asset,
        'row': row,
        'form': form,
    })


@login_required
def checklist_templates_partial(request):
    """HTMX endpoint: checkbox list of active checklist templates unioned
    across all currently-checked target departments, reloaded whenever the
    schedule form's department selection changes."""
    departments = request.GET.getlist('departments')
    templates = MaintenanceChecklistTemplate.objects.filter(
        department__in=departments, is_active=True
    ) if departments else MaintenanceChecklistTemplate.objects.none()

    return render(request, 'maintenance/partials/checklist_template_options.html', {
        'templates': templates,
    })


@login_required
def target_assets_partial(request):
    """HTMX endpoint: checkbox list of assets across all currently-checked
    target departments, reloaded whenever the schedule form's department
    selection changes. Pre-checks assets already linked to the schedule
    being edited (schedule_id, optional) so reloading the partial doesn't
    silently drop existing selections."""
    departments = request.GET.getlist('departments')
    schedule_id = request.GET.get('schedule_id', '')

    selected_ids = set()
    if schedule_id:
        try:
            schedule = MaintenanceSchedule.objects.get(pk=schedule_id)
            selected_ids = set(schedule.target_assets.values_list('pk', flat=True))
        except (MaintenanceSchedule.DoesNotExist, ValueError):
            pass

    assets = Asset.objects.filter(department__in=departments).exclude(
        status__in=ASSET_EXCLUDED_STATUSES
    ).order_by('name') if departments else Asset.objects.none()

    return render(request, 'maintenance/partials/target_asset_options.html', {
        'assets': assets,
        'selected_ids': selected_ids,
    })


@login_required
def calendar_view(request):
    """Custom calendar view of maintenance schedules."""
    if effective_role_name(request.user) not in ('AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'):
        return HttpResponse(status=403)

    # Get month/year from request or use current
    month = int(request.GET.get('month', timezone.now().month))
    year = int(request.GET.get('year', timezone.now().year))
    
    # Get schedules for this month
    schedules = MaintenanceSchedule.objects.filter(
        scheduled_date__year=year,
        scheduled_date__month=month
    )
    
    # Filter by department for Team Lead
    role = request.user.get_active_role()
    if role and role.name == 'TEAM_LEAD':
        schedules = schedules.filter(departments__contains=[request.user.department])

    # Build calendar days with events
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]
    
    calendar_days = []
    today = timezone.now().date()
    
    for week in cal:
        for day in week:
            if day == 0:
                calendar_days.append({
                    'day': None,
                    'date': None,
                    'events': [],
                    'is_today': False,
                    'is_other_month': True,
                })
            else:
                date_obj = date(year, month, day)
                day_schedules = schedules.filter(scheduled_date=date_obj)
                
                # Color map for events
                color_map = {
                    'SCHEDULED': '#3B82F6',
                    'IN_PROGRESS': '#F59E0B',
                    'COMPLETED': '#10B981',
                    'CANCELLED': '#6B7280'
                }
                
                events = []
                for schedule in day_schedules:
                    events.append({
                        'id': schedule.pk,
                        'title': schedule.title,
                        'status': schedule.get_status_display(),
                        'color': color_map.get(schedule.status, '#3B82F6'),
                        'url': f'/maintenance/{schedule.pk}/',
                    })
                
                calendar_days.append({
                    'day': day,
                    'date': date_obj.isoformat(),
                    'events': events,
                    'is_today': date_obj == today,
                    'is_other_month': False,
                })
    
    context = {
        'calendar_days': calendar_days,
        'month': month,
        'year': year,
        'month_name': month_name,
        'schedules': schedules.order_by('scheduled_date'),
        'sidebar_template': get_sidebar_template(request.user),
        'user_role': get_user_role(request),
    }
    
    # ✅ CRITICAL: If HTMX request, return ONLY the grid partial
    if request.headers.get('HX-Request'):
        return render(request, 'maintenance/partials/calendar_grid.html', context)
    
    # Full page render
    return render(request, 'maintenance/calendar_view.html', context)


@login_required
def calendar_day_events(request):
    """HTMX endpoint to load events for a specific day."""
    date_str = request.GET.get('date')
    if not date_str:
        return HttpResponse('')
    
    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return HttpResponse('')
    
    schedules = MaintenanceSchedule.objects.filter(scheduled_date=selected_date)
    
    # Filter by department for Team Lead
    role = request.user.get_active_role()
    if role and role.name == 'TEAM_LEAD':
        schedules = schedules.filter(departments__contains=[request.user.department])

    schedules = schedules.order_by('status')
    
    return render(request, 'maintenance/partials/day_events.html', {
        'schedules': schedules,
        'selected_date': selected_date,
    })


# ================================================================
# EMAIL HELPERS
# ================================================================

def send_maintenance_assignment_email(schedule, request):
    """Send email to assigned IT personnel when schedule is created/assigned."""
    
    if not schedule.assigned_to:
        return
    
    context = {
        'schedule': schedule,
        'assigned_to': schedule.assigned_to.get_full_name() or schedule.assigned_to.email,
        'department': schedule.departments_display,
        'date': schedule.scheduled_date.strftime('%B %d, %Y'),
        'detail_url': request.build_absolute_uri(
            f'/maintenance/{schedule.pk}/'
        ),
        'checklist': schedule.checklist_items,
    }

    html_message = render_to_string('emails/maintenance_assignment.html', context)
    
    success, result = send_email_via_brevo(
        to_email=schedule.assigned_to.email,
        subject=f"Maintenance Assignment: {schedule.title}",
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )
    
    if success:
        schedule.email_sent = True
        schedule.email_sent_at = timezone.now()
        schedule.save(update_fields=['email_sent', 'email_sent_at'])
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.EMAIL_SENT,
            None,
            {'recipient': schedule.assigned_to.email, 'type': 'assignment'}
        )
    else:
        logger.error(f"Failed to send assignment email for schedule {schedule.pk}: {result}")


def send_maintenance_completion_email(schedule, request):
    """Send email to department manager when maintenance is completed."""
    
    # Find a manager belonging to any of the target departments (Team Lead
    # or Admin), falling back to any Admin — same two-step lookup as the
    # original single-department version, just department__in-aware.
    manager = User.objects.filter(
        Q(role=User.Role.TEAM_LEAD) | Q(role=User.Role.ADMIN) | Q(role=User.Role.SUPERADMIN),
        department__in=schedule.departments,
        is_active=True
    ).first()

    if not manager:
        # Fallback: send to any admin
        manager = User.objects.filter(role=User.Role.ADMIN, is_active=True).first()

    if not manager:
        return

    context = {
        'schedule': schedule,
        'department': schedule.departments_display,
        'date': schedule.scheduled_date.strftime('%B %d, %Y'),
        'assigned_to': schedule.assigned_to.get_full_name() or schedule.assigned_to.email,
        'detail_url': request.build_absolute_uri(
            f'/maintenance/{schedule.pk}/'
        ),
        # Confirmation is per-asset now (see MaintenanceAssetConfirmation) —
        # there's no single schedule-level confirm action any more, so this
        # links to the same detail page, which lists every target asset's
        # confirmation state and the per-asset Confirm/Dispute action.
        'confirm_url': request.build_absolute_uri(
            f'/maintenance/{schedule.pk}/'
        ),
        'checklist': schedule.checklist_items,
        'completed_checklist': schedule.completed_checklist,
    }

    html_message = render_to_string('emails/maintenance_completion.html', context)
    
    success, result = send_email_via_brevo(
        to_email=manager.email,
        subject=f"Maintenance Completed: {schedule.title} - Awaiting Confirmation",
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )
    
    if success:
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.EMAIL_SENT,
            None,
            {'recipient': manager.email, 'type': 'completion'}
        )
    else:
        logger.error(f"Failed to send completion email for schedule {schedule.pk}: {result}")


def send_asset_confirmation_email(schedule, asset, row, request):
    """Send email to the technician (assigned_to) when an asset owner
    confirms or disputes maintenance completion on one target asset."""

    if not schedule.assigned_to:
        return

    context = {
        'schedule': schedule,
        'asset': asset,
        'row': row,
        'confirmed_by': row.confirmed_by.get_full_name() or row.confirmed_by.email,
        'department': schedule.departments_display,
        'date': schedule.scheduled_date.strftime('%B %d, %Y'),
        'notes': row.notes,
        'dispute_reason': row.dispute_reason,
        'detail_url': request.build_absolute_uri(
            f'/maintenance/{schedule.pk}/'
        ),
    }

    html_message = render_to_string('emails/maintenance_asset_confirmed.html', context)

    subject = (
        f"Maintenance Confirmed: {schedule.title} — {asset.name}"
        if row.status == MaintenanceAssetConfirmation.Status.CONFIRMED
        else f"Maintenance Disputed: {schedule.title} — {asset.name}"
    )

    success, result = send_email_via_brevo(
        to_email=schedule.assigned_to.email,
        subject=subject,
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )

    if success:
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.EMAIL_SENT,
            None,
            {'recipient': schedule.assigned_to.email, 'type': 'asset_confirmation', 'asset': asset.tracking_id}
        )
    else:
        logger.error(f"Failed to send asset confirmation email for schedule {schedule.pk}/asset {asset.pk}: {result}")


def send_maintenance_teamlead_notice_email(schedule, team_lead, request):
    """Informational email to a department Team Lead when maintenance is
    scheduled for their department — fired once at scheduling time, not an
    action item."""

    context = {
        'schedule': schedule,
        'team_lead': team_lead.get_full_name() or team_lead.email,
        'department': team_lead.get_department_display(),
        'date': schedule.scheduled_date.strftime('%B %d, %Y'),
        'assigned_to': schedule.assigned_to.get_full_name() if schedule.assigned_to else 'Unassigned',
        'detail_url': request.build_absolute_uri(f'/maintenance/{schedule.pk}/'),
    }

    html_message = render_to_string('emails/maintenance_teamlead_notice.html', context)

    success, result = send_email_via_brevo(
        to_email=team_lead.email,
        subject=f"Maintenance Scheduled for {context['department']}: {schedule.title}",
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )

    if success:
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.EMAIL_SENT,
            None,
            {'recipient': team_lead.email, 'type': 'teamlead_notice'}
        )
    else:
        logger.error(f"Failed to send Team Lead notice email for schedule {schedule.pk}: {result}")


def send_asset_owner_reminder_email(schedule, asset, recipient, label):
    """Reminder email to an asset owner (or fallback confirmer) — reused for
    both pre-maintenance due-date reminders (label e.g. '24 hours') and the
    post-completion overdue-confirmation nudge (label 'overdue confirmation').

    Called from the send_maintenance_reminders management command, which has
    no HttpRequest to build an absolute URL from — settings.SITE_URL is the
    fallback base for that case (see base.py). Uses _asset_review_url so the
    owner lands on My Assets (modal deep-linked, once a confirmation row
    exists) rather than the IT-internal maintenance detail page."""

    context = {
        'schedule': schedule,
        'asset': asset,
        'recipient': recipient.get_full_name() or recipient.email,
        'label': label,
        'date': schedule.scheduled_date.strftime('%B %d, %Y'),
        'detail_url': f'{settings.SITE_URL}{_asset_review_url(asset, schedule, recipient)}',
    }

    html_message = render_to_string('emails/maintenance_owner_reminder.html', context)

    success, result = send_email_via_brevo(
        to_email=recipient.email,
        subject=f"Maintenance Reminder: {schedule.title} — {asset.name}",
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )

    if not success:
        logger.error(f"Failed to send owner reminder email for schedule {schedule.pk}/asset {asset.pk}: {result}")

