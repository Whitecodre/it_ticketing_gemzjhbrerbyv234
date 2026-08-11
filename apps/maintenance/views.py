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

from .models import MaintenanceSchedule, MaintenanceActivityLog
from .forms import MaintenanceScheduleForm, MaintenanceStatusForm, MaintenanceConfirmForm
from apps.accounts.models import User
from apps.common.utils import send_email_via_brevo

logger = logging.getLogger(__name__)

def get_user_role(request):
    """Helper to get user's active role name."""
    role = request.user.get_active_role()
    return role.name if role else request.user.role

# Helper to get sidebar template
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


def can_manage_maintenance(user):
    """Check if user can manage maintenance (create, edit, delete)."""
    role = user.get_active_role()
    if not role:
        return user.role in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']
    return role.name in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']


def can_confirm_maintenance(user, schedule):
    """Check if user can confirm a schedule (department manager or admin)."""
    # Admin/Superadmin can confirm anything
    role = user.get_active_role()
    if role and role.name in ['ADMIN', 'SUPERADMIN']:
        return True
    # Team Lead can confirm their department
    if role and role.name == 'TEAM_LEAD':
        return user.department == schedule.department
    return False


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
    
    schedules = MaintenanceSchedule.objects.all()
    
    # Filters
    department = request.GET.get('department', '')
    status = request.GET.get('status', '')
    month = request.GET.get('month', '')
    
    if department:
        schedules = schedules.filter(department=department)
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
    
    # If team lead, only see their department
    role = request.user.get_active_role()
    if role and role.name == 'TEAM_LEAD':
        schedules = schedules.filter(department=request.user.department)
    
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

            # Set checklist items
            schedule.checklist_items = form.cleaned_data.get('checklist_items', [])
            schedule.save(update_fields=['checklist_items'])

            # Log creation
            log_activity(schedule, MaintenanceActivityLog.Action.CREATED, request.user)

            # Send email to assigned IT personnel
            if schedule.assigned_to:
                send_maintenance_assignment_email(schedule, request)

            messages.success(request, f'Maintenance schedule "{schedule.title}" created successfully.')

            detail_url = reverse('maintenance:detail', kwargs={'pk': schedule.pk})
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Redirect': detail_url})
            return redirect(detail_url)
        else:
            messages.error(request, 'Please correct the errors below.')
            if request.headers.get('HX-Request'):
                return render(request, 'maintenance/partials/form_errors.html', {'form': form})
    else:
        form = MaintenanceScheduleForm()
    
    # Get IT users for dropdown
    it_roles = ['SUPERADMIN', 'ADMIN', 'TEAM_LEAD', 'AGENT']
    it_users = User.objects.filter(role__in=it_roles, is_active=True).order_by('first_name', 'last_name')
    
    context = {
        'form': form,
        'schedule': None,
        'it_users': it_users,
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
        form = MaintenanceScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            old_status = schedule.status
            schedule = form.save()

            # Update checklist
            schedule.checklist_items = form.cleaned_data.get('checklist_items', [])
            schedule.save(update_fields=['checklist_items'])

            # Log update
            log_activity(schedule, MaintenanceActivityLog.Action.UPDATED, request.user)

            # Send email if assigned_to changed
            if schedule.assigned_to:
                send_maintenance_assignment_email(schedule, request)

            messages.success(request, f'Maintenance schedule "{schedule.title}" updated successfully.')

            detail_url = reverse('maintenance:detail', kwargs={'pk': schedule.pk})
            if request.headers.get('HX-Request'):
                return HttpResponse(status=204, headers={'HX-Redirect': detail_url})
            return redirect(detail_url)
        else:
            messages.error(request, 'Please correct the errors below.')
            if request.headers.get('HX-Request'):
                return render(request, 'maintenance/partials/form_errors.html', {'form': form})
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
    
    # Security: Team Lead can only view their department
    role = request.user.get_active_role()
    if role and role.name == 'TEAM_LEAD' and request.user.department != schedule.department:
        messages.error(request, 'You do not have permission to view this schedule.')
        return redirect('maintenance:list')
    
    # Activity logs
    logs = schedule.activity_logs.all()[:20]
    
    context = {
        'schedule': schedule,
        'activity_logs': logs,
        'can_confirm': can_confirm_maintenance(request.user, schedule),
        'sidebar_template': get_sidebar_template(request.user),
         'user_role': get_user_role(request),
    }
    
    return render(request, 'maintenance/schedule_detail.html', context)


@login_required
@require_POST
def schedule_update_status(request, pk):
    """Update schedule status via HTMX modal."""
    
    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)
    
    # Security: Only assigned IT or admin can update status
    role = request.user.get_active_role()
    if not (role and role.name in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']) and schedule.assigned_to != request.user:
        return HttpResponse(status=403)
    
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
            # Send email to manager for confirmation
            send_maintenance_completion_email(schedule, request)
        
        schedule.save()
        
        # Log status change
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.STATUS_CHANGED,
            request.user,
            {'from': old_status, 'to': new_status, 'comment': comment}
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
    form = MaintenanceStatusForm(initial={'status': schedule.status})
    
    return render(request, 'maintenance/partials/status_modal.html', {
        'schedule': schedule,
        'form': form,
    })


@login_required
def schedule_confirm_modal(request, pk):
    """Return the confirmation modal (HTMX)."""
    
    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)
    
    if not can_confirm_maintenance(request.user, schedule):
        return HttpResponse('You do not have permission to confirm this maintenance.', status=403)
    
    if not schedule.can_confirm():
        return HttpResponse('This maintenance is not ready for confirmation.', status=400)
    
    form = MaintenanceConfirmForm()
    
    return render(request, 'maintenance/partials/confirmation_modal.html', {
        'schedule': schedule,
        'form': form,
    })


@login_required
@require_POST
def schedule_confirm(request, pk):
    """Confirm maintenance completion (manager action)."""
    
    schedule = get_object_or_404(MaintenanceSchedule, pk=pk)
    
    if not can_confirm_maintenance(request.user, schedule):
        messages.error(request, 'You do not have permission to confirm this maintenance.')
        return redirect('maintenance:detail', pk=pk)
    
    if not schedule.can_confirm():
        messages.error(request, 'This maintenance is not ready for confirmation.')
        return redirect('maintenance:detail', pk=pk)
    
    form = MaintenanceConfirmForm(request.POST)
    if form.is_valid():
        schedule.confirmed_by = request.user
        schedule.confirmed_at = timezone.now()
        schedule.confirmation_comment = form.cleaned_data.get('comment', '')
        schedule.save()
        
        # Log confirmation
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.CONFIRMED,
            request.user,
            {'comment': schedule.confirmation_comment}
        )
        
        # Send confirmation email to IT personnel
        if schedule.assigned_to:
            send_confirmation_email(schedule, request)
        
        messages.success(request, f'Maintenance "{schedule.title}" confirmed successfully.')
        
        if request.headers.get('HX-Request'):
            return HttpResponse('')
        
        return redirect('maintenance:detail', pk=pk)
    
    return render(request, 'maintenance/partials/confirmation_modal.html', {
        'schedule': schedule,
        'form': form,
    })


@login_required
def calendar_view(request):
    """Custom calendar view of maintenance schedules."""
    
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
        schedules = schedules.filter(department=request.user.department)
    
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
        schedules = schedules.filter(department=request.user.department)
    
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
        'department': schedule.get_department_display(),
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
    
    # Find the manager for this department (Team Lead or Admin)
    manager = User.objects.filter(
        Q(role=User.Role.TEAM_LEAD) | Q(role=User.Role.ADMIN) | Q(role=User.Role.SUPERADMIN),
        department=schedule.department,
        is_active=True
    ).first()
    
    if not manager:
        # Fallback: send to any admin
        manager = User.objects.filter(role=User.Role.ADMIN, is_active=True).first()
    
    if not manager:
        return
    
    context = {
        'schedule': schedule,
        'department': schedule.get_department_display(),
        'date': schedule.scheduled_date.strftime('%B %d, %Y'),
        'assigned_to': schedule.assigned_to.get_full_name() or schedule.assigned_to.email,
        'detail_url': request.build_absolute_uri(
            f'/maintenance/{schedule.pk}/'
        ),
        'confirm_url': request.build_absolute_uri(
            f'/maintenance/{schedule.pk}/confirm-modal/'
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


def send_confirmation_email(schedule, request):
    """Send email to IT personnel when manager confirms."""
    
    if not schedule.assigned_to:
        return
    
    context = {
        'schedule': schedule,
        'confirmed_by': schedule.confirmed_by.get_full_name() or schedule.confirmed_by.email,
        'department': schedule.get_department_display(),
        'date': schedule.scheduled_date.strftime('%B %d, %Y'),
        'comment': schedule.confirmation_comment,
        'detail_url': request.build_absolute_uri(
            f'/maintenance/{schedule.pk}/'
        ),
    }
    
    html_message = render_to_string('emails/maintenance_confirmed.html', context)
    
    success, result = send_email_via_brevo(
        to_email=schedule.assigned_to.email,
        subject=f"Maintenance Confirmed: {schedule.title}",
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )
    
    if success:
        log_activity(
            schedule,
            MaintenanceActivityLog.Action.EMAIL_SENT,
            None,
            {'recipient': schedule.assigned_to.email, 'type': 'confirmation'}
        )
    else:
        logger.error(f"Failed to send confirmation email for schedule {schedule.pk}: {result}")

