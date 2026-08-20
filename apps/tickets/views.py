import random, hashlib, os, re, csv, json
from datetime import datetime, timedelta, date
from decimal import Decimal, InvalidOperation
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.management import call_command
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Count, Avg, Q, F, Value
from django.db import transaction, IntegrityError
from django.db.models.functions import TruncDate, Concat
from django.utils import timezone
from django.utils.html import strip_tags
from django.urls import reverse
from django.template.loader import render_to_string
from apps.common.utils import send_email_via_brevo, role_of
from django.conf import settings
from .forms import TicketForm, IncidentReportForm, ServiceRequestForm, CommentForm, AssetForm, MobilizationForm, ProcurementRequestForm
from .service_request_fields import build_service_request_details, fields_for_group, display_value_for_field
from .models import *
from apps.tickets.models import Asset
from apps.maintenance.models import Vendor, MaintenanceAssetConfirmation, MaintenanceSchedule
from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.permissions import is_admin, get_sidebar_template
from bs4 import BeautifulSoup
import bleach


import logging
logger = logging.getLogger(__name__)

# ==========================================================================
# HELPER FUNCTIONS
# ==========================================================================

_COMMENT_ALLOWED_TAGS = [
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li', 'a',
    'blockquote', 'code', 'pre', 'div', 'span',
]
_COMMENT_ALLOWED_ATTRS = {
    'a': ['href', 'title', 'target', 'rel'],
}
_COMMENT_ALLOWED_PROTOCOLS = ['http', 'https', 'mailto']


def clean_comment_body(body):
    """
    Sanitizes HTML content from the rich text editor before saving, using an
    allowlist (bleach) rather than trying to blocklist dangerous markup —
    strips anything not in _COMMENT_ALLOWED_TAGS/_COMMENT_ALLOWED_ATTRS
    entirely (script tags, event-handler attributes like onerror=,
    javascript:/data: URIs, iframe/style, etc.), then applies the same
    empty-tag cleanup and whitespace collapsing as before.
    Returns None if the cleaned body is empty (used to reject empty comments).
    """
    if not body:
        return None

    sanitized = bleach.clean(
        body,
        tags=_COMMENT_ALLOWED_TAGS,
        attributes=_COMMENT_ALLOWED_ATTRS,
        protocols=_COMMENT_ALLOWED_PROTOCOLS,
        strip=True,
    )

    soup = BeautifulSoup(sanitized, 'html.parser')

    # Remove empty block tags that contain no text and no formatting children
    for tag in soup.find_all():
        if tag.name in ['div', 'p', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            if not tag.get_text(strip=True) and not tag.find_all(['strong', 'em', 'br']):
                tag.decompose()

    # Replace <br> with newline characters (they will be turned back into <br> by linebreaksbr filter)
    for br in soup.find_all('br'):
        br.replace_with('\n')

    cleaned = str(soup)
    cleaned = re.sub(r'\n\s*\n+', '\n', cleaned)
    cleaned = cleaned.strip()

    if not cleaned or cleaned == '':
        return None
    return cleaned

# get_sidebar_template is imported from apps.common.permissions (see top of file).

# apps/tickets/views.py - Fix apply_sla

def apply_sla(ticket):
    """
    Sets the response_due_at and resolution_due_at fields on a ticket
    based on the SLA policy configured for its priority.
    Called after ticket creation and when priority changes.
    """
    try:
        sla = SLA.objects.get(priority=ticket.priority)
    except SLA.DoesNotExist:
        return
    
    # Use the ticket's created_at as the start time
    # If created_at is None or in the future, use timezone.now()
    start_time = ticket.created_at if ticket.created_at and ticket.created_at <= timezone.now() else timezone.now()
    
    ticket.response_due_at = start_time + timedelta(minutes=sla.response_minutes)
    ticket.resolution_due_at = start_time + timedelta(minutes=sla.resolution_minutes)
    ticket.save(update_fields=['response_due_at', 'resolution_due_at'])

# Helper function to handle "Other" field logic
def get_other_value(data, select_field, other_field, default_value):
    """Helper to handle 'Other' field logic for asset forms."""
    value = data.get(select_field)
    if value == 'OTHER':
        other_val = data.get(other_field, '').strip()
        return other_val if other_val else default_value
    return value

# Allowed MIME types for file attachments
ALLOWED_MIMES = [
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
    'application/zip',
]
MAX_SIZE_MB = 10

def save_attachments(ticket, files, author, comment=None):
    """
    Validates and saves uploaded file attachments.
    - Skips files that exceed MAX_SIZE_MB or have disallowed MIME types.
    - Computes SHA-256 hash for integrity checking.
    - Associates attachments with a ticket and optionally a specific comment.
    Returns list of created Attachment objects.
    """
    created = []
    for f in files:
        if f.size > MAX_SIZE_MB * 1024 * 1024:
            continue
        mime = f.content_type.split(';')[0].strip().lower()
        if mime not in ALLOWED_MIMES:
            continue
        sha = hashlib.sha256()
        for chunk in f.chunks():
            sha.update(chunk)
        f.seek(0)
        att = Attachment.objects.create(
            ticket=ticket,
            comment=comment,
            file=f,
            filename=f.name,
            uploaded_by=author,
            content_type=mime,
            size=f.size,
            hash=sha.hexdigest(),
        )
        created.append(att)
    return created

# ==========================================================================
# TICKET CREATION & LISTING VIEWS (End Users)
# ==========================================================================

# apps/tickets/views.py
import random
from django.contrib import messages

@login_required
def create_ticket(request):
    """
    Handles creation of a new ticket (incident or service request).
    - GET: displays the appropriate form (incident_form or service_request_form).
    - POST: validates form, generates a unique ticket number, saves ticket,
            attaches files, applies SLA, and redirects to ticket detail page.
    """
    # The form templates submit type as a hidden POST field (see
    # requester/service_request_form.html) — on a real form submission this
    # coincidentally also matched request.GET because the browser posts back
    # to the same "?type=..." URL it loaded, but that isn't guaranteed (a
    # bare test-client POST, a stripped query string, a JS-driven submit),
    # so read POST first and only fall back to GET for the initial page load.
    if request.method == 'POST':
        ticket_type = request.POST.get('type', request.GET.get('type', 'INCIDENT')).upper()
    else:
        ticket_type = request.GET.get('type', 'INCIDENT').upper()
    if ticket_type not in ['INCIDENT', 'SERVICE_REQUEST']:
        ticket_type = 'INCIDENT'

    if ticket_type == 'INCIDENT':
        FormClass = IncidentReportForm
    else:
        FormClass = ServiceRequestForm

    if request.method == 'POST':
        form = FormClass(request.POST)
        service_request_details = {}

        if form.is_valid() and ticket_type == 'SERVICE_REQUEST':
            service_category = form.cleaned_data.get('service_category')
            field_group = service_category.field_group if service_category else ServiceCategory.FieldGroup.GENERAL
            service_request_details, detail_errors = build_service_request_details(field_group, request.POST)
            for message_text in detail_errors.values():
                form.add_error(None, message_text)

        if not form.errors:
            ticket = form.save(commit=False)
            ticket.requester = request.user
            ticket.type = ticket_type
            if ticket_type == 'SERVICE_REQUEST':
                ticket.service_request_details = service_request_details

            notify_admins_new_job_number = None
            if ticket_type == 'SERVICE_REQUEST':
                job_number_selection = request.POST.get('job_number')
                new_job_number_text = (request.POST.get('new_job_number_text') or '').strip()
                if job_number_selection == 'NEW' and new_job_number_text:
                    job_number_obj, job_number_created = JobNumber.objects.get_or_create(
                        number=new_job_number_text,
                        defaults={'is_active': False, 'proposed_by': request.user},
                    )
                    ticket.job_number = job_number_obj
                    if job_number_created:
                        notify_admins_new_job_number = job_number_obj
                elif job_number_selection:
                    ticket.job_number = JobNumber.objects.filter(pk=job_number_selection, is_active=True).first()

                lat = request.POST.get('submission_latitude') or None
                lon = request.POST.get('submission_longitude') or None
                try:
                    ticket.submission_latitude = Decimal(lat) if lat else None
                    ticket.submission_longitude = Decimal(lon) if lon else None
                except (InvalidOperation, ValueError, TypeError):
                    ticket.submission_latitude = ticket.submission_longitude = None
                ticket.submission_location_address = (request.POST.get('submission_location_address') or '').strip()[:255]

            # Generate unique ticket number (e.g., TK#1234 or SRV#5678)
            prefix = 'TK' if ticket.type == Ticket.Type.INCIDENT else 'SRV'
            for _ in range(20):
                suffix = str(random.randint(0, 9999)).zfill(4)
                candidate = f"{prefix}#{suffix}"
                if not Ticket.objects.filter(number=candidate).exists():
                    ticket.number = candidate
                    break
            else:
                import time
                ticket.number = f"{prefix}#{int(time.time()) % 10000:04d}"

            ticket.save()
            if ticket_type == 'SERVICE_REQUEST':
                form.save_m2m()  # persists the `vessels`/`dive_systems` selections

            if notify_admins_new_job_number is not None:
                for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
                    Notification.objects.create(
                        recipient=admin,
                        role=role_of(admin),
                        message=(
                            f'{request.user.get_full_name()} submitted service request {ticket.number} for job '
                            f'"{notify_admins_new_job_number.number}", which isn\'t in the system yet. Review and '
                            f'activate it under System Settings → Job Numbers if it should be added.'
                        ),
                        url=reverse('tickets:conversation', args=[ticket.pk]),
                    )

            files = request.FILES.getlist('attachments')
            if files:
                save_attachments(ticket, files, request.user)

            # If it's a service request, set status to PENDING_MANAGER_REVIEW
            if ticket.type == Ticket.Type.SERVICE_REQUEST:
                ticket.status = Ticket.Status.PENDING_MANAGER_REVIEW

                if ticket.service_category and ticket.service_category.field_group == ServiceCategory.FieldGroup.ASSET:
                    ticket.is_asset_request = True
                    ticket.is_mobilization_request = request.POST.get('is_mobilization_request') == 'on'

                ticket.save(update_fields=['status', 'is_asset_request', 'is_mobilization_request'])

                messages.success(request, f'Service request {ticket.number} submitted for manager review.')
            else:
                messages.success(request, f'Ticket {ticket.number} created successfully.')

            apply_sla(ticket)

            # Submission is a normal full-page POST-redirect, not AJAX, so
            # there's no client-side "after submit" hook to fire a discard
            # request before the browser navigates away — clear the draft
            # here instead.
            TicketDraft.objects.filter(user=request.user, ticket_type=ticket_type).delete()

            return redirect('tickets:detail', pk=ticket.pk)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = FormClass(initial={'type': ticket_type})

    template = 'requester/incident_form.html' if ticket_type == 'INCIDENT' else 'requester/service_request_form.html'
    context = {'form': form, 'ticket_type': ticket_type}
    if ticket_type == 'SERVICE_REQUEST':
        from .service_request_fields import DYNAMIC_FIELDS_BY_GROUP
        context['dynamic_fields_by_group'] = DYNAMIC_FIELDS_BY_GROUP
        context['vessels'] = Vessel.objects.filter(is_active=True)
        context['selected_vessels'] = set(request.POST.getlist('vessels')) if request.method == 'POST' else set()
        context['dive_systems'] = DiveSystem.objects.filter(is_active=True)
        context['selected_dive_systems'] = set(request.POST.getlist('dive_systems')) if request.method == 'POST' else set()
        context['job_numbers'] = JobNumber.objects.filter(is_active=True)
    return render(request, template, context)

@login_required
@require_POST
def cancel_ticket(request, pk):
    """
    Allows an end user to cancel a ticket that is still in NEW or TRIAGED status.
    - Closes the ticket and logs the action.
    - If the request is HTMX, returns the updated ticket list partial.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user != ticket.requester:
        return HttpResponse(status=403)
    if ticket.status not in [Ticket.Status.NEW, Ticket.Status.TRIAGED]:
        return HttpResponse(status=400)
    ticket.status = Ticket.Status.CLOSED
    ticket.save()
    TicketActivityLog.objects.create(
        ticket=ticket, action='status_changed', actor=request.user,
        details={'from': ticket.status, 'to': Ticket.Status.CLOSED, 'reason': 'Cancelled by requester'}
    )
    messages.success(request, f'Ticket {ticket.number} cancelled.')
    if request.headers.get('HX-Request'):
        tickets = Ticket.objects.filter(requester=request.user).order_by('-created_at')
        status_filter = request.POST.get('current_status', '')
        if status_filter and status_filter.upper() in dict(Ticket.Status.choices):
            tickets = tickets.filter(status=status_filter.upper())
        paginator = Paginator(tickets, 10)
        page_number = request.POST.get('page', 1)
        try:
            page_obj = paginator.page(page_number)
        except (PageNotAnInteger, EmptyPage):
            page_obj = paginator.page(1)
        context = {
            'tickets': page_obj,
            'current_status': status_filter,
            'status_choices': Ticket.Status.choices,
        }
        return render(request, 'partials/ticket_list_partial.html', context)
    return redirect('tickets:my_list')

# apps/tickets/views.py - my_ticket_list

@login_required
def my_ticket_list(request):
    """
    Displays a list of tickets created by the logged‑in end user.
    Supports filtering by status (OPEN/CLOSED or specific status).
    Uses URL parameters for filter persistence.
    """
    tickets = Ticket.objects.filter(requester=request.user).order_by('-created_at')
    
    # Get filter parameters from URL
    status_filter = request.GET.get('status', '')
    base = request.GET.get('base', '')
    
    open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR', 'APPROVED']
    closed_statuses = ['RESOLVED', 'CLOSED']

    if status_filter == 'OPEN':
        tickets = tickets.filter(status__in=open_statuses)
    elif status_filter == 'CLOSED':
        tickets = tickets.filter(status__in=closed_statuses)
    elif status_filter and status_filter.upper() in dict(Ticket.Status.choices):
        tickets = tickets.filter(status=status_filter.upper())

    # Pagination
    paginator = Paginator(tickets, 10)
    page_number = request.GET.get('page', 1)
    try:
        page_obj = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    # Build status choices based on base filter
    all_choices = Ticket.Status.choices
    if base == 'OPEN':
        status_choices = [
            ('NEW', 'New'), ('TRIAGED', 'Triaged'), ('ASSIGNED', 'Assigned'),
            ('IN_PROGRESS', 'In Progress'), ('PENDING_USER', 'Pending User'),
            ('PENDING_VENDOR', 'Pending Vendor'), ('APPROVED', 'Approved')
        ]
    elif base == 'CLOSED':
        status_choices = [('RESOLVED', 'Resolved'), ('CLOSED', 'Closed')]
    else:
        status_choices = all_choices

    base_status = base if base in ['OPEN', 'CLOSED'] else ''
    explicit = request.GET.get('explicit') == '1'

    # Pass selected_status to template
    context = {
        'tickets': page_obj,
        'current_status': status_filter or '',
        'selected_status': status_filter or '',  # For highlighting active chip
        'status_choices': status_choices,
        'sidebar_template': get_sidebar_template(request.user),
        'base_status': base_status,
        'explicit': explicit,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/ticket_list_partial.html', context)
    return render(request, 'requester/ticket_list.html', context)

@login_required
def ticket_detail(request, pk):
    """
    Unified ticket conversation page for both requesters and agents.
    - GET: displays the conversation timeline and comment form.
    - POST (HTMX): accepts a new public comment from the requester,
      cleans the HTML body, saves attachments, updates ticket status if needed,
      and returns the updated timeline partial.
    The 'is_agent' flag controls visibility of agent‑only UI elements.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user != ticket.requester and request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return redirect('dashboard')

    # Handle comment submission from requester
    if request.method == 'POST' and request.headers.get('HX-Request'):
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.ticket = ticket
            comment.author = request.user
            comment.visibility = 'PUBLIC'
            cleaned_body = clean_comment_body(comment.body)
            if cleaned_body is None:
                return HttpResponse(status=400)   # empty message
            comment.body = cleaned_body
            comment.save()

            files = request.FILES.getlist('attachments')
            if files:
                save_attachments(ticket, files, request.user, comment=comment)

            if ticket.status == Ticket.Status.PENDING_USER:
                ticket.status = Ticket.Status.IN_PROGRESS
                ticket.save()
                TicketActivityLog.objects.create(
                    ticket=ticket, action='status_changed', actor=request.user,
                    details={'from': Ticket.Status.PENDING_USER, 'to': Ticket.Status.IN_PROGRESS}
                )

            comments = ticket.comments.prefetch_related('attachment_set').all().order_by('created_at')
            initial_attachments = ticket.attachments.filter(comment__isnull=True)
            return render(request, 'partials/conversation_timeline.html', {
                'ticket': ticket,
                'comments': comments,
                'initial_attachments': initial_attachments,
            })
        else:
            return HttpResponse(status=422)

    # GET request – render conversation page
    comments = ticket.comments.all().order_by('created_at')
    initial_attachments = ticket.attachments.filter(comment__isnull=True)
    user_attachments = ticket.attachments.filter(uploaded_by__role='END_USER')
    agent_attachments = ticket.attachments.filter(
        uploaded_by__role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    )
    form = CommentForm()
    is_agent = request.user.role in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']

    return render(request, 'agent/ticket_conversation.html', {
        'ticket': ticket,
        'comments': comments,
        'form': form,
        'initial_attachments': initial_attachments,
        'user_attachments': user_attachments,
        'agent_attachments': agent_attachments,
        'sidebar_template': get_sidebar_template(request.user),
        'is_agent': is_agent,
    })

# ==========================================================================
# AGENT QUEUES & TICKET MANAGEMENT
# ==========================================================================

@login_required
def unassigned_queue(request):
    """
    Displays all unassigned tickets that are ready for agents to claim.
    """
    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] or request.user.department != 'IT':
        return HttpResponse(status=403)

    # Get all unassigned tickets
    tickets = Ticket.objects.filter(
        assigned_to__isnull=True
    ).order_by('-created_at')
    
    # ================================================================
    # 🔥 Filter: Show INCIDENTS + APPROVED SERVICE REQUESTS
    # ================================================================
    tickets = tickets.filter(
        Q(type=Ticket.Type.INCIDENT) |
        (Q(type=Ticket.Type.SERVICE_REQUEST) & Q(status=Ticket.Status.APPROVED))
    )
    
    # Exclude tickets that shouldn't be in the queue
    tickets = tickets.exclude(
        status__in=[
            Ticket.Status.PENDING_MANAGER_REVIEW,
            Ticket.Status.PENDING_FULFILLMENT,
            Ticket.Status.PENDING_APPROVAL,
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
        ]
    )

    assignable_agents = User.objects.filter(
        role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'],
        department='IT',  # ✅ Only IT department
        is_active=True
    ).only('pk', 'first_name', 'last_name', 'email')

    context = {
        'tickets': tickets,
        'assignable_agents': assignable_agents,
        'status_choices': Ticket.Status.choices,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'agent/unassigned_queue.html', context)

@login_required
def assigned_to_me(request):
    """
    Displays all tickets assigned to the logged‑in agent,
    excluding resolved, closed, and pending approval tickets.
    """
    if request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] or request.user.department != 'IT':
        return HttpResponse(status=403)

    tickets = Ticket.objects.filter(
        assigned_to=request.user
    ).exclude(
        status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED, Ticket.Status.PENDING_APPROVAL, Ticket.Status.PENDING_MANAGER_REVIEW]
    ).order_by('-created_at')

    assignable_agents = User.objects.filter(
        role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'],
        department='IT',  # ✅ Only IT department
        is_active=True
    ).only('pk', 'first_name', 'last_name', 'email')

    context = {
        'tickets': tickets,
        'assignable_agents': assignable_agents,
        'status_choices': Ticket.Status.choices,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'agent/assigned_to_me.html', context)

from django.template.loader import render_to_string
from django.http import JsonResponse

# apps/tickets/views.py - Update claim_ticket

@login_required
def claim_ticket(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    source = request.POST.get('source', 'unassigned')
    
    if ticket.assigned_to is None:
        # Assign ticket to current user
        ticket.assigned_to = request.user
        ticket.status = Ticket.Status.ASSIGNED
        ticket.save()
        
        # Log the assignment
        TicketActivityLog.objects.create(
            ticket=ticket, action='assigned', actor=request.user,
            details={'to': request.user.get_full_name(), 'status': ticket.status}
        )
        
        # Create notifications
        Notification.objects.create(
            recipient=request.user,
            role=role_of(request.user),
            message=f"✅ You have claimed ticket {ticket.number}: {ticket.title}",
            url=reverse('tickets:conversation', args=[ticket.pk]),
            type=Notification.Type.TICKET
        )
        
        Notification.objects.create(
            recipient=ticket.requester,
            role=role_of(ticket.requester),
            message=f"🎫 Ticket {ticket.number} has been claimed by {request.user.get_full_name()} and is now in progress.",
            url=reverse('tickets:detail', args=[ticket.pk]),
            type=Notification.Type.TICKET
        )
        
        # ALWAYS return JSON for API-like requests
        # Check if the request is from HTMX or a form
        if request.headers.get('HX-Request'):
            # For HTMX requests, return HTML
            assignable_agents = User.objects.filter(
                role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
            ).only('pk', 'first_name', 'last_name', 'email')
            
            unassigned_tickets = Ticket.objects.filter(
                assigned_to__isnull=True
            ).exclude(
                status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED, Ticket.Status.PENDING_APPROVAL,
                            Ticket.Status.PENDING_MANAGER_REVIEW, Ticket.Status.PENDING_FULFILLMENT,
                            Ticket.Status.PENDING_VENDOR]
            ).order_by('-created_at')
            
            if source == 'dashboard':
                unassigned_tickets = unassigned_tickets[:5]
                return JsonResponse({
                    'success': True,
                    'message': f'✅ Successfully claimed ticket {ticket.number}',
                    'unassigned_count': unassigned_tickets.count(),
                })
            else:
                return render(request, 'partials/agent_ticket_table.html', {
                    'tickets': unassigned_tickets,
                    'assignable_agents': assignable_agents,
                    'status_choices': Ticket.Status.choices,
                    'source': source,
                })
        else:
            # For JSON requests, return JSON
            return JsonResponse({
                'success': True,
                'message': f'✅ Successfully claimed ticket {ticket.number}',
                'ticket_id': ticket.pk,
                'ticket_number': ticket.number,
            })
    
    # If ticket is already assigned
    return JsonResponse({
        'success': False,
        'message': 'Ticket is already assigned to someone else.'
    }, status=400)

@login_required
def agent_ticket_detail(request, pk):
    """
    Returns a slide‑over panel with ticket details and comments.
    Used when an agent clicks the "eye" icon on a ticket row.
    """ 
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user.role not in [User.Role.AGENT, User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)
    comments = ticket.comments.all().order_by('created_at')
    user_attachments = ticket.attachments.filter(uploaded_by__role='END_USER')
    agent_attachments = ticket.attachments.filter(
        uploaded_by__role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    )
    return render(request, 'partials/ticket_slideover.html', {
        'ticket': ticket,
        'comments': comments,
        'user_attachments': user_attachments,
        'agent_attachments': agent_attachments,
    })

@login_required
def agent_ticket_conversation(request, pk):
    """
    Full‑page conversation view for agents (and admins).
    Renders the same template as ticket_detail but with is_agent=True.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user.role not in [User.Role.AGENT, User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)
    comments = ticket.comments.all().order_by('created_at')
    form = CommentForm()
    initial_attachments = ticket.attachments.filter(comment__isnull=True)
    user_attachments = ticket.attachments.filter(uploaded_by__role='END_USER')
    agent_attachments = ticket.attachments.filter(
        uploaded_by__role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    )
    manual_status_choices = [
        (value, label) for value, label in Ticket.Status.choices
        if value in MANUALLY_SETTABLE_STATUSES
    ]
    return render(request, 'agent/ticket_conversation.html', {
        'ticket': ticket,
        'comments': comments,
        'form': form,
        'initial_attachments': initial_attachments,
        'user_attachments': user_attachments,
        'agent_attachments': agent_attachments,
        'sidebar_template': get_sidebar_template(request.user),
        'is_agent': True,
        'manual_status_choices': manual_status_choices,
        'status_is_manually_editable': ticket.status in MANUALLY_SETTABLE_STATUSES,
    })

@login_required
@require_POST
def add_comment_conversation(request, pk):
    """
    Handles agent comments (public or internal) on a ticket.
    - Cleans the HTML body using BeautifulSoup.
    - Saves attachments.
    - Updates ticket status to IN_PROGRESS if a public comment is added.
    - Returns the updated conversation timeline partial (HTMX).
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.ticket = ticket
        comment.author = request.user
        comment.visibility = request.POST.get('visibility', 'PUBLIC').upper()
        if comment.visibility not in ['PUBLIC', 'INTERNAL']:
            comment.visibility = 'PUBLIC'
        cleaned_body = clean_comment_body(comment.body)
        if cleaned_body is None:
            return HttpResponse(status=400)
        comment.body = cleaned_body
        comment.save()

        files = request.FILES.getlist('attachments')
        if files:
            created = save_attachments(ticket, files, request.user, comment=comment)
            comment = TicketComment.objects.get(pk=comment.pk)

        TicketActivityLog.objects.create(
            ticket=ticket, action='commented', actor=request.user,
            details={'visibility': comment.visibility, 'body': comment.body[:200]}
        )

        old_status = ticket.status
        if comment.visibility == 'PUBLIC':
            if old_status in [Ticket.Status.ASSIGNED, Ticket.Status.IN_PROGRESS,
                              Ticket.Status.PENDING_USER, Ticket.Status.NEW, Ticket.Status.TRIAGED]:
                ticket.status = Ticket.Status.IN_PROGRESS
                ticket.save()
                if old_status != ticket.status:
                    TicketActivityLog.objects.create(
                        ticket=ticket, action='status_changed', actor=request.user,
                        details={'from': old_status, 'to': ticket.status}
                    )

    comments = ticket.comments.prefetch_related('attachment_set').all().order_by('created_at')
    initial_attachments = ticket.attachments.filter(comment__isnull=True)
    return render(request, 'partials/conversation_timeline.html', {
        'ticket': ticket,
        'comments': comments,
        'initial_attachments': initial_attachments, 
    })

# The manual status dropdown on the ticket conversation page is only for
# the day-to-day "working" states an agent moves a ticket through by hand.
# Everything else (Resolved, Closed, Approved, Pending Manager Review,
# Pending Fulfillment, Pending Approval) is owned by a dedicated, guarded
# flow (Resolve button, manager review, asset fulfillment, approval) and
# must not be reachable by picking it off this dropdown — that would let an
# agent skip the automated lifecycle those flows enforce.
MANUALLY_SETTABLE_STATUSES = {
    Ticket.Status.NEW, Ticket.Status.TRIAGED, Ticket.Status.ASSIGNED,
    Ticket.Status.IN_PROGRESS, Ticket.Status.PENDING_USER,
    Ticket.Status.PENDING_VENDOR, Ticket.Status.ESCALATED,
}


@login_required
@require_POST
def update_status(request, pk):
    """
    Changes the status of a ticket. Only agents, team leads, admins, and superadmins can do this.
    The new status is passed as a GET parameter 'status'.
    Logs the change in TicketActivityLog.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user.role not in [User.Role.AGENT, User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)

    previous_status = ticket.status
    new_status = request.GET.get('status')

    if not new_status or new_status not in dict(Ticket.Status.choices):
        return JsonResponse({'error': 'Unknown status.'}, status=400)

    if previous_status not in MANUALLY_SETTABLE_STATUSES or new_status not in MANUALLY_SETTABLE_STATUSES:
        return JsonResponse({
            'error': 'This transition is managed by the ticket workflow (resolve, manager review, or fulfillment) and cannot be set manually.'
        }, status=400)

    ticket.status = new_status
    ticket.save()
    TicketActivityLog.objects.create(
        ticket=ticket, action='status_changed', actor=request.user,
        details={'from': previous_status, 'to': new_status}
    )
    return HttpResponse(status=204)

@login_required
@require_http_methods(['GET', 'POST'])
def resolve_ticket(request, pk):
    """
    Initiates the resolve confirmation flow.
    - GET: Returns the resolve modal (HTMX)
    - POST: Processes the resolution confirmation
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user.role not in [User.Role.AGENT, User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)
    
    # Check if ticket is already resolved
    if ticket.status in [Ticket.Status.RESOLVED, Ticket.Status.CLOSED]:
        if request.headers.get('HX-Request'):
            return HttpResponse('<div class="p-4 text-center"><p class="text-text-secondary">This ticket is already resolved.</p></div>')
        messages.warning(request, 'Ticket is already resolved or closed.')
        return redirect('tickets:conversation', pk=ticket.pk)
    
    # GET request - return the modal (HTMX)
    if request.method == 'GET' and request.headers.get('HX-Request'):
        return render(request, 'partials/resolve_modal.html', {'ticket': ticket})
    
    # POST request - process confirmation
    if request.method == 'POST':
        action = request.POST.get('action')
        comment = request.POST.get('comment', '').strip()
        root_cause = request.POST.get('resolution_root_cause', '').strip()
        resolution_steps = request.POST.get('resolution_steps', '').strip()
        valid_root_cause_categories = dict(Ticket.RootCauseCategory.choices)
        root_cause_categories = [
            c for c in request.POST.getlist('resolution_root_cause_category') if c in valid_root_cause_categories
        ]

        if action == 'confirm':
            if ticket.is_asset_request and ticket.resolution_confirmed_at:
                # The requester already confirmed they received the
                # asset(s) (confirm_resolution) — no need to send it back
                # to them a second time. Resolve directly, no modal round-trip.
                ticket.status = Ticket.Status.RESOLVED
                ticket.resolved_at = timezone.now()
                ticket.save()

                TicketActivityLog.objects.create(
                    ticket=ticket, action='resolved', actor=request.user,
                    details={'comment': comment, 'note': 'receipt already confirmed by requester'}
                )
                TicketComment.objects.create(
                    ticket=ticket, author=request.user, visibility='PUBLIC',
                    body=f"✅ **Resolved**.{' ' + comment if comment else ''}"
                )
                messages.success(request, f'Ticket {ticket.number} resolved.')
                return redirect('tickets:conversation', pk=ticket.pk)

            if ticket.type == Ticket.Type.INCIDENT and (not root_cause or not resolution_steps):
                messages.error(request, 'Root Cause and Resolution Steps are required to resolve an Incident ticket.')
                return redirect('tickets:conversation', pk=ticket.pk)

            # Create resolution request
            ticket.status = Ticket.Status.PENDING_USER
            ticket.resolution_root_cause = root_cause
            ticket.resolution_steps = resolution_steps
            ticket.resolution_root_cause_category = root_cause_categories
            ticket.save()
            
            # Create activity log
            TicketActivityLog.objects.create(
                ticket=ticket,
                action='resolution_requested',
                actor=request.user,
                details={'comment': comment}
            )
            
            # Add system comment to ticket
            TicketComment.objects.create(
                ticket=ticket,
                author=request.user,
                body=f"🔄 **Resolution requested**: Please confirm if this ticket has been resolved.{' ' + comment if comment else ''}",
                visibility='PUBLIC'
            )
            
            # Send notification to requester
            Notification.objects.create(
                recipient=ticket.requester,
                role=role_of(ticket.requester),
                message=f"Please confirm if ticket {ticket.number} has been resolved.",
                url=reverse('tickets:confirm_resolution', args=[ticket.pk]),
                type=Notification.Type.RESOLUTION_CONFIRMATION
            )
            
            # Send email to requester
            confirm_url = request.build_absolute_uri(
                reverse('tickets:confirm_resolution', args=[ticket.pk])
            )
            html_message = render_to_string('emails/resolution_confirmation.html', {
                'requester_name': ticket.requester.get_full_name() or ticket.requester.email,
                'ticket_number': ticket.number,
                'ticket_title': ticket.title,
                'confirm_url': confirm_url,
                'agent_name': request.user.get_full_name() or request.user.email,
            })
            
            success, result = send_email_via_brevo(
                to_email=ticket.requester.email,
                subject=f"Please confirm resolution for ticket {ticket.number}",
                html_content=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL
            )
            
            if not success:
                logger.error(f"Failed to send resolution confirmation email: {result}")
            
            messages.success(request, f'Resolution confirmation sent to {ticket.requester.get_full_name()}.')
            return redirect('tickets:conversation', pk=ticket.pk)
        
        elif action == 'cancel':
            return redirect('tickets:conversation', pk=ticket.pk)

    return HttpResponse(status=400)


@login_required
@require_POST
def approve_incident_report(request, pk):
    """
    IT Manager / Head of IT sign-off on a resolved Incident's report.
    Merged approval: this app has no separate IT Manager role distinct from
    Admin, and IT is the highest approval authority for incident reports —
    one approval satisfies both the "Reviewed By" and "Approved By" rows.
    """
    ticket = get_object_or_404(Ticket, pk=pk)

    if request.user.role not in [User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)

    if ticket.type != Ticket.Type.INCIDENT or ticket.status not in [Ticket.Status.RESOLVED, Ticket.Status.CLOSED]:
        messages.error(request, 'Only resolved or closed Incident tickets can be approved.')
        return redirect('tickets:report_record_detail', report_type='incidents', pk=ticket.pk)

    if ticket.incident_approved_by:
        messages.info(request, f'Ticket {ticket.number} has already been approved.')
        return redirect('tickets:report_record_detail', report_type='incidents', pk=ticket.pk)

    ticket.incident_approved_by = request.user
    ticket.incident_approved_at = timezone.now()
    ticket.save()

    TicketActivityLog.objects.create(
        ticket=ticket,
        action='incident_report_approved',
        actor=request.user,
    )

    messages.success(request, f'Incident report for {ticket.number} approved.')
    return redirect('tickets:report_record_detail', report_type='incidents', pk=ticket.pk)


@login_required
def confirm_resolution(request, pk):
    """
    Page where requester confirms if ticket is resolved.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    
    # Security: only requester can confirm
    if request.user != ticket.requester:
        return HttpResponse(status=403)
    
    # Check if ticket is in pending user state (waiting for confirmation)
    if ticket.status != Ticket.Status.PENDING_USER:
        messages.warning(request, f'Ticket {ticket.number} is not awaiting resolution confirmation.')
        return redirect('tickets:detail', pk=ticket.pk)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        reason = request.POST.get('reason', '').strip()

        if action == 'confirm':
            ticket.resolution_confirmed_at = timezone.now()
            ticket.resolution_confirmed_by = request.user

            if ticket.is_asset_request:
                # Confirming receipt isn't the same as the ticket being
                # resolved — an agent still explicitly resolves it
                # afterward (resolve_ticket skips its own confirmation
                # round-trip once it sees resolution_confirmed_at is set).
                ticket.status = Ticket.Status.APPROVED
                ticket.save()

                TicketActivityLog.objects.create(
                    ticket=ticket,
                    action='receipt_confirmed',
                    actor=request.user,
                    details={'confirmed_at': ticket.resolution_confirmed_at.isoformat()}
                )
                TicketComment.objects.create(
                    ticket=ticket,
                    author=request.user,
                    body="✅ **Receipt confirmed**. The requester has received the asset(s).",
                    visibility='PUBLIC'
                )
                messages.success(request, 'Thank you for confirming! Please rate your experience.')
                return redirect('tickets:submit_feedback', pk=ticket.pk)

            # Non-asset (Incident/general) tickets: confirming resolves it
            # directly, same as today.
            ticket.status = Ticket.Status.RESOLVED
            ticket.resolved_at = timezone.now()
            ticket.save()

            TicketActivityLog.objects.create(
                ticket=ticket,
                action='resolution_confirmed',
                actor=request.user,
                details={'confirmed_at': ticket.resolution_confirmed_at.isoformat()}
            )

            TicketComment.objects.create(
                ticket=ticket,
                author=request.user,
                body="✅ **Resolution confirmed**. The issue has been resolved.",
                visibility='PUBLIC'
            )

            messages.success(request, 'Thank you for confirming! Please rate your experience.')
            return redirect('tickets:submit_feedback', pk=ticket.pk)

        elif action == 'reopen':
            TicketActivityLog.objects.create(
                ticket=ticket,
                action='resolution_rejected',
                actor=request.user,
                details={'reason': reason}
            )

            if ticket.is_asset_request:
                # Back to the fulfillment queue for correction (wrong item,
                # missing item, etc.) rather than a generic "in progress".
                ticket.status = Ticket.Status.PENDING_FULFILLMENT
                ticket.save()

                TicketComment.objects.create(
                    ticket=ticket,
                    author=request.user,
                    body=f"❌ **Not received**. The requester says the asset(s) weren't received as expected.{' Reason: ' + reason if reason else ''}",
                    visibility='PUBLIC'
                )

                if ticket.fulfilled_by:
                    Notification.objects.create(
                        recipient=ticket.fulfilled_by,
                        role=role_of(ticket.fulfilled_by),
                        message=f"{ticket.requester.get_full_name()} says request {ticket.number} wasn't received as expected.{' Reason: ' + reason if reason else ''}",
                        url=reverse('tickets:conversation', args=[ticket.pk])
                    )

                messages.info(request, f'Ticket {ticket.number} sent back for fulfillment review.')
                return redirect('tickets:detail', pk=ticket.pk)

            # User says issue is not resolved
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.save()

            TicketComment.objects.create(
                ticket=ticket,
                author=request.user,
                body=f"❌ **Resolution rejected**. The issue is not fully resolved.{' Reason: ' + reason if reason else ''}",
                visibility='PUBLIC'
            )

            # Notify the agent who requested resolution
            last_log = TicketActivityLog.objects.filter(
                ticket=ticket,
                action='resolution_requested'
            ).order_by('-created_at').first()

            if last_log and last_log.actor:
                Notification.objects.create(
                    recipient=last_log.actor,
                    role=role_of(last_log.actor),
                    message=f"{ticket.requester.get_full_name()} rejected resolution for ticket {ticket.number}.{' Reason: ' + reason if reason else ''}",
                    url=reverse('tickets:conversation', args=[ticket.pk])
                )

            messages.info(request, f'Ticket {ticket.number} reopened for further investigation.')
            return redirect('tickets:detail', pk=ticket.pk)
        else:
            logger.warning(f"Unknown action: '{action}'")
            messages.error(request, f'Invalid action: {action}')
            return redirect('tickets:confirm_resolution', pk=ticket.pk)
    
    return render(request, 'tickets/confirm_resolution.html', {
        'ticket': ticket,
        'sidebar_template': get_sidebar_template(request.user),
    })


@login_required
def submit_feedback(request, pk):
    """
    Submit 1-5 star feedback for resolved ticket.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    
    # Security: only requester can submit feedback
    if request.user != ticket.requester:
        return HttpResponse(status=403)
    
    # Check if ticket is resolved and feedback not already submitted
    if ticket.status != Ticket.Status.RESOLVED:
        messages.warning(request, 'Feedback can only be submitted for resolved tickets.')
        return redirect('tickets:detail', pk=ticket.pk)
    
    if ticket.feedback_rating is not None:
        messages.info(request, 'You have already submitted feedback for this ticket.')
        return redirect('tickets:detail', pk=ticket.pk)
    
    if request.method == 'POST':
        rating = request.POST.get('rating')
        comment = request.POST.get('comment', '').strip()
        
        if not rating or int(rating) < 1 or int(rating) > 5:
            messages.error(request, 'Please select a rating from 1 to 5 stars.')
            return render(request, 'tickets/feedback_form.html', {
                'ticket': ticket,
                'sidebar_template': get_sidebar_template(request.user),
                'error': 'Please select a rating.'
            })
        
        ticket.feedback_rating = int(rating)
        ticket.feedback_comment = comment
        ticket.feedback_submitted_at = timezone.now()
        ticket.save()
        
        TicketActivityLog.objects.create(
            ticket=ticket,
            action='feedback_submitted',
            actor=request.user,
            details={'rating': rating, 'comment': comment}
        )
        
        # Notify the agent(s) who worked on this ticket
        assigned_log = TicketActivityLog.objects.filter(
            ticket=ticket,
            action='assigned'
        ).order_by('-created_at').first()
        
        if assigned_log and assigned_log.actor:
            star_emoji = '⭐' * int(rating) + '☆' * (5 - int(rating))
            Notification.objects.create(
                recipient=assigned_log.actor,
                role=role_of(assigned_log.actor),
                message=f"Feedback received for ticket {ticket.number}: {star_emoji} ({rating}/5)",
                url=reverse('tickets:detail', args=[ticket.pk])
            )
        
        messages.success(request, f'Thank you for your feedback! You rated this ticket {rating}/5 stars.')
        return redirect('tickets:detail', pk=ticket.pk)
    
    return render(request, 'tickets/feedback_form.html', {
        'ticket': ticket,
        'sidebar_template': get_sidebar_template(request.user),
    })

# ==========================================================================
# TICKET DETAILS PANEL & METADATA EDITING
# ==========================================================================

@login_required
def ticket_details_panel(request, pk):
    """
    Returns the right‑hand details panel (assignee, metadata, attachments)
    that slides in on the conversation page.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    followers = User.objects.filter(role__in=['AGENT','TEAM_LEAD'])[:5]
    user_attachments = ticket.attachments.filter(uploaded_by__role='END_USER')
    agent_attachments = ticket.attachments.filter(
        uploaded_by__role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    )
    return render(request, 'partials/ticket_details_panel.html', {
        'ticket': ticket,
        'followers': followers,
        'user_attachments': user_attachments,
        'agent_attachments': agent_attachments,
    })

@login_required
@require_POST
def edit_subject(request, pk):
    """
    Edits the ticket title inline (subject). Agent-tier roles only.
    Returns the updated subject display partial.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user.role not in [User.Role.AGENT, User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)
    new_title = request.POST.get('title', '').strip()
    if new_title:
        ticket.title = new_title
        ticket.save()
    return render(request, 'partials/subject_display.html', {'ticket': ticket, 'is_agent': True})

# ==========================================================================
# ASSIGNMENT POPOVERS AND ACTIONS
# ==========================================================================

@login_required
def assign_popover(request, pk):
    """
    Returns a popover with a list of assignable agents (Agent, Team Lead, Admin, Superadmin)
    so the agent can reassign the ticket.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    agents = User.objects.filter(
        role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'],
        department='IT',  # ✅ Only IT department
        is_active=True
    )[:10]
    return render(request, 'partials/popovers/assign_popover.html', {'ticket': ticket, 'agents': agents})

@login_required
@require_POST
def assign_to_me(request, pk):
    """
    Assigns the ticket to the current user.
    Returns the updated assignee display partial.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    ticket.assigned_to = request.user
    ticket.save()
    return render(request, 'partials/ticket_details_assignee.html', {'ticket': ticket})

@login_required
@require_POST
def assign_specific(request, pk, user_pk):
    """
    Assigns the ticket to a specific user (by primary key).
    Returns the updated assignee display partial.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    agent = get_object_or_404(User, pk=user_pk)
    ticket.assigned_to = agent
    ticket.save()
    return render(request, 'partials/ticket_details_assignee.html', {'ticket': ticket})

# ==========================================================================
# MACROS
# ==========================================================================

@login_required
def macro_list(request):
    """
    Returns a dropdown list of macros (predefined reply templates) for agents.
    Used in the conversation composer.
    """
    from .views_macros import visible_macros_for
    macros = visible_macros_for(request.user)
    return render(request, 'partials/macro_dropdown.html', {'macros': macros})

# ==========================================================================
# BULK ACTIONS (for ticket queues)
# ==========================================================================

@login_required
@require_POST
def bulk_action(request):
    """
    Performs bulk status change or assignment on multiple tickets.
    Only Team Leads, Admins, and Superadmins can bulk‑assign.
    Returns the updated agent ticket table partial.
    """
    ticket_ids_str = request.POST.get('ticket_ids', '')
    action = request.POST.get('action', '')
    value = request.POST.get('value', '')
    if not ticket_ids_str or not action:
        return HttpResponse(status=400)

    ids = [int(pk) for pk in ticket_ids_str.split(',') if pk.strip().isdigit()]
    tickets = Ticket.objects.filter(pk__in=ids)

    if action == 'status':
        if value in dict(Ticket.Status.choices):
            for ticket in tickets:
                old_status = ticket.status
                ticket.status = value
                ticket.save()
                TicketActivityLog.objects.create(
                    ticket=ticket, action='status_changed', actor=request.user,
                    details={'from': old_status, 'to': value, 'method': 'bulk'}
                )
                
    elif action == 'assign':
        if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
            return HttpResponse(status=403)
        if value.isdigit():
            agent = get_object_or_404(User, pk=int(value))
            actor_name = request.user.get_full_name()
            agent_name = agent.get_full_name()
            
            for ticket in tickets:
                old_assignee = ticket.assigned_to
                old_name = old_assignee.get_full_name() if old_assignee else 'Unassigned'
                
                # Reassign the ticket
                ticket.assigned_to = agent
                ticket.save()
                
                # Create activity log
                TicketActivityLog.objects.create(
                    ticket=ticket, action='assigned', actor=request.user,
                    details={'from': old_name, 'to': agent_name, 'method': 'bulk'}
                )
                
                # ================================================================
                # DEFAULT REASSIGN COMMENT (per ticket)
                # ================================================================
                TicketComment.objects.create(
                    ticket=ticket,
                    author=request.user,
                    body=f"🔄 **Bulk reassign**: Ticket reassigned by {actor_name} from **{old_name}** to **{agent_name}**.",
                    visibility='PUBLIC'
                )
            
            # Notify the agent once for all tickets
            Notification.objects.create(
                recipient=agent,
                role=role_of(agent),
                message=f"{len(tickets)} ticket(s) have been reassigned to you by {actor_name}.",
                url=reverse('tickets:unassigned')
            )

    source = request.POST.get('source', 'unassigned')
    if source == 'assigned':
        tickets = Ticket.objects.filter(
            assigned_to=request.user
        ).exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED, Ticket.Status.PENDING_APPROVAL]
        ).order_by('-created_at')
    else:
        tickets = Ticket.objects.filter(
            assigned_to__isnull=True
        ).exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
        ).order_by('-created_at')

    assignable_agents = User.objects.filter(
        role__in=['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'],
        department='IT',  # ✅ Only IT department
        is_active=True
    ).only('pk', 'first_name', 'last_name', 'email')
    return render(request, 'partials/agent_ticket_table.html', {
        'tickets': tickets,
        'assignable_agents': assignable_agents,
        'status_choices': Ticket.Status.choices,
    })

# ==========================================================================
# TEAM LEAD QUEUE & REASSIGNMENT
# ==========================================================================

@login_required
def team_queue(request):
    """
    Team Lead view: shows all tickets assigned to agents in the same department.
    Allows filtering by individual agent.
    """
    if request.user.role != 'TEAM_LEAD' or request.user.department != 'IT':
        return HttpResponse(status=403)
    team_members = User.objects.filter(
        department=request.user.department,
        role='AGENT',
        is_active=True
    )
    # Note: team_members already filtered by department from request.user
    tickets = Ticket.objects.filter(
        assigned_to__in=team_members
    ).exclude(status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED]
    ).order_by('-created_at')
    agent_id = request.GET.get('agent')
    if agent_id:
        tickets = tickets.filter(assigned_to_id=agent_id)
    context = {
        'tickets': tickets,
        'team_members': team_members,
        'selected_agent': agent_id,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'partials/team_queue.html', context)

@login_required
@require_POST
def team_reassign(request, pk):
    """
    Allows a Team Lead to reassign a ticket to another agent in their team.
    Returns JSON status.
    """
    if request.user.role != 'TEAM_LEAD':
        return HttpResponse(status=403)
    ticket = get_object_or_404(Ticket, pk=pk)
    new_agent_id = request.POST.get('agent_id')
    agent = get_object_or_404(User, pk=new_agent_id, role='AGENT')
    old_assignee = ticket.assigned_to
    
    # Store old assignee name for comment
    old_name = old_assignee.get_full_name() if old_assignee else 'Unassigned'
    new_name = agent.get_full_name()
    actor_name = request.user.get_full_name()
    
    # Reassign the ticket
    ticket.assigned_to = agent
    ticket.save()
    
    # Create activity log
    TicketActivityLog.objects.create(
        ticket=ticket, action='assigned', actor=request.user,
        details={'from': old_name, 'to': new_name}
    )
    
    # ================================================================
    # DEFAULT REASSIGN COMMENT
    # ================================================================
    TicketComment.objects.create(
        ticket=ticket,
        author=request.user,
        body=f"🔄 **Ticket reassigned** by {actor_name} from **{old_name}** to **{new_name}**.",
        visibility='PUBLIC'
    )
    
    # Notify the new agent
    Notification.objects.create(
        recipient=agent,
        role=role_of(agent),
        message=f"Ticket {ticket.number} has been reassigned to you by {actor_name}.",
        url=reverse('tickets:conversation', args=[ticket.pk])
    )
    
    return JsonResponse({'status': 'ok'})

# ==========================================================================
# AUDIT LOG
# ==========================================================================

# Category grouping for the Logs page — bucket each recorded action into a
# human-facing category so the page reads as "what area was this in" rather
# than a flat, undifferentiated table. Keep in sync with every
# TicketActivityLog.objects.create(action=...) call site.
LOG_CATEGORY_MAP = {
    'status_changed': 'Ticket Lifecycle',
    'assigned': 'Ticket Lifecycle',
    'commented': 'Ticket Lifecycle',
    'resolution_requested': 'Ticket Lifecycle',
    'resolution_confirmed': 'Ticket Lifecycle',
    'resolution_rejected': 'Ticket Lifecycle',
    'receipt_confirmed': 'Ticket Lifecycle',
    'resolved': 'Ticket Lifecycle',
    'feedback_submitted': 'Ticket Lifecycle',
    'manager_approved': 'Manager Review',
    'manager_rejected': 'Manager Review',
    'manager_requested_changes': 'Manager Review',
    'escalated': 'Escalation',
    'reassigned_escalated': 'Escalation',
    'returned_to_pool': 'Escalation',
    'remote_session_requested': 'Remote Sessions',
    'remote_session_status_change': 'Remote Sessions',
    'asset_fulfilled': 'Assets',
    'mobilization_fulfilled': 'Assets',
}
LOG_CATEGORY_ORDER = ['Ticket Lifecycle', 'Manager Review', 'Escalation', 'Remote Sessions', 'Assets', 'Other']

# Friendly labels for the JSONField keys stored in TicketActivityLog.details,
# so the Logs page can show "From: Open / To: Resolved" instead of a raw
# dict dump. Unknown keys fall back to a title-cased version of themselves.
LOG_DETAIL_LABELS = {
    'from': 'From', 'to': 'To', 'reason': 'Reason', 'method': 'Method',
    'body': 'Comment', 'visibility': 'Visibility', 'status': 'Status',
    'rating': 'Rating', 'comment': 'Feedback',
}


def _log_category(action):
    return LOG_CATEGORY_MAP.get(action, 'Other')


def _log_detail_items(details):
    """Turn a TicketActivityLog.details dict into readable (label, value) pairs."""
    if not details:
        return []
    items = []
    for key, value in details.items():
        label = LOG_DETAIL_LABELS.get(key, key.replace('_', ' ').title())
        if isinstance(value, str) and len(value) > 160:
            value = value[:160] + '…'
        items.append((label, value))
    return items


@login_required
def audit_log(request):
    if request.user.role not in ['TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] or request.user.department != 'IT':
        return HttpResponse(status=403)

    tab = request.GET.get('tab', 'tickets')
    is_admin_tier = request.user.role in ['ADMIN', 'SUPERADMIN']

    # ------------------------------------------------------------------
    # SYSTEM TAB — impersonation events. Admin/Superadmin only; previously
    # this data existed in ImpersonationLog with no UI surfacing it at all.
    # ------------------------------------------------------------------
    if tab == 'system':
        if not is_admin_tier:
            return HttpResponse(status=403)
        from apps.accounts.models import ImpersonationLog
        system_logs = ImpersonationLog.objects.select_related('admin', 'target_user').order_by('-started_at')
        paginator = Paginator(system_logs, 50)
        page_obj = paginator.get_page(request.GET.get('page', 1))
        context = {
            'tab': 'system',
            'system_logs': page_obj,
            'is_admin_tier': is_admin_tier,
            'sidebar_template': get_sidebar_template(request.user),
        }
        return render(request, 'partials/audit_log.html', context)

    # ------------------------------------------------------------------
    # TICKETS TAB — ticket activity, grouped by category.
    # ------------------------------------------------------------------
    logs = TicketActivityLog.objects.select_related('ticket', 'actor').all()
    if request.user.role == 'TEAM_LEAD':
        team_members = User.objects.filter(department=request.user.department, role='AGENT')
        logs = logs.filter(
            Q(ticket__assigned_to__in=team_members) | Q(ticket__requester__in=team_members)
        )

    action = request.GET.get('action')
    category = request.GET.get('category')
    ticket_id = request.GET.get('ticket')
    if action:
        logs = logs.filter(action=action)
    if category and category in LOG_CATEGORY_MAP.values():
        matching_actions = [a for a, c in LOG_CATEGORY_MAP.items() if c == category]
        logs = logs.filter(action__in=matching_actions)
    if ticket_id:
        logs = logs.filter(ticket__number__icontains=ticket_id)
    logs = logs.order_by('-created_at')

    # --- Export logic (CSV, JSON, Excel) ---
    export_format = request.GET.get('export')
    if export_format:
        filename = f"logs_{timezone.now().strftime('%Y%m%d_%H%M%S')}"

        # Convert each log to a flat dict for export
        export_data = []
        for log in logs:
            export_data.append({
                'time': log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'category': _log_category(log.action),
                'ticket': log.ticket.number if log.ticket else '—',
                'action': log.action,
                'actor': log.actor.get_full_name() if log.actor else 'System',
                'details': str(log.details) if log.details else ''  # Convert dict to string
            })

        if export_format == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
            writer = csv.writer(response)
            writer.writerow(['Time', 'Category', 'Ticket', 'Action', 'Actor', 'Details'])
            for row in export_data:
                writer.writerow([row['time'], row['category'], row['ticket'], row['action'], row['actor'], row['details']])
            return response

        elif export_format == 'json':
            response = HttpResponse(json.dumps(export_data, indent=2), content_type='application/json')
            response['Content-Disposition'] = f'attachment; filename="{filename}.json"'
            return response

        elif export_format == 'excel':
            wb = Workbook()
            ws = wb.active
            ws.title = "Logs"
            ws.append(['Time', 'Category', 'Ticket', 'Action', 'Actor', 'Details'])
            for row in export_data:
                ws.append([row['time'], row['category'], row['ticket'], row['action'], row['actor'], row['details']])
            response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
            wb.save(response)
            return response

    # --- Pagination, then bucket this page's entries into category groups ---
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    grouped = {cat: [] for cat in LOG_CATEGORY_ORDER}
    for log in page_obj:
        log.category = _log_category(log.action)
        log.detail_items = _log_detail_items(log.details)
        grouped[log.category].append(log)
    grouped_logs = [(cat, entries) for cat, entries in grouped.items() if entries]

    context = {
        'tab': 'tickets',
        'logs': page_obj,
        'grouped_logs': grouped_logs,
        'action_choices': sorted(LOG_CATEGORY_MAP.keys()),
        'category_choices': LOG_CATEGORY_ORDER[:-1],  # exclude 'Other' from the filter
        'is_admin_tier': is_admin_tier,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'partials/audit_log.html', context)

# ==========================================================================
# REPORTS DASHBOARD (Charts & KPIs)
# ==========================================================================

@login_required
def reports_dashboard(request):
    """Renders the reports page with SLA compliance, ticket volume, and priority charts."""
    user = request.user
    if user.role not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return HttpResponse(status=403)
    
    # ================================================================
    # DATE RANGE FILTER
    # ================================================================
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if start_date_str and end_date_str:
        try:
            from datetime import datetime
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            date_range_filter = Q(created_at__date__gte=start_date) & Q(created_at__date__lte=end_date)
            date_range_label = f"{start_date.strftime('%b %d, %Y')} – {end_date.strftime('%b %d, %Y')}"
            # Calculate number of days for volume chart
            volume_days = (end_date - start_date).days + 1
            volume_start = start_date
        except ValueError:
            # Invalid date format - fallback to 30 days
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=29)
            date_range_filter = Q(created_at__date__gte=start_date) & Q(created_at__date__lte=end_date)
            date_range_label = "Last 30 days"
            volume_days = 30
            volume_start = start_date
    else:
        # Default: Last 30 days
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=29)
        date_range_filter = Q(created_at__date__gte=start_date) & Q(created_at__date__lte=end_date)
        date_range_label = "Last 30 days"
        volume_days = 30
        volume_start = start_date
    
    if user.role == 'TEAM_LEAD':
        team_members = User.objects.filter(department=user.department, role='AGENT')
        ticket_filter = Q(assigned_to__in=team_members) | Q(requester__in=team_members)
    else:
        ticket_filter = Q()
    
    # Apply date range to ticket filter
    ticket_filter = ticket_filter & date_range_filter
    
    # ========== SLA COMPLIANCE ==========
    slas = SLA.objects.all().order_by('priority')
    sla_data = []

    for sla in slas:
        resolved_tickets = Ticket.objects.filter(
            ticket_filter,
            priority=sla.priority,
            status__in=['RESOLVED', 'CLOSED'],
            resolved_at__isnull=False
        )
        
        total = resolved_tickets.count()
        
        if total == 0:
            compliance = 100
            compliant_count = 0
            breached_count = 0
        else:
            compliant_count = 0
            breached_count = 0
            
            for ticket in resolved_tickets:
                if ticket.resolved_at and ticket.created_at:
                    actual_minutes = (ticket.resolved_at - ticket.created_at).total_seconds() / 60
                    
                    if actual_minutes <= sla.resolution_minutes:
                        compliant_count += 1
                    else:
                        breached_count += 1
            
            compliance = round((compliant_count / total) * 100, 1)
        
        sla_data.append({
            'priority': sla.get_priority_display(),
            'compliance': compliance,
            'total': total,
            'compliant': compliant_count,
            'breached': breached_count,
            'sla_minutes': sla.resolution_minutes,
            'sla_display': sla.get_resolution_display(),
        })

    # ========== TICKET VOLUME (Date Range) ==========
    created_qs = Ticket.objects.filter(
        ticket_filter, created_at__date__gte=volume_start
    ).annotate(date=TruncDate('created_at')).values('date').annotate(count=Count('id')).order_by('date')
    
    resolved_qs = Ticket.objects.filter(
        ticket_filter, resolved_at__isnull=False, resolved_at__date__gte=volume_start
    ).annotate(date=TruncDate('resolved_at')).values('date').annotate(count=Count('id')).order_by('date')

    dates, created_counts, resolved_counts = [], [], []
    for i in range(volume_days):
        d = volume_start + timedelta(days=i)
        dates.append(d.strftime('%m/%d'))
        created_counts.append(next((x['count'] for x in created_qs if x['date'] == d), 0))
        resolved_counts.append(next((x['count'] for x in resolved_qs if x['date'] == d), 0))

    # ========== MTTR ==========
    resolved = Ticket.objects.filter(
        ticket_filter, status__in=['RESOLVED', 'CLOSED'], resolved_at__isnull=False
    )
    mttr = resolved.aggregate(avg_mttr=Avg(F('resolved_at') - F('created_at')))['avg_mttr']
    mttr_minutes = round(mttr.total_seconds() / 60) if mttr else 0

    # ========== BACKLOG ==========
    backlog = Ticket.objects.filter(
        ticket_filter,
        status__in=['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR'],
        created_at__lt=timezone.now() - timedelta(days=7)
    ).count()

    # ========== OPEN BY PRIORITY ==========
    open_by_priority = Ticket.objects.filter(
        ticket_filter,
        status__in=['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']
    ).values('priority').annotate(count=Count('id')).order_by('priority')

    open_labels, open_data = [], []
    for p in open_by_priority:
        open_labels.append(dict(Ticket.Priority.choices)[p['priority']])
        open_data.append(p['count'])

    # ========== ASSET METRICS ==========
    
    total_assets = Asset.objects.count()
    
    asset_status_labels = ['Active', 'In Store', 'Maintenance', 'Damaged', 'Scrapped']
    asset_status_counts = [
        Asset.objects.filter(status__in=[Asset.Status.IN_USE, Asset.Status.CHECKED_OUT, Asset.Status.MOBILIZED]).count(),
        Asset.objects.filter(status=Asset.Status.IN_STORE).count(),
        Asset.objects.filter(status=Asset.Status.MAINTENANCE).count(),
        Asset.objects.filter(status=Asset.Status.DAMAGED).count(),
        Asset.objects.filter(status=Asset.Status.SCRAPPED).count(),
    ]
    
    total_asset_requests = Ticket.objects.filter(
        type=Ticket.Type.SERVICE_REQUEST,
        is_asset_request=True
    ).count()
    
    fulfilled_asset_requests = Ticket.objects.filter(
        type=Ticket.Type.SERVICE_REQUEST,
        is_asset_request=True,
        fulfilled_at__isnull=False
    ).count()
    
    fulfillment_rate = round((fulfilled_asset_requests / total_asset_requests * 100), 1) if total_asset_requests > 0 else 0
    
    fulfilled_tickets = Ticket.objects.filter(
        type=Ticket.Type.SERVICE_REQUEST,
        is_asset_request=True,
        fulfilled_at__isnull=False,
        created_at__isnull=False
    )
    
    total_hours = 0
    count = 0
    for ticket in fulfilled_tickets:
        delta = ticket.fulfilled_at - ticket.created_at
        total_hours += delta.total_seconds() / 3600
        count += 1
    
    avg_fulfillment_hours = round(total_hours / count, 1) if count > 0 else 0

    context = {
        'sla_data': sla_data,
        'volume_dates': dates,
        'volume_created': created_counts,
        'volume_resolved': resolved_counts,
        'mttr_minutes': mttr_minutes,
        'backlog': backlog,
        'open_priority_labels': open_labels,
        'open_priority_data': open_data,
        'open_total': sum(open_data),
        'sidebar_template': get_sidebar_template(request.user),
        # Asset metrics
        'total_assets': total_assets,
        'asset_status_labels': asset_status_labels,
        'asset_status_counts': asset_status_counts,
        'total_asset_requests': total_asset_requests,
        'fulfilled_asset_requests': fulfilled_asset_requests,
        'fulfillment_rate': fulfillment_rate,
        'avg_fulfillment_hours': avg_fulfillment_hours,
        # Date range context
        'start_date': start_date,
        'end_date': end_date,
        'date_range_label': date_range_label,
    }
    return render(request, 'dashboards/reports.html', context)


@login_required
def reports_ticket_list(request):
    """Deep-link target for the Reports dashboard's org-wide KPI cards
    (Open Tickets / Backlog) — there's no other view that lists tickets
    across the whole org (existing list views are queue/requester-scoped),
    so this reuses the same department-scoping rule as reports_dashboard."""
    user = request.user
    if user.role not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return HttpResponse(status=403)

    if user.role == 'TEAM_LEAD':
        team_members = User.objects.filter(department=user.department, role='AGENT')
        ticket_filter = Q(assigned_to__in=team_members) | Q(requester__in=team_members)
    else:
        ticket_filter = Q()

    kpi = request.GET.get('kpi', 'open')
    open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']

    if kpi == 'backlog':
        tickets = Ticket.objects.filter(
            ticket_filter, status__in=open_statuses,
            created_at__lt=timezone.now() - timedelta(days=7)
        )
        heading = 'Backlog (open more than 7 days)'
    else:
        tickets = Ticket.objects.filter(ticket_filter, status__in=open_statuses)
        heading = 'Open Tickets'
    tickets = tickets.order_by('-created_at')

    paginator = Paginator(tickets, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'tickets': page_obj,
        'heading': heading,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'dashboards/reports_ticket_list.html', context)

# ==========================================================================
# EXTERNAL CRON TRIGGERS (SLA & CLEANUP)
# ==========================================================================

# is_admin is imported from apps.common.permissions (see top of file).

@login_required
@user_passes_test(is_admin)
def trigger_sla_processing(request):
    """
    Admin-only endpoint to trigger SLA processing.
    Protected by authentication and role check.
    """
    try:
        call_command('process_sla')
        return JsonResponse({'status': 'ok', 'message': 'SLA processing triggered successfully.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@user_passes_test(is_admin)
def trigger_cleanup(request):
    """
    Admin-only endpoint to trigger cleanup of inactive users.
    Protected by authentication and role check.
    """
    try:
        call_command('cleanup_inactive_users')
        return JsonResponse({'status': 'ok', 'message': 'Cleanup triggered successfully.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

# If you still need an external trigger (e.g., for cron jobs), use a secure token:
# Option: Use a secure token stored in environment variables
@csrf_exempt
def trigger_sla_processing_external(request):
    """
    External endpoint for cron jobs. Protected by a secure token.
    Token should be set in environment variables, not hardcoded.

    The token is read from the X-SLA-Trigger-Secret header (preferred, not
    logged/leaked via Referer the way a query string is) with a `secret`
    GET param kept as a fallback for backward compatibility with any
    existing callers. Comparison uses secrets.compare_digest to avoid a
    timing side-channel.
    """
    import os
    import secrets as secrets_module
    secret = request.headers.get('X-SLA-Trigger-Secret') or request.GET.get('secret', '')
    expected_secret = os.environ.get('SLA_TRIGGER_SECRET')

    if not expected_secret:
        return JsonResponse({'error': 'SLA trigger not configured'}, status=500)

    if not secrets_module.compare_digest(secret, expected_secret):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    try:
        call_command('process_sla')
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ==========================================================================
# PLACEHOLDER / STATIC PAGES
# ==========================================================================

@login_required
def catalogue(request):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']: return HttpResponse(status=403)
    return render(request, 'admin/catalogue.html', {'sidebar_template': get_sidebar_template(request.user)})

@login_required
def connectors(request):
    """
    Admin/Superadmin configuration page for remote connectors (Quick Assist, etc.).
    Lists all connectors and allows editing.
    """
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    connectors_list = RemoteConnector.objects.all().order_by('name')
    return render(request, 'admin/connectors.html', {
        'connectors': connectors_list,
        'sidebar_template': get_sidebar_template(request.user),
    })

@login_required
@require_http_methods(['GET', 'POST'])
def connector_edit(request, pk):
    """
    Edit a specific remote connector: enable/disable and update instructions.
    """
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    connector = get_object_or_404(RemoteConnector, pk=pk)
    if request.method == 'POST':
        connector.is_active = request.POST.get('is_active') == 'on'
        connector.instructions_for_requester = request.POST.get('instructions_for_requester', '')
        connector.instructions_for_agent = request.POST.get('instructions_for_agent', '')
        connector.save()
        messages.success(request, f'"{connector.name}" updated successfully.')
        return redirect('tickets:connectors')
    return render(request, 'admin/connector_form.html', {
        'connector': connector,
        'sidebar_template': get_sidebar_template(request.user),
    })

# ==========================================================================
# ASSET MANAGEMENT
# ==========================================================================

# ==========================================================================
# HELPER: Parse date for asset import
# ==========================================================================

def parse_date(value):
    """Parse date from various formats for asset import."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%b %d, %Y']:
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None

# ==========================================================================
# ASSET LIST
# ==========================================================================

@login_required
def assets(request):
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'AGENT', 'TEAM_LEAD'] or request.user.department != 'IT':
        return HttpResponse(status=403)

    # Use renamed filter parameters
    query = request.GET.get('filter_q', '')
    category_filter = request.GET.get('filter_category', '')
    status_filter = request.GET.get('filter_status', '')
    location_filter = request.GET.get('filter_location', '')
    low_stock_filter = request.GET.get('filter_low_stock', '')
    renewal_due_filter = request.GET.get('filter_renewal_due', '')

    assets_list = Asset.objects.select_related('category', 'assigned_to', 'checked_out_to').order_by('-created_at')

    if query:
        assets_list = assets_list.filter(
            Q(name__icontains=query) |
            Q(tracking_id__icontains=query) |
            Q(serial_number__icontains=query) |
            Q(model__icontains=query) |
            Q(manufacturer__icontains=query)
        )
    if category_filter:
        assets_list = assets_list.filter(category_id=category_filter)
    if status_filter:
        assets_list = assets_list.filter(status=status_filter)
    if location_filter:
        assets_list = assets_list.filter(location__icontains=location_filter)
    if low_stock_filter:
        assets_list = assets_list.filter(
            category__is_consumable=True,
            low_stock_threshold__isnull=False,
            quantity_in_stock__lte=F('low_stock_threshold'),
        )
    if renewal_due_filter:
        assets_list = assets_list.filter(
            category__is_renewable=True,
            next_renewal_date__isnull=False,
            next_renewal_date__lte=timezone.now().date() + timedelta(days=30),
        )

    paginator = Paginator(assets_list, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    users = User.objects.filter(is_active=True).order_by('first_name', 'last_name')

    context = {
        'assets': page_obj,
        'users': users,
        'categories': AssetCategory.objects.all().order_by('name'),
        'status_choices': Asset.Status.choices,
        'status_values': [v for v, _ in Asset.Status.choices],
        'location_choices': Asset.Location.choices,
        'location_values': [v for v, _ in Asset.Location.choices],
        'query': query,
        'selected_category': category_filter,
        'selected_status': status_filter,
        'selected_location': location_filter,
        'selected_low_stock': low_stock_filter,
        'selected_renewal_due': renewal_due_filter,
        'today': timezone.now().date(),
        'sidebar_template': get_sidebar_template(request.user),
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/asset_table.html', context)

    return render(request, 'tickets/asset_list.html', context)


# ==========================================================================
# MY ASSETS — assets allocated to the logged-in user, any role. Separate
# from `assets()` above (IT-only asset management) — this is a read-mostly
# view of "what's assigned to me", including any maintenance scheduled or
# awaiting the owner's confirmation on those assets.
# ==========================================================================

def _my_assets_pending_confirmations_q(user):
    """Rows the given user is eligible to confirm as an asset OWNER — used
    by both my_assets() and my_assets_pending_count(). Deliberately does NOT
    include the department-Team-Lead fallback or the Admin/Superadmin
    override (see apps.maintenance.views.can_confirm_asset_maintenance) —
    this page is about assets allocated to THIS user specifically, not every
    schedule they happen to be eligible to act on."""
    return MaintenanceAssetConfirmation.objects.filter(
        asset__assigned_to=user, status=MaintenanceAssetConfirmation.Status.PENDING,
    )


@login_required
def my_assets(request):
    """Assets assigned to the current user, with any upcoming/in-progress
    maintenance and any completion awaiting their confirmation surfaced
    inline — open to every role, since asset ownership isn't role-bound."""
    assets_list = Asset.objects.filter(assigned_to=request.user).select_related('category').prefetch_related(
        'maintenance_confirmations__schedule',
        'maintenance_schedules',
    ).order_by('name')

    rows = []
    for asset in assets_list:
        pending_confirmations = [
            c for c in asset.maintenance_confirmations.all()
            if c.status == MaintenanceAssetConfirmation.Status.PENDING
        ]
        upcoming_schedules = [
            s for s in asset.maintenance_schedules.all()
            if s.status in (MaintenanceSchedule.Status.SCHEDULED, MaintenanceSchedule.Status.IN_PROGRESS)
        ]
        rows.append({
            'asset': asset,
            'pending_confirmations': pending_confirmations,
            'upcoming_schedules': upcoming_schedules,
        })

    context = {
        'rows': rows,
        'today': timezone.now().date(),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'tickets/my_assets.html', context)


@login_required
def my_assets_pending_count(request):
    """Badge count for the sidebar 'My Assets' link — mirrors the pattern
    used by remote_session_pending_count."""
    count = _my_assets_pending_confirmations_q(request.user).count()
    return render(request, 'partials/my_assets_badge.html', {'count': count})


# ==========================================================================
# ASSET CREATE PAGE (Dedicated Page)
# ==========================================================================

@login_required
@require_http_methods(['GET', 'POST'])
def asset_create_page(request):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    if request.method == 'POST':
        form = AssetForm(request.POST)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.tracking_id = None
            asset.save()
            
            # Create CREATED log
            AssetLog.objects.create(
                asset=asset,
                action=AssetLog.Action.CREATED,
                actor=request.user,
                details={'name': asset.name, 'category': asset.category.name if asset.category else None}
            )
            
            # Create ASSIGNED log if assigned to someone
            if asset.assigned_to:
                AssetLog.objects.create(
                    asset=asset,
                    action=AssetLog.Action.ASSIGNED,
                    actor=request.user,
                    details={
                        'from': None,
                        'to': asset.assigned_to.get_full_name() if asset.assigned_to else None,
                        'comment': 'Initial assignment'
                    }
                )
            
            messages.success(request, f'Asset "{asset.name}" created successfully!')
            return redirect('tickets:assets')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AssetForm()

    context = {
        'form': form,
        'asset': None,
        'action': 'create',
        'users': User.objects.filter(is_active=True).order_by('first_name', 'last_name'),
        'categories': AssetCategory.objects.all().order_by('name'),
        'status_choices': Asset.Status.choices,
        'status_values': [v for v, _ in Asset.Status.choices],
        'locations': Asset.objects.exclude(location='').values_list('location', flat=True).distinct().order_by('location'),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'tickets/asset_form_page.html', context)


# ==========================================================================
# ASSET EDIT PAGE (Dedicated Page)
# ==========================================================================

@login_required
@require_http_methods(['GET', 'POST'])
def asset_edit_page(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    asset = get_object_or_404(Asset, pk=pk)

    if request.method == 'POST':
        # Store the old assigned_to value before saving
        old_assigned_to = asset.assigned_to
        old_name = old_assigned_to.get_full_name() if old_assigned_to else 'Unassigned'
        actor_name = request.user.get_full_name()
        
        form = AssetForm(request.POST, instance=asset)
        if form.is_valid():
            asset = form.save()
            asset.refresh_low_stock_alert()

            # Check if assigned_to changed
            new_assigned_to = asset.assigned_to
            new_name = new_assigned_to.get_full_name() if new_assigned_to else 'Unassigned'
            
            # Create appropriate logs based on what changed
            if old_assigned_to != new_assigned_to:
                # This is a reassignment or unassignment
                if new_assigned_to:
                    # Reassigned to someone
                    AssetLog.objects.create(
                        asset=asset,
                        action=AssetLog.Action.ASSIGNED,
                        actor=request.user,
                        details={
                            'from': old_name,
                            'to': new_name,
                            'comment': 'Reassigned via edit form'
                        }
                    )
                    
                    # ================================================================
                    # DEFAULT REASSIGN COMMENT
                    # ================================================================
                    comment_body = f"🔄 **Asset reassigned** by {actor_name} from **{old_name}** to **{new_name}** via edit form."
                    if asset.notes:
                        asset.notes = f"{asset.notes}\n\n{comment_body}"
                    else:
                        asset.notes = comment_body
                    asset.save(update_fields=['notes'])
                    
                else:
                    # Unassigned
                    AssetLog.objects.create(
                        asset=asset,
                        action=AssetLog.Action.UNASSIGNED,
                        actor=request.user,
                        details={
                            'from': old_name,
                            'to': None,
                            'comment': 'Unassigned via edit form'
                        }
                    )
                    
                    # ================================================================
                    # DEFAULT UNASSIGN COMMENT
                    # ================================================================
                    comment_body = f"🔄 **Asset unassigned** by {actor_name} from **{old_name}** via edit form."
                    if asset.notes:
                        asset.notes = f"{asset.notes}\n\n{comment_body}"
                    else:
                        asset.notes = comment_body
                    asset.save(update_fields=['notes'])
                    
            else:
                # General update (no assignment change)
                AssetLog.objects.create(
                    asset=asset,
                    action=AssetLog.Action.UPDATED,
                    actor=request.user,
                    details={'source': 'edit_page'}
                )
            
            messages.success(request, f'Asset "{asset.name}" updated successfully!')
            
            # Preserve filters when redirecting back
            source = request.GET.get('source', 'list')
            query = request.GET.get('q', '')
            category_param = request.GET.get('category', '')
            status = request.GET.get('status', '')
            location = request.GET.get('location', '')

            redirect_url = reverse('tickets:assets')
            if source == 'list':
                params = []
                if query:
                    params.append(f'q={query}')
                if category_param:
                    params.append(f'category={category_param}')
                if status:
                    params.append(f'status={status}')
                if location:
                    params.append(f'location={location}')
                if params:
                    redirect_url += '?' + '&'.join(params)
            
            return redirect(redirect_url)
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = AssetForm(instance=asset)

    context = {
        'form': form,
        'asset': asset,
        'action': 'edit',
        'users': User.objects.filter(is_active=True).order_by('first_name', 'last_name'),
        'categories': AssetCategory.objects.all().order_by('name'),
        'status_choices': Asset.Status.choices,
        'status_values': [v for v, _ in Asset.Status.choices],
        'locations': Asset.objects.exclude(location='').values_list('location', flat=True).distinct().order_by('location'),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'tickets/asset_form_page.html', context)

# ==========================================================================
# ASSET REASSIGN
# ==========================================================================

@login_required
@require_POST
def asset_reassign(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return HttpResponse(status=403)

    asset = get_object_or_404(Asset, pk=pk)
    new_user_id = request.POST.get('assigned_to')
    comment = request.POST.get('comment', '')

    old_user = asset.assigned_to
    actor_name = request.user.get_full_name()
    
    if new_user_id:
        new_user = get_object_or_404(User, pk=new_user_id)
        asset.assigned_to = new_user
        new_name = new_user.get_full_name()
    else:
        asset.assigned_to = None
        new_name = 'Unassigned'
    
    old_name = old_user.get_full_name() if old_user else 'Unassigned'
    
    asset.save()

    # Create asset log
    AssetLog.objects.create(
        asset=asset,
        action=AssetLog.Action.ASSIGNED if new_user_id else AssetLog.Action.UNASSIGNED,
        actor=request.user,
        details={
            'from': old_name,
            'to': new_name,
            'comment': comment
        }
    )

    # Add comment to asset notes (user can edit the default comment)
    if new_user_id:
        comment_body = f"🔄 **Asset reassigned** by {actor_name} from **{old_name}** to **{new_name}**.\n\n**Reason:** {comment}"
    else:
        comment_body = f"🔄 **Asset unassigned** by {actor_name} from **{old_name}**.\n\n**Reason:** {comment}"
    
    if asset.notes:
        asset.notes = f"{asset.notes}\n\n{comment_body}"
    else:
        asset.notes = comment_body
    asset.save(update_fields=['notes'])

    if new_user_id:
        messages.success(request, f'"{asset.name}" reassigned to {new_name}.')
    else:
        messages.success(request, f'"{asset.name}" unassigned.')
    return redirect('tickets:assets')

@login_required
def asset_reassign_modal(request, pk):
    """Returns the asset reassign modal with pre-filled comment."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    users = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
    
    # Generate default comment
    old_name = asset.assigned_to.get_full_name() if asset.assigned_to else 'Unassigned'
    default_comment = f"Reassigning asset from {old_name} to [new user]."
    
    return render(request, 'partials/asset_reassign_modal.html', {
        'asset': asset,
        'users': users,
        'default_comment': default_comment,
    })

# ==========================================================================
# ASSET DETAIL
# ==========================================================================

@login_required
def asset_detail(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'AGENT', 'TEAM_LEAD']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    logs = asset.logs.all()[:10]  # Recent activity
    
    return render(request, 'tickets/asset_detail.html', {
        'asset': asset,
        'logs': logs,
        'today': timezone.now().date(),
        'sidebar_template': get_sidebar_template(request.user),
    })


@login_required
@require_POST
def asset_mark_renewed(request, pk):
    """Admin action: the license/subscription was actually paid/renewed —
    advances next_renewal_date, resets reminder flags, logs an audit entry."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    asset = get_object_or_404(Asset, pk=pk)
    if not asset.is_renewable:
        messages.error(request, 'This asset is not in a renewable category.')
        return redirect('tickets:asset_detail', pk=asset.pk)
    if not asset.renewal_interval_months:
        messages.error(request, 'Set a renewal interval (months) before marking this as renewed.')
        return redirect('tickets:asset_detail', pk=asset.pk)

    new_cost_raw = request.POST.get('new_cost', '').strip()
    new_cost = None
    if new_cost_raw:
        try:
            new_cost = Decimal(new_cost_raw)
        except InvalidOperation:
            messages.error(request, 'Enter a valid cost, or leave it blank to keep the current cost.')
            return redirect('tickets:asset_detail', pk=asset.pk)

    asset.mark_renewed(request.user, new_cost=new_cost)
    messages.success(request, f'✅ "{asset.name}" renewed — next renewal {asset.next_renewal_date}.')
    return redirect('tickets:asset_detail', pk=asset.pk)

# ==========================================================================
# ASSET SCRAP REQUEST
# ==========================================================================

# apps/tickets/views.py - Fix asset_scrap_request

@login_required
@require_POST
def asset_scrap_request(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return HttpResponse(status=403)

    asset = get_object_or_404(Asset, pk=pk)
    comment = request.POST.get('comment', '')

    # Check if asset is already scrapped or damaged
    if asset.status == Asset.Status.SCRAPPED:
        return JsonResponse({'error': 'Asset already scrapped.'}, status=400)
    
    if asset.status == Asset.Status.DAMAGED:
        return JsonResponse({'error': 'Asset already marked as damaged.'}, status=400)

    # Only change status if not already in appropriate state
    asset.status = Asset.Status.DAMAGED
    asset.save()

    AssetLog.objects.create(
        asset=asset,
        action=AssetLog.Action.SCRAP_REQUESTED,
        actor=request.user,
        details={'comment': comment}
    )

    messages.success(request, f'Scrap requested for "{asset.name}" — pending approval.')
    return redirect('tickets:assets')

@login_required
def scrap_request_modal(request, pk):
    """Returns the scrap request modal content."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    return render(request, 'partials/scrap_request_modal.html', {'asset': asset})

# ==========================================================================
# ASSET SCRAP APPROVE
# ==========================================================================

@login_required
@require_POST
def asset_scrap_approve(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    asset = get_object_or_404(Asset, pk=pk)
    action = request.POST.get('action')  # 'approve' or 'reject'

    if action == 'approve':
        asset.status = Asset.Status.SCRAPPED
        asset.scrap_approved = True
        asset.scrap_approved_at = timezone.now()
        asset.scrap_approved_by = request.user
        asset.save()
        AssetLog.objects.create(
            asset=asset,
            action=AssetLog.Action.SCRAP_APPROVED,
            actor=request.user,
            details={'comment': request.POST.get('comment', '')}
        )
        messages.success(request, f'Scrap approved for "{asset.name}" — asset marked as scrapped.')
    else:
        # Reject: revert to an available state (asset was marked DAMAGED by
        # the scrap request; rejecting the scrap returns it to the shelf).
        asset.status = Asset.Status.IN_STORE
        asset.save()
        AssetLog.objects.create(
            asset=asset,
            action=AssetLog.Action.SCRAP_REJECTED,
            actor=request.user,
            details={'comment': request.POST.get('comment', '')}
        )
        messages.success(request, f'Scrap rejected for "{asset.name}" — returned to inventory.')

    return redirect('tickets:assets')

@login_required
def scrap_approve_modal(request, pk):
    """Returns the scrap approve modal content."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    return render(request, 'partials/scrap_approve_modal.html', {'asset': asset})


# ==========================================================================
# ASSET CALCULATE WARRANTY
# ==========================================================================

@login_required
def asset_calculate_warranty(request):
    """Calculate warranty expiry date based on purchase date and duration."""
    purchase_date_str = request.GET.get('purchase_date')
    duration_years = request.GET.get('warranty_duration', 0)
    expiry_date_str = ''
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Warranty calculation: purchase_date={purchase_date_str}, duration={duration_years}")
    
    try:
        duration_years = int(duration_years)
        if duration_years > 0 and purchase_date_str:
            from datetime import datetime
            purchase_date = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
            # Calculate expiry by adding years
            try:
                expiry_date = purchase_date.replace(year=purchase_date.year + duration_years)
                expiry_date_str = expiry_date.strftime('%Y-%m-%d')
                logger.info(f"Warranty calculation result: {expiry_date_str}")
            except ValueError:
                # Handle Feb 29 edge case - approximate by adding days
                days = 365 * duration_years
                expiry_date = purchase_date + timedelta(days=days)
                expiry_date_str = expiry_date.strftime('%Y-%m-%d')
                logger.info(f"Warranty calculation (approx): {expiry_date_str}")
    except (ValueError, TypeError, OverflowError) as e:
        logger.error(f"Warranty calculation error: {e}")
        pass

    return render(request, 'partials/warranty_expiry_input.html', {'value': expiry_date_str})

# ==========================================================================
# REMOTE SESSION REQUESTS (Quick Assist integration)
# ==========================================================================

@login_required
@require_POST
def request_remote_session(request, pk):
    """
    Initiates a remote session request from an agent to the ticket requester.
    - Creates a RemoteSession record (status=REQUESTED).
    - Adds a public comment on the ticket.
    - Sends an in‑app notification to the requester.
    - Sends an email to the requester with a link to accept the session.
    - Logs the action in the activity log.
    Only agents, team leads, admins, and superadmins can call this.
    """
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.user.role not in [User.Role.AGENT, User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return JsonResponse({'error': 'You do not have permission to request a remote session.'}, status=403)

    # Get the first active remote connector (e.g., Quick Assist)
    connector = RemoteConnector.objects.filter(is_active=True).first()
    if not connector:
        # This request is always hx-post/hx-swap="none" (see ticket_conversation.html),
        # so a messages.error()+redirect is never actually rendered to the user —
        # return JSON so the caller's toast can show the real reason.
        return JsonResponse({'error': 'No active remote connector configured. Please contact your administrator.'}, status=400)

    # Check if there's already a pending or active session for this ticket
    existing = RemoteSession.objects.filter(ticket=ticket, status__in=[RemoteSession.Status.REQUESTED, RemoteSession.Status.ACCEPTED, RemoteSession.Status.STARTED]).first()
    if existing:
        return JsonResponse({'error': 'A remote session is already pending or in progress.'}, status=400)
    
    session = RemoteSession.objects.create(
        ticket=ticket,
        requester=ticket.requester,
        agent=request.user,
        connector=connector,
        status=RemoteSession.Status.REQUESTED
    )

    # Add a public comment to the ticket timeline
    TicketComment.objects.create(
        ticket=ticket,
        author=request.user,
        body=f"Remote session requested via {connector.name}. Please check your notifications to accept.",
        visibility='PUBLIC'
    )

    # Send in‑app notification
    Notification.objects.create(
        recipient=ticket.requester,
        role=role_of(ticket.requester),
        message=f"Remote session requested for ticket {ticket.number}. Click to accept.",
        url=reverse('tickets:remote_session_detail', args=[session.pk]),
        type=Notification.Type.REMOTE_SESSION
    )

    # send_mail section

    accept_url = request.build_absolute_uri(reverse('tickets:remote_session_detail', args=[session.pk]))
    reject_url = request.build_absolute_uri(reverse('tickets:remote_session_detail', args=[session.pk])) + '?action=reject'

    html_message = render_to_string('emails/remote_session_request.html', {
        'requester_name': ticket.requester.get_full_name() or ticket.requester.email,
        'ticket_number': ticket.number,
        'accept_url': accept_url,
        'reject_url': reject_url,
    })
    plain_message = strip_tags(html_message)

    success, result = send_email_via_brevo(
        to_email=ticket.requester.email,
        subject=f"Remote Session Request – Ticket {ticket.number}",
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )

    if not success:
        logger.error(f"Failed to send remote session email: {result}")
    
    TicketActivityLog.objects.create(
        ticket=ticket,
        action='remote_session_requested',
        actor=request.user,
        details={'connector': connector.name, 'session_id': session.pk}
    )
    
    return JsonResponse({'session_id': session.pk, 'status': 'requested'})

@login_required
def remote_session_detail(request, session_pk):
    session = get_object_or_404(RemoteSession, pk=session_pk)
    user = request.user
    is_overseer = user.role in [User.Role.ADMIN, User.Role.SUPERADMIN]
    if user != session.requester and user != session.agent and not is_overseer:
        return HttpResponse(status=403)

    if user == session.agent:
        instructions = session.connector.instructions_for_agent
        role = 'agent'
    elif user == session.requester:
        instructions = session.connector.instructions_for_requester
        role = 'requester'
    else:
        # Admin/Superadmin viewing a session they're not party to — read-only oversight,
        # same as remote_sessions_list already shows them every session.
        instructions = session.connector.instructions_for_requester
        role = 'observer'

    code_error = None

    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(RemoteSession.STATUS_CHOICES):
            old_status = session.status
            # Handle REJECT from requester — only meaningful before the session has
            # actually started, matching every other transition's old_status guard
            # (previously unguarded, so a stray POST could "reject" an ended session).
            if new_status == RemoteSession.Status.REJECTED and role == 'requester' and old_status in (RemoteSession.Status.REQUESTED, RemoteSession.Status.ACCEPTED):
                session.status = RemoteSession.Status.REJECTED
                session.save()
                # Notify agent
                Notification.objects.create(
                    recipient=session.agent,
                    role=role_of(session.agent),
                    message=f"{session.requester.get_full_name()} rejected the remote session for ticket {session.ticket.number}.",
                    url=reverse('tickets:remote_session_detail', args=[session.pk]),
                    type=Notification.Type.REMOTE_SESSION
                )
                TicketActivityLog.objects.create(
                    ticket=session.ticket,
                    action='remote_session_status_change',
                    actor=user,
                    details={'from': old_status, 'to': RemoteSession.Status.REJECTED, 'session_id': session.pk}
                )
                return redirect('tickets:remote_session_detail', session_pk=session.pk)
            
            # Handle ACCEPT from requester
            elif new_status == RemoteSession.Status.ACCEPTED and role == 'requester' and old_status == RemoteSession.Status.REQUESTED:
                session.status = RemoteSession.Status.ACCEPTED
                session.save()
                # Notify agent
                Notification.objects.create(
                    recipient=session.agent,
                    role=role_of(session.agent),
                    message=f"{session.requester.get_full_name()} accepted the remote session for ticket {session.ticket.number}.",
                    url=reverse('tickets:remote_session_detail', args=[session.pk]),
                    type=Notification.Type.REMOTE_SESSION
                )
                TicketActivityLog.objects.create(
                    ticket=session.ticket,
                    action='remote_session_status_change',
                    actor=user,
                    details={'from': old_status, 'to': RemoteSession.Status.ACCEPTED, 'session_id': session.pk}
                )
                return redirect('tickets:remote_session_detail', session_pk=session.pk)
            
            # Handle START with code from agent
            elif new_status == RemoteSession.Status.STARTED and role == 'agent' and old_status == RemoteSession.Status.ACCEPTED:
                code = request.POST.get('quick_assist_code', '').strip()
                if not code or len(code) < 6:
                    code_error = 'Enter the 6-digit code shown in Quick Assist before starting the session.'
                else:
                    session.session_code = code
                    session.status = RemoteSession.Status.STARTED
                    session.started_at = timezone.now()
                    session.save()
                    # Send automatic public comment on ticket
                    TicketComment.objects.create(
                        ticket=session.ticket,
                        author=request.user,
                        body=f"Remote session code: {code}. Please use this code in Quick Assist to start the session.",
                        visibility='PUBLIC'
                    )
                    # Send email to requester
                    html_message = render_to_string('emails/remote_session_code.html', {
                        'requester_name': session.requester.get_full_name() or session.requester.email,
                        'ticket_number': session.ticket.number,
                        'code': code,
                    })
                    plain_message = strip_tags(html_message)

                    success, result = send_email_via_brevo(
                        to_email=session.requester.email,
                        subject=f"Remote Session Code – Ticket {session.ticket.number}",
                        html_content=html_message,
                        from_email=settings.DEFAULT_FROM_EMAIL
                    )

                    if not success:
                        logger.error(f"Failed to send remote session code email: {result}")
                        
                    TicketActivityLog.objects.create(
                        ticket=session.ticket,
                        action='remote_session_status_change',
                        actor=user,
                        details={'from': old_status, 'to': RemoteSession.Status.STARTED, 'session_id': session.pk, 'code': code}
                    )
                    return redirect('tickets:remote_session_detail', session_pk=session.pk)
            
            # Handle END from agent
            elif new_status == RemoteSession.Status.ENDED and role == 'agent' and old_status == RemoteSession.Status.STARTED:
                session.status = RemoteSession.Status.ENDED
                session.ended_at = timezone.now()
                session.save()
                # Previously the requester was never told the session ended — they'd
                # only find out by refreshing. Notify + email them like every other
                # transition does.
                Notification.objects.create(
                    recipient=session.requester,
                    role=role_of(session.requester),
                    message=f"The remote session for ticket {session.ticket.number} has ended.",
                    url=reverse('tickets:remote_session_detail', args=[session.pk]),
                    type=Notification.Type.REMOTE_SESSION
                )
                html_message = render_to_string('emails/remote_session_ended.html', {
                    'requester_name': session.requester.get_full_name() or session.requester.email,
                    'ticket_number': session.ticket.number,
                })
                success, result = send_email_via_brevo(
                    to_email=session.requester.email,
                    subject=f"Remote Session Ended – Ticket {session.ticket.number}",
                    html_content=html_message,
                    from_email=settings.DEFAULT_FROM_EMAIL
                )
                if not success:
                    logger.error(f"Failed to send remote session ended email: {result}")
                TicketActivityLog.objects.create(
                    ticket=session.ticket,
                    action='remote_session_status_change',
                    actor=user,
                    details={'from': old_status, 'to': RemoteSession.Status.ENDED, 'session_id': session.pk}
                )
                return redirect('tickets:remote_session_detail', session_pk=session.pk)
    
    context = {
        'session': session,
        'instructions': instructions,
        'role': role,
        'sidebar_template': get_sidebar_template(request.user),
        'code_error': code_error,
        # The "Reject" button in the request email links here with ?action=reject —
        # previously nothing read this param at all, so the link silently did
        # nothing beyond opening the normal page. We still require an explicit
        # click to actually reject (a GET request shouldn't change state), but
        # highlight the reject option so the email's promise is at least honored.
        'highlight_reject': request.GET.get('action') == 'reject',
    }
    return render(request, 'tickets/remote_session_detail.html', context)

@login_required
def remote_session_pending_count(request):
    """
    Returns the count of pending remote sessions for the current user.
    For agents: sessions they requested with status REQUESTED or ACCEPTED.
    For requesters: sessions requested for their tickets with status REQUESTED.
    """
    user = request.user
    if user.role in [User.Role.ADMIN, User.Role.SUPERADMIN]:
        # Admins see all pending sessions
        count = RemoteSession.objects.filter(status__in=[RemoteSession.Status.REQUESTED, RemoteSession.Status.ACCEPTED]).count()
    elif user.role in [User.Role.AGENT, User.Role.TEAM_LEAD]:
        count = RemoteSession.objects.filter(agent=user, status__in=[RemoteSession.Status.REQUESTED, RemoteSession.Status.ACCEPTED]).count()
    else:
        # End users: sessions requested for their tickets
        count = RemoteSession.objects.filter(requester=user, status=RemoteSession.Status.REQUESTED).count()
    return render(request, 'partials/remote_session_badge.html', {'count': count})

@login_required
def remote_sessions_list(request):
    """
    List all remote sessions relevant to the logged‑in user.
    - Agents see sessions they initiated (as agent).
    - Requesters see sessions requested for their tickets.
    - Admins/Superadmins see all sessions (optional, but we'll filter by role).
    """
    user = request.user
    base_qs = RemoteSession.objects.select_related('ticket', 'requester', 'agent', 'connector')
    if user.role in [User.Role.ADMIN, User.Role.SUPERADMIN]:
        sessions = base_qs.order_by('-created_at')
    elif user.role in [User.Role.AGENT, User.Role.TEAM_LEAD] and user.department == 'IT':
        sessions = base_qs.filter(agent=user).order_by('-created_at')
    else:
        sessions = base_qs.filter(requester=user).order_by('-created_at')
    
    # Pagination
    paginator = Paginator(sessions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'sessions': page_obj,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'tickets/remote_sessions_list.html', context)

@login_required
def escalated_tickets(request):
    if request.user.role not in [User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN] or request.user.department != 'IT':
        return HttpResponse(status=403)

    tickets = Ticket.objects.filter(status=Ticket.Status.ESCALATED).order_by('-created_at')

    # If Team Lead, filter by their department
    if request.user.role == User.Role.TEAM_LEAD:
        tickets = tickets.filter(assigned_to__department=request.user.department)

    # Agents in the same department (for reassign)
    agents = User.objects.filter(
        department=request.user.department,
        role=User.Role.AGENT,
        is_active=True
    )

    # Workload: open tickets per agent
    open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']
    agent_workload = {}
    for agent in agents:
        agent_workload[agent.pk] = Ticket.objects.filter(
            assigned_to=agent,
            status__in=open_statuses
        ).count()

    # Reason macros
    reassign_reasons = Macro.objects.filter(type=Macro.Type.REASSIGN_REASON)
    return_reasons = Macro.objects.filter(type=Macro.Type.RETURN_REASON)

    context = {
        'tickets': tickets,
        'assignable_agents': agents,
        'agent_workload': agent_workload,
        'reassign_reasons': reassign_reasons,
        'return_reasons': return_reasons,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'team_lead/escalated_tickets.html', context)

@login_required
@require_POST
def reassign_escalated(request, pk):
    if request.user.role not in [User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)
    
    ticket = get_object_or_404(Ticket, pk=pk, status=Ticket.Status.ESCALATED)
    agent_id = request.POST.get('agent_id')
    comment = request.POST.get('comment', '')
    agent = get_object_or_404(User, pk=agent_id, role=User.Role.AGENT)
    
    # Store old assignee name
    old_name = ticket.assigned_to.get_full_name() if ticket.assigned_to else 'Unassigned'
    new_name = agent.get_full_name()
    actor_name = request.user.get_full_name()
    
    # Reassign the ticket
    ticket.assigned_to = agent
    ticket.status = Ticket.Status.ASSIGNED
    ticket.save()
    
    # Create activity log
    TicketActivityLog.objects.create(
        ticket=ticket,
        action='reassigned_escalated',
        actor=request.user,
        details={'to': agent.get_full_name(), 'comment': comment}
    )
    
    # ================================================================
    # DEFAULT REASSIGN COMMENT
    # ================================================================
    reassign_body = f"🔄 **Escalated ticket reassigned** by {actor_name} from **{old_name}** to **{new_name}**."
    if comment:
        reassign_body += f"\n\n**Reason:** {comment}"
    
    TicketComment.objects.create(
        ticket=ticket,
        author=request.user,
        body=reassign_body,
        visibility='PUBLIC'
    )
    
    # Notify agent
    Notification.objects.create(
        recipient=agent,
        role=role_of(agent),
        message=f"Ticket {ticket.number} has been reassigned to you by {request.user.get_full_name()}.",
        url=reverse('tickets:detail', args=[ticket.pk])
    )
    messages.success(request, f'Ticket {ticket.number} reassigned to {new_name}.')
    return redirect('tickets:escalated_tickets')

@login_required
def escalated_reassign_modal(request, pk):
    """Returns the escalated ticket reassign modal with pre-filled comment."""
    if request.user.role not in [User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)
    
    ticket = get_object_or_404(Ticket, pk=pk, status=Ticket.Status.ESCALATED)
    
    # Get agents in the same department
    agents = User.objects.filter(
        department=request.user.department, 
        role=User.Role.AGENT, 
        is_active=True
    )
    
    # Generate default comment
    old_name = ticket.assigned_to.get_full_name() if ticket.assigned_to else 'Unassigned'
    default_comment = f"Reassigning escalated ticket from {old_name} to [new agent]."
    
    return render(request, 'partials/escalated_reassign_modal.html', {
        'ticket': ticket,
        'agents': agents,
        'default_comment': default_comment,
    })

@login_required
@require_POST
def return_escalated_to_pool(request, pk):
    if request.user.role not in [User.Role.TEAM_LEAD, User.Role.ADMIN, User.Role.SUPERADMIN]:
        return HttpResponse(status=403)
    ticket = get_object_or_404(Ticket, pk=pk, status=Ticket.Status.ESCALATED)
    comment = request.POST.get('comment', '')
    if not comment:
        return JsonResponse({'error': 'Comment is required'}, status=400)
    ticket.assigned_to = None
    ticket.status = Ticket.Status.NEW
    ticket.save()
    TicketActivityLog.objects.create(
        ticket=ticket,
        action='returned_to_pool',
        actor=request.user,
        details={'comment': comment}
    )
    messages.success(request, f'Ticket {ticket.number} returned to the pool.')
    return redirect('tickets:escalated_tickets')


# ==========================================================================
# ATTACHMENT PREVIEW AND DOWNLOAD
# ==========================================================================

@login_required
def attachment_preview(request, pk):
    """
    Returns a modal with a preview of the attachment.
    Supports images, PDF, Office documents, and text files.
    """
    attachment = get_object_or_404(Attachment, pk=pk)
    ticket = attachment.ticket

    # Permission check: same as download
    if request.user != ticket.requester and request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    # Get file URL for embedding
    file_url = request.build_absolute_uri(attachment.file.url)
    content_type = attachment.content_type or ''
    filename = attachment.filename

    # Determine preview type
    preview_type = 'unknown'
    embed_url = None
    text_content = None

    if content_type.startswith('image/'):
        preview_type = 'image'
    elif content_type == 'application/pdf':
        preview_type = 'pdf'
        embed_url = f"https://docs.google.com/gview?url={file_url}&embedded=true"
    elif content_type in [
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
    ]:
        preview_type = 'office'
        embed_url = f"https://docs.google.com/gview?url={file_url}&embedded=true"
    elif content_type.startswith('text/') or filename.endswith(('.txt', '.csv', '.log', '.py', '.js', '.html', '.css')):
        preview_type = 'text'
        # Fetch the file content (for small text files only)
        try:
            with attachment.file.open('r') as f:
                text_content = f.read()
                # Limit size to prevent huge files
                if len(text_content) > 100000:  # 100KB limit
                    text_content = "File too large to preview as text."
        except Exception:
            text_content = "Could not read file content."

    context = {
        'attachment': attachment,
        'preview_type': preview_type,
        'embed_url': embed_url,
        'text_content': text_content,
        'file_url': file_url,
    }
    return render(request, 'tickets/attachment_preview.html', context)

@login_required
def attachment_download(request, pk):
    """
    Serves a file attachment. Only the ticket requester or agents/leads/admins can download.
    """
    attachment = get_object_or_404(Attachment, pk=pk)
    ticket = attachment.ticket
    if request.user != ticket.requester and request.user.role not in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        raise PermissionDenied
    response = FileResponse(attachment.file.open('rb'), content_type=attachment.content_type or 'application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{attachment.filename}"'
    return response

# ==========================================================================
# SLA MANAGEMENT (Admin & Superadmin only)
# ==========================================================================

# is_admin is imported from apps.common.permissions (see top of file).

@login_required
@user_passes_test(is_admin)
def sla_list(request):
    slas = SLA.objects.all().order_by('priority')
    calendars = BusinessCalendar.objects.all()
    rules = EscalationRule.objects.all().order_by('priority', 'timer_type', 'threshold_percent')
    context = {
        'slas': slas,
        'calendars': calendars,
        'rules': rules,
        'priority_choices': Ticket.Priority.choices,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'admin/sla_management.html', context)

@login_required
@user_passes_test(is_admin)
@require_POST
def sla_create(request):
    priority = request.POST.get('priority')
    if not priority:
        messages.error(request, 'Please select a priority for the SLA policy.')
        return redirect('tickets:sla_management')

    try:
        # Get hours and minutes from form
        response_hours = int(request.POST.get('response_hours', 0))
        response_minutes = int(request.POST.get('response_minutes', 0))
        resolution_hours = int(request.POST.get('resolution_hours', 0))
        resolution_minutes = int(request.POST.get('resolution_minutes', 0))
    except ValueError:
        messages.error(request, 'Please enter valid numbers for the response/resolution times.')
        return redirect('tickets:sla_management')

    # Calculate total minutes
    response_total = (response_hours * 60) + response_minutes
    resolution_total = (resolution_hours * 60) + resolution_minutes

    calendar_id = request.POST.get('calendar_id') or None

    try:
        sla, created = SLA.objects.update_or_create(
            priority=priority,
            defaults={
                'response_minutes': response_total if response_total > 0 else 60,  # Default 1 hour
                'resolution_minutes': resolution_total if resolution_total > 0 else 480,  # Default 8 hours
                'calendar_id': calendar_id
            }
        )
    except Exception as e:
        logger.error(f"Failed to save SLA policy: {e}")
        messages.error(request, 'Could not save the SLA policy. Please try again.')
        return redirect('tickets:sla_management')

    if created:
        messages.success(request, f'SLA policy for {sla.get_priority_display()} created successfully.')
    else:
        messages.success(request, f'SLA policy for {sla.get_priority_display()} updated successfully.')
    return redirect('tickets:sla_management')

@login_required
@user_passes_test(is_admin)
@require_POST
def sla_delete(request, pk):
    sla = get_object_or_404(SLA, pk=pk)
    priority_display = sla.get_priority_display()
    sla.delete()
    messages.success(request, f'SLA policy for {priority_display} deleted.')
    return redirect('tickets:sla_management')

@login_required
def sla_badge(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)
    return render(request, 'partials/sla_badge.html', {'ticket': ticket})

@login_required
@user_passes_test(is_admin)
@require_POST
def calendar_create(request):
    name = request.POST.get('name')
    if not name:
        messages.error(request, 'Please enter a name for the business calendar.')
        return redirect('tickets:sla_management')

    workdays = request.POST.getlist('workdays')
    work_start = request.POST.get('work_start')
    work_end = request.POST.get('work_end')
    holidays_str = request.POST.get('holidays', '')
    holidays = [h.strip() for h in holidays_str.split(',') if h.strip()]
    try:
        BusinessCalendar.objects.create(
            name=name, workdays=workdays, work_start=work_start, work_end=work_end, holidays=holidays
        )
    except Exception as e:
        logger.error(f"Failed to create business calendar: {e}")
        messages.error(request, 'Could not create the business calendar. Please check the values and try again.')
        return redirect('tickets:sla_management')

    messages.success(request, f'Business calendar "{name}" created successfully.')
    return redirect('tickets:sla_management')

@login_required
@user_passes_test(is_admin)
@require_POST
def rule_create(request):
    priority = request.POST.get('priority')
    timer_type = request.POST.get('timer_type')
    threshold = request.POST.get('threshold_percent')
    action = request.POST.get('action_type')
    if not (priority and timer_type and threshold and action):
        messages.error(request, 'Please fill in priority, timer type, threshold, and action for the escalation rule.')
        return redirect('tickets:sla_management')

    notify_role = request.POST.get('notify_role') if action == 'notify' else None
    reassign_to_role = request.POST.get('reassign_to_role') if action == 'reassign' else None
    try:
        EscalationRule.objects.create(
            priority=priority, timer_type=timer_type, threshold_percent=threshold,
            action_type=action, notify_role=notify_role, reassign_to_role=reassign_to_role
        )
    except Exception as e:
        logger.error(f"Failed to create escalation rule: {e}")
        messages.error(request, 'Could not create the escalation rule. Please check the values and try again.')
        return redirect('tickets:sla_management')

    messages.success(request, 'Escalation rule created successfully.')
    return redirect('tickets:sla_management')

@login_required
@user_passes_test(is_admin)
@require_POST
def rule_delete(request, pk):
    rule = get_object_or_404(EscalationRule, pk=pk)
    rule.delete()
    messages.success(request, 'Escalation rule deleted.')
    return redirect('tickets:sla_management')

@login_required
@user_passes_test(is_admin)
@require_POST
def calendar_delete(request, pk):
    cal = get_object_or_404(BusinessCalendar, pk=pk)
    cal_name = cal.name
    cal.delete()
    messages.success(request, f'Business calendar "{cal_name}" deleted.')
    return redirect('tickets:sla_management')

@login_required
@user_passes_test(is_admin)
def resolved_service_requests(request):
    """Admin-only transparency view: every service request that has reached
    a resolved outcome, org-wide. Distinct from Reports/Exportables, which
    are analytics/export tooling rather than a plain audit list."""
    tickets = Ticket.objects.filter(
        type=Ticket.Type.SERVICE_REQUEST,
        status__in=[Ticket.Status.RESOLVED, Ticket.Status.CLOSED],
    ).select_related('requester', 'assigned_to', 'category').order_by('-updated_at')

    department = request.GET.get('department', '').strip()
    if department:
        tickets = tickets.filter(requester__department=department)

    q = request.GET.get('q', '').strip()
    if q:
        tickets = tickets.filter(
            Q(number__icontains=q) | Q(title__icontains=q) |
            Q(requester__first_name__icontains=q) | Q(requester__last_name__icontains=q) |
            Q(requester__email__icontains=q)
        )

    paginator = Paginator(tickets, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'tickets': page_obj,
        'department_choices': User.DEPARTMENT_CHOICES,
        'department_filter': department,
        'q': q,
        'sidebar_template': get_sidebar_template(request.user),
    }
    if request.headers.get('HX-Request'):
        return render(request, 'partials/resolved_service_requests_table.html', context)
    return render(request, 'admin/resolved_service_requests.html', context)

# ==========================================================================
# MANAGER WORKFLOW (Team Lead reviews service requests)
# ==========================================================================

@login_required
def manager_review_queue(request):
    """Team Lead view – list service requests pending manager review."""
    if request.user.role != User.Role.TEAM_LEAD:
        return HttpResponse(status=403)

    tickets = Ticket.objects.filter(
        status=Ticket.Status.PENDING_MANAGER_REVIEW,
        requester__department=request.user.department
    ).order_by('-created_at')

    context = {
        'tickets': tickets,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'team_lead/manager_review_queue.html', context)


@login_required
def manager_review_ticket(request, pk):
    """Team Lead review page for a single service request."""
    if request.user.role != User.Role.TEAM_LEAD:
        return HttpResponse(status=403)

    ticket = get_object_or_404(Ticket, pk=pk)

    # Security: ensure ticket belongs to Team Lead's department
    if ticket.requester.department != request.user.department:
        return HttpResponse(status=403)

    # Only allow review of PENDING_MANAGER_REVIEW tickets
    if ticket.status != Ticket.Status.PENDING_MANAGER_REVIEW:
        messages.warning(request, f'Ticket {ticket.number} is not pending manager review.')
        return redirect('tickets:manager_review_queue')

    if request.method == 'POST':
        action = request.POST.get('action', '').strip()
        comment = request.POST.get('comment', '').strip()

        # Comment is required for REJECT and REQUEST_CHANGES only
        if action in ['reject', 'request_changes'] and not comment:
            messages.error(request, f'Please provide a comment explaining why you are {action.replace("_", " ")} this request.')
            return redirect('tickets:manager_review_ticket', pk=pk)

        if action == 'approve':
            # ================================================================
            # APPROVAL - Comment is Optional
            # ================================================================
            if ticket.is_asset_request:
                ticket.status = Ticket.Status.PENDING_FULFILLMENT
                ticket.save()
                
                TicketActivityLog.objects.create(
                    ticket=ticket,
                    action='manager_approved',
                    actor=request.user,
                    details={'comment': comment if comment else 'No comment provided', 'routed_to': 'PENDING_FULFILLMENT'}
                )
                
                admins = User.objects.filter(role=User.Role.ADMIN, is_active=True)
                for admin in admins:
                    Notification.objects.create(
                        recipient=admin,
                        role=role_of(admin),
                        message=f'Asset request {ticket.number} from {ticket.requester.get_full_name()} needs fulfillment.',
                        url=reverse('tickets:conversation', args=[ticket.pk])
                    )
                
                Notification.objects.create(
                    recipient=ticket.requester,
                    role=role_of(ticket.requester),
                    message=f'Your asset request {ticket.number} has been approved by your manager and is pending fulfillment.',
                    url=reverse('tickets:detail', args=[ticket.pk])
                )
                
                messages.success(request, f'Asset request {ticket.number} approved. An admin will fulfill it shortly.')
            else:
                ticket.status = Ticket.Status.APPROVED
                ticket.save()
                
                TicketActivityLog.objects.create(
                    ticket=ticket,
                    action='manager_approved',
                    actor=request.user,
                    details={'comment': comment if comment else 'No comment provided', 'routed_to': 'APPROVED'}
                )
                
                Notification.objects.create(
                    recipient=ticket.requester,
                    role=role_of(ticket.requester),
                    message=f'Your service request {ticket.number} has been approved.',
                    url=reverse('tickets:detail', args=[ticket.pk])
                )
                
                agents = User.objects.filter(role__in=[User.Role.AGENT, User.Role.TEAM_LEAD])
                for agent in agents:
                    Notification.objects.create(
                        recipient=agent,
                        role=role_of(agent),
                        message=f'New approved ticket {ticket.number}: {ticket.title}',
                        url=reverse('tickets:detail', args=[ticket.pk])
                    )
                
                messages.success(request, f'Ticket {ticket.number} approved and sent to agent queue.')

        elif action == 'reject':
            ticket.status = Ticket.Status.CLOSED
            ticket.save()
            TicketActivityLog.objects.create(
                ticket=ticket,
                action='manager_rejected',
                actor=request.user,
                details={'comment': comment}
            )
            Notification.objects.create(
                recipient=ticket.requester,
                role=role_of(ticket.requester),
                message=f'Your service request {ticket.number} was rejected by your manager. Reason: {comment}',
                url=reverse('tickets:detail', args=[ticket.pk])
            )
            messages.info(request, f'Ticket {ticket.number} rejected.')

        elif action == 'request_changes':
            ticket.status = Ticket.Status.PENDING_USER
            ticket.save()
            TicketActivityLog.objects.create(
                ticket=ticket,
                action='manager_requested_changes',
                actor=request.user,
                details={'comment': comment}
            )
            Notification.objects.create(
                recipient=ticket.requester,
                role=role_of(ticket.requester),
                message=f'Changes requested for ticket {ticket.number} by your manager: {comment}',
                url=reverse('tickets:detail', args=[ticket.pk])
            )
            messages.info(request, f'Changes requested on ticket {ticket.number}.')

        else:
            messages.error(request, f'Invalid action: "{action}"')
            return redirect('tickets:manager_review_ticket', pk=pk)

        return redirect('tickets:manager_review_queue')

    # GET – render review page
    comments = ticket.comments.all().order_by('created_at')
    initial_attachments = ticket.attachments.filter(comment__isnull=True)
    attachments = ticket.attachments.all().order_by('uploaded_at')

    context = {
        'ticket': ticket,
        'comments': comments,
        'initial_attachments': initial_attachments,
        'attachments': attachments,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'team_lead/manager_review_ticket.html', context)

@login_required
def manager_review_count(request):
    if request.user.role != User.Role.TEAM_LEAD:
        return HttpResponse('')
    count = Ticket.objects.filter(
        status=Ticket.Status.PENDING_MANAGER_REVIEW,
        requester__department=request.user.department
    ).count()
    return render(request, 'partials/manager_review_badge.html', {'count': count})

# ==========================================================================
# ASSET EXPORT
# ==========================================================================

@login_required
def asset_export(request):
    """Export assets as CSV, Excel, or JSON"""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    export_format = request.GET.get('format', 'csv')
    filename = f"assets_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
    
    # Get filtered assets (respect current filters)
    query = request.GET.get('q', '')
    category_filter = request.GET.get('category', '')
    status_filter = request.GET.get('status', '')
    location_filter = request.GET.get('location', '')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    assets = Asset.objects.select_related('category', 'assigned_to').order_by('tracking_id')

    if query:
        assets = assets.filter(
            Q(name__icontains=query) |
            Q(tracking_id__icontains=query) |
            Q(serial_number__icontains=query) |
            Q(model__icontains=query) |
            Q(manufacturer__icontains=query)
        )
    if category_filter:
        assets = assets.filter(category_id=category_filter)
    if status_filter:
        assets = assets.filter(status=status_filter)
    if location_filter:
        assets = assets.filter(location__icontains=location_filter)
    if start_date and end_date:
        try:
            from datetime import datetime
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            assets = assets.filter(created_at__date__gte=start, created_at__date__lte=end)
        except ValueError:
            pass
    
    # Prepare data - Use direct field values since choices were removed
    data = []
    for asset in assets:
        data.append({
            'Tracking ID': asset.tracking_id,
            'Name': asset.name,
            'Category': asset.category.name if asset.category else '',
            'Serial Number': asset.serial_number,
            'Model': asset.model,
            'Manufacturer': asset.manufacturer,
            'Location': asset.location,  # Direct value
            'Status': asset.status,  # Direct value
            'Assigned To': asset.assigned_to.get_full_name() if asset.assigned_to else '',
            'Assigned Department': asset.assigned_to.department if asset.assigned_to else '',
            'Purchase Date': asset.purchase_date.strftime('%Y-%m-%d') if asset.purchase_date else '',
            'Warranty Expiry': asset.warranty_expiry.strftime('%Y-%m-%d') if asset.warranty_expiry else '',
            'Warranty Duration (Years)': asset.warranty_duration_years,
            'Notes': asset.notes,
            'Created': asset.created_at.strftime('%Y-%m-%d %H:%M'),
            'Updated': asset.updated_at.strftime('%Y-%m-%d %H:%M'),
        })
    
    # Export based on format
    if export_format in ('csv', 'excel'):
        # Neutralize spreadsheet formula injection: a value starting with
        # =, +, -, or @ is interpreted as a live formula by Excel/Sheets
        # when the exported file is later opened by another admin.
        def _csv_safe(value):
            s = str(value) if value is not None else ''
            return "'" + s if s and s[0] in ('=', '+', '-', '@') else s

        for row in data:
            for key in ('Name', 'Category', 'Serial Number', 'Model', 'Manufacturer',
                        'Location', 'Assigned To', 'Assigned Department', 'Notes'):
                if key in row:
                    row[key] = _csv_safe(row[key])

    if export_format == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'

        if data:
            writer = csv.DictWriter(response, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return response

    elif export_format == 'excel':
        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'

        wb = Workbook()
        ws = wb.active
        ws.title = "Assets"
        
        if data:
            # Headers
            headers = list(data[0].keys())
            for col, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col, value=header)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
                cell.alignment = Alignment(horizontal='center')
            
            # Data
            for row_idx, row_data in enumerate(data, 2):
                for col_idx, key in enumerate(headers, 1):
                    ws.cell(row=row_idx, column=col_idx, value=row_data.get(key, ''))
            
            # Auto-fit columns
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column].width = adjusted_width
        
        wb.save(response)
        return response
    
    elif export_format == 'json':
        response = HttpResponse(
            json.dumps(data, indent=2),
            content_type='application/json'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}.json"'
        return response
    
    return HttpResponse('Invalid format', status=400)


# ==========================================================================
# ASSET IMPORT
# ==========================================================================

@login_required
@require_POST
def asset_import(request):
    """Import assets from CSV or Excel file"""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    file = request.FILES.get('file')
    if not file:
        messages.error(request, 'Please select a file to import.')
        return redirect('tickets:assets')

    MAX_IMPORT_SIZE = 5 * 1024 * 1024  # 5MB
    if file.size > MAX_IMPORT_SIZE:
        messages.error(request, 'File too large. Maximum size is 5MB.')
        return redirect('tickets:assets')

    # Check file type
    file_name = file.name.lower()
    is_csv = file_name.endswith('.csv')
    is_excel = file_name.endswith(('.xlsx', '.xls'))

    if not (is_csv or is_excel):
        messages.error(request, 'Please upload a CSV or Excel file.')
        return redirect('tickets:assets')
    
    imported = 0
    errors = []
    warnings = []
    
    try:
        if is_csv:
            # Parse CSV
            decoded = file.read().decode('utf-8')
            reader = csv.DictReader(decoded.splitlines())
            rows = list(reader)
        else:
            # Parse Excel
            import openpyxl
            wb = openpyxl.load_workbook(file)
            ws = wb.active
            
            # Get headers from first row
            headers = []
            for cell in ws[1]:
                headers.append(cell.value)
            
            rows = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                row_dict = {}
                for idx, header in enumerate(headers):
                    if idx < len(row):
                        row_dict[header] = row[idx]
                rows.append(row_dict)
        
        # Import each row
        for row_idx, row in enumerate(rows, start=2):  # Start at 2 for Excel row numbers
            try:
                # Skip empty rows
                if not row.get('Name') and not row.get('name'):
                    continue
                
                # Map columns (case-insensitive)
                name = row.get('Name') or row.get('name')
                category_name = row.get('Category') or row.get('category') or row.get('Type') or row.get('type') or ''
                serial_number = row.get('Serial Number') or row.get('serial_number') or row.get('Serial') or ''
                model = row.get('Model') or row.get('model') or ''
                manufacturer = row.get('Manufacturer') or row.get('manufacturer') or ''
                location = row.get('Location') or row.get('location') or ''
                raw_status = str(row.get('Status') or row.get('status') or '').strip().upper()
                valid_statuses = dict(Asset.Status.choices)
                if raw_status and raw_status in valid_statuses:
                    status = raw_status
                else:
                    status = Asset.Status.IN_STORE
                    if raw_status:
                        warnings.append(f"Row {row_idx}: unknown status '{raw_status}', defaulted to In Store.")
                purchase_date = parse_date(row.get('Purchase Date') or row.get('purchase_date'))
                warranty_expiry = parse_date(row.get('Warranty Expiry') or row.get('warranty_expiry'))
                warranty_duration = row.get('Warranty Duration (Years)') or row.get('warranty_duration') or 0
                notes = row.get('Notes') or row.get('notes') or ''
                assigned_to_name = row.get('Assigned To') or row.get('assigned_to') or ''

                # Find assigned user by exact email or exact full-name match
                # (case-insensitive). Ambiguous/ no matches are skipped and
                # flagged rather than guessing via a fuzzy substring match.
                assigned_to = None
                if assigned_to_name:
                    assigned_to_name = str(assigned_to_name).strip()
                    if '@' in assigned_to_name:
                        matches = list(User.objects.filter(email__iexact=assigned_to_name))
                    else:
                        matches = list(User.objects.annotate(
                            full_name=Concat('first_name', Value(' '), 'last_name')
                        ).filter(full_name__iexact=assigned_to_name))
                    if len(matches) == 1:
                        assigned_to = matches[0]
                    elif len(matches) > 1:
                        warnings.append(f"Row {row_idx}: '{assigned_to_name}' matched multiple users, left unassigned.")
                    else:
                        warnings.append(f"Row {row_idx}: no user found matching '{assigned_to_name}', left unassigned.")
                
                # Resolve/create the category by name so imports keep working
                # with whatever labels the sheet uses (mirrors the get_or_create
                # pattern used for inline "add new category" on the asset form).
                category = None
                if category_name:
                    category, _ = AssetCategory.objects.get_or_create(name=category_name.strip())

                # Create asset
                asset = Asset.objects.create(
                    name=name,
                    category=category,
                    serial_number=serial_number,
                    model=model,
                    manufacturer=manufacturer,
                    location=location,
                    status=status,
                    purchase_date=purchase_date if purchase_date else None,
                    warranty_expiry=warranty_expiry if warranty_expiry else None,
                    warranty_duration_years=int(warranty_duration) if warranty_duration else 0,
                    notes=notes,
                    assigned_to=assigned_to,
                )
                
                imported += 1
                
            except Exception as e:
                errors.append(f"Row {row_idx}: {str(e)}")
        
    except Exception as e:
        messages.error(request, f'Error reading file: {str(e)}')
        return redirect('tickets:assets')
    
    # Show results
    if imported > 0:
        messages.success(request, f'✅ Successfully imported {imported} asset(s).')
    if warnings:
        for w in warnings[:10]:
            messages.warning(request, f'⚠️ {w}')
    if errors:
        messages.warning(request, f'⚠️ {len(errors)} error(s) occurred.')
    if not imported and not errors:
        messages.warning(request, 'No assets were imported. Please check your file format.')
    
    return redirect('tickets:assets')


# ==========================================================================
# ASSET FULFILLMENT (Admin only)
# ==========================================================================

@login_required
def fulfill_asset_modal(request, pk):
    """Returns the fulfillment modal for an asset request."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    ticket = get_object_or_404(
        Ticket, pk=pk,
        status__in=[Ticket.Status.PENDING_FULFILLMENT, Ticket.Status.PENDING_VENDOR]
    )

    # Get available assets (IN_STORE or unassigned READY)
    available_assets = Asset.objects.filter(
        status__in=[Asset.Status.IN_STORE, Asset.Status.READY],
        assigned_to__isnull=True
    ).select_related('category').order_by('name')

    # Show what's already mobilized (out) for this ticket's job/vessel(s)/
    # dive system(s), so the admin can check existing issue before approving more.
    already_mobilized = MobilizationItem.objects.none()
    vessel_ids = list(ticket.vessels.values_list('id', flat=True))
    system_ids = list(ticket.dive_systems.values_list('id', flat=True))
    if ticket.job_number_id or vessel_ids or system_ids:
        job_filter = Q()
        if ticket.job_number_id:
            job_filter |= Q(mobilization__job_number_id=ticket.job_number_id)
        if vessel_ids:
            job_filter |= Q(mobilization__vessels__id__in=vessel_ids)
        if system_ids:
            job_filter |= Q(mobilization__dive_systems__id__in=system_ids)
        already_mobilized = MobilizationItem.objects.filter(
            job_filter, demobilized_at__isnull=True
        ).select_related('asset', 'mobilization').distinct()

    open_procurement = ticket.procurement_requests.filter(
        status__in=[AssetProcurementRequest.Status.REQUESTED, AssetProcurementRequest.Status.ORDERED]
    ).select_related('vendor', 'category').first()

    return render(request, 'admin/fulfill_asset_modal.html', {
        'ticket': ticket,
        'available_assets': available_assets,
        'already_mobilized': already_mobilized,
        'open_procurement': open_procurement,
        'procurement_form': ProcurementRequestForm(),
    })


def _mark_asset_ticket_fulfilled(ticket, request, summary):
    """Shared terminal step for both single-asset (_fulfill_ticket_with_asset)
    and mobilization (mobilization_create/_maybe_fulfill_mobilization_ticket)
    fulfillment: instead of resting at APPROVED forever, ask the requester to
    confirm the asset(s) arrived — reuses the PENDING_USER -> confirm_resolution
    machinery Incident tickets already use via resolve_ticket (this module).
    Confirming receipt (confirm_resolution) does NOT resolve the ticket by
    itself for an asset request — it records the confirmation and returns the
    ticket to APPROVED; an agent still explicitly resolves it afterward via
    resolve_ticket, which skips its own confirmation round-trip once receipt
    is already on record (see the is_asset_request branches in both views)."""
    ticket.status = Ticket.Status.PENDING_USER
    ticket.fulfilled_at = timezone.now()
    ticket.fulfilled_by = request.user
    ticket.save(update_fields=['status', 'fulfilled_at', 'fulfilled_by'])

    TicketComment.objects.create(
        ticket=ticket,
        author=request.user,
        body=f"📦 **Fulfilled**: {summary}. Please confirm once received.",
        visibility='PUBLIC'
    )

    Notification.objects.create(
        recipient=ticket.requester,
        role=role_of(ticket.requester),
        message=f'Your request {ticket.number} has been fulfilled — please confirm you received it.',
        url=reverse('tickets:confirm_resolution', args=[ticket.pk]),
        type=Notification.Type.RESOLUTION_CONFIRMATION,
    )

    if ticket.requester.email:
        confirm_url = request.build_absolute_uri(reverse('tickets:confirm_resolution', args=[ticket.pk]))
        html_message = render_to_string('emails/resolution_confirmation.html', {
            'requester_name': ticket.requester.get_full_name() or ticket.requester.email,
            'ticket_number': ticket.number,
            'ticket_title': ticket.title,
            'confirm_url': confirm_url,
            'agent_name': request.user.get_full_name() or request.user.email,
            'is_asset_request': ticket.is_asset_request,
        })
        success, result = send_email_via_brevo(
            to_email=ticket.requester.email,
            subject=f"Please confirm receipt for {ticket.number}",
            html_content=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL
        )
        if not success:
            logger.error(f"Failed to send fulfillment confirmation email: {result}")


def _mobilization_still_awaiting_vendor(mobilization, exclude_pk=None):
    """True if the mobilization has any procurement request still on order
    from a vendor (not yet received or cancelled)."""
    qs = mobilization.procurement_requests.filter(
        status__in=[AssetProcurementRequest.Status.REQUESTED, AssetProcurementRequest.Status.ORDERED]
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def _maybe_fulfill_mobilization_ticket(mobilization, request):
    """Fulfills the mobilization's linked ticket (if any) once every item on
    it is actually in hand — immediately if nothing on this mobilization was
    ever sourced from a vendor, or once the last open vendor procurement
    request against it clears (received or cancelled). Called from
    mobilization_create, procurement_receive, and procurement_cancel — all
    three converge here so the requester is only ever asked to confirm
    receipt once everything has actually arrived, never for a part still on
    order. Idempotent: a no-op once the ticket is already past fulfillment."""
    ticket = mobilization.ticket
    if not ticket or ticket.status not in (Ticket.Status.PENDING_FULFILLMENT, Ticket.Status.PENDING_VENDOR):
        return

    if _mobilization_still_awaiting_vendor(mobilization):
        if ticket.status != Ticket.Status.PENDING_VENDOR:
            ticket.status = Ticket.Status.PENDING_VENDOR
            ticket.save(update_fields=['status'])
        return

    if not mobilization.items.exists():
        # Everything that was on order got cancelled and nothing was ever
        # picked from stock — nothing was actually delivered, so there's
        # nothing to confirm receipt of. Leave the ticket as-is.
        return

    _mark_asset_ticket_fulfilled(ticket, request, summary=f'assets mobilized to {mobilization.destination_display}')
    TicketActivityLog.objects.create(
        ticket=ticket, action='mobilization_fulfilled', actor=request.user,
        details={'mobilization_id': mobilization.pk, 'asset_count': mobilization.items.count()}
    )


def _fulfill_ticket_with_asset(ticket, asset, actor, request, comment=''):
    """Core of fulfilling an asset-request ticket by assigning `asset` to
    the requester — shared by the direct-fulfillment path (an asset was
    already in stock) and the post-receiving path (a procurement request
    for this ticket just arrived). Assumes `asset` has already been
    validated as available; does not re-check `is_available` itself."""
    old_user = asset.assigned_to
    asset.assigned_to = ticket.requester
    asset.save()

    ticket.assigned_asset = asset
    ticket.save(update_fields=['assigned_asset'])
    summary = f'{asset.name} ({asset.tracking_id}) assigned to you'
    if comment:
        summary += f'. {comment}'
    _mark_asset_ticket_fulfilled(ticket, request, summary=summary)

    AssetLog.objects.create(
        asset=asset,
        action=AssetLog.Action.ASSIGNED,
        actor=actor,
        details={
            'from': old_user.get_full_name() if old_user else None,
            'to': ticket.requester.get_full_name(),
            'comment': f'Fulfilled request {ticket.number}: {comment}'
        }
    )

    TicketActivityLog.objects.create(
        ticket=ticket,
        action='asset_fulfilled',
        actor=actor,
        details={
            'asset_id': asset.pk,
            'asset_name': asset.name,
            'asset_tracking_id': asset.tracking_id,
            'assigned_to': ticket.requester.get_full_name()
        }
    )

    Notification.objects.create(
        recipient=ticket.requester,
        role=role_of(ticket.requester),
        message=f'✅ Your asset request {ticket.number} has been fulfilled. {asset.name} assigned to you.',
        url=reverse('tickets:detail', args=[ticket.pk])
    )

    if ticket.requester.email:
        from apps.accounts.models import ClientSettings
        client = ClientSettings.objects.first()
        html_message = render_to_string('emails/asset_fulfilled.html', {
            'requester_name': ticket.requester.get_full_name() or ticket.requester.email,
            'ticket': ticket,
            'asset': asset,
            'ticket_url': request.build_absolute_uri(reverse('tickets:detail', args=[ticket.pk])),
            'logo_url': request.build_absolute_uri(client.logo.url) if client and client.logo else None,
            'client_settings': {
                'company_name': client.company_name if client else 'My Company',
            },
        })
        success, result = send_email_via_brevo(
            to_email=ticket.requester.email,
            subject=f"Your asset request {ticket.number} has been fulfilled",
            html_content=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL
        )
        if not success:
            logger.error(f"Failed to send asset fulfilled email: {result}")


@login_required
@require_POST
def fulfill_asset_request(request, pk):
    """Admin action to fulfill an asset request by assigning an asset."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    ticket = get_object_or_404(
        Ticket, pk=pk,
        status__in=[Ticket.Status.PENDING_FULFILLMENT, Ticket.Status.PENDING_VENDOR]
    )
    asset_id = request.POST.get('asset_id')
    comment = request.POST.get('comment', '').strip()
    
    if not asset_id:
        messages.error(request, 'Please select an asset to assign.')
        return redirect('tickets:conversation', pk=ticket.pk)
    
    with transaction.atomic():
        try:
            asset = Asset.objects.select_for_update().get(pk=asset_id)
        except Asset.DoesNotExist:
            messages.error(request, 'Asset not found.')
            return redirect('tickets:conversation', pk=ticket.pk)

        # Check if asset is already assigned
        if asset.assigned_to:
            messages.error(request, f'Asset {asset.name} is already assigned to {asset.assigned_to.get_full_name()}.')
            return redirect('tickets:conversation', pk=ticket.pk)

        # Check if asset is actually available (not scrapped/retired/lost/etc.)
        if not asset.is_available:
            messages.error(request, f'Asset {asset.name} is not available (status: {asset.get_status_display()}).')
            return redirect('tickets:conversation', pk=ticket.pk)

        _fulfill_ticket_with_asset(ticket, asset, request.user, request, comment=comment)

    messages.success(request, f'✅ Asset {asset.name} assigned to {ticket.requester.get_full_name()}.')
    return redirect('tickets:conversation', pk=ticket.pk)


# ==========================================================================
# VENDOR PROCUREMENT (assets not yet in inventory)
# ==========================================================================

def _notify_new_vendor_proposed(vendor, actor, detail_url):
    """Same propose-and-approve notification shape as mobilization_create's
    third-party-vessel handling — an unrecognized vendor name becomes an
    inactive Vendor row, and Admins are notified to review/activate it."""
    for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
        Notification.objects.create(
            recipient=admin,
            role=role_of(admin),
            message=(
                f'{actor.get_full_name()} referenced "{vendor.name}", a vendor not yet in the system, '
                f'on a procurement request. Review and activate it under System Settings → Vendors if it should be added.'
            ),
            url=detail_url,
        )


@login_required
@require_POST
def procurement_request_create(request, pk):
    """Record that an asset-request ticket's needed item isn't in stock and
    is being sourced from a vendor. Ticket moves to PENDING_VENDOR —
    receiving the item later is what actually fulfills it."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    ticket = get_object_or_404(Ticket, pk=pk, status=Ticket.Status.PENDING_FULFILLMENT)
    form = ProcurementRequestForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect('tickets:conversation', pk=ticket.pk)

    procurement_request = form.save(commit=False)
    procurement_request.vendor = form.cleaned_data.get('vendor')
    procurement_request.ticket = ticket
    procurement_request.requested_by = request.user
    procurement_request.save()

    ticket.status = Ticket.Status.PENDING_VENDOR
    ticket.save(update_fields=['status'])

    TicketComment.objects.create(
        ticket=ticket,
        author=request.user,
        body=f"🛒 **On order**: {procurement_request.item_name} x{procurement_request.quantity} requested from "
             f"{procurement_request.vendor.name if procurement_request.vendor else 'vendor (TBD)'}"
             f"{f', expected {procurement_request.expected_arrival_date}' if procurement_request.expected_arrival_date else ''}.",
        visibility='PUBLIC'
    )
    TicketActivityLog.objects.create(
        ticket=ticket,
        action='procurement_requested',
        actor=request.user,
        details={'procurement_request_id': procurement_request.pk, 'item_name': procurement_request.item_name}
    )
    Notification.objects.create(
        recipient=ticket.requester,
        role=role_of(ticket.requester),
        message=f'🛒 Your asset request {ticket.number} is on order from a vendor. We\'ll notify you once it arrives.',
        url=reverse('tickets:detail', args=[ticket.pk])
    )
    if form.cleaned_data.get('_new_vendor_proposed'):
        _notify_new_vendor_proposed(procurement_request.vendor, request.user, reverse('tickets:conversation', args=[ticket.pk]))

    messages.success(request, f'🛒 {procurement_request.item_name} recorded as on order.')
    return redirect('tickets:conversation', pk=ticket.pk)


@login_required
def procurement_list(request):
    """All vendor procurement requests, filterable by status."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    status_filter = request.GET.get('status', '').strip()
    requests_qs = AssetProcurementRequest.objects.select_related(
        'category', 'vendor', 'ticket', 'mobilization', 'requested_by'
    ).order_by('-requested_at')
    if status_filter:
        requests_qs = requests_qs.filter(status=status_filter)

    return render(request, 'tickets/procurement_list.html', {
        'procurement_requests': requests_qs,
        'status_choices': AssetProcurementRequest.Status.choices,
        'current_status': status_filter,
        'sidebar_template': get_sidebar_template(request.user),
    })


@login_required
@require_POST
def procurement_mark_ordered(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    procurement_request = get_object_or_404(AssetProcurementRequest, pk=pk, status=AssetProcurementRequest.Status.REQUESTED)
    procurement_request.status = AssetProcurementRequest.Status.ORDERED
    procurement_request.save(update_fields=['status'])
    messages.success(request, f'{procurement_request.item_name} marked as ordered.')
    return redirect(request.META.get('HTTP_REFERER') or 'tickets:procurement_list')


@login_required
@require_POST
def procurement_cancel(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    procurement_request = get_object_or_404(AssetProcurementRequest, pk=pk)
    if not procurement_request.is_open:
        messages.error(request, 'Only open procurement requests can be cancelled.')
        return redirect(request.META.get('HTTP_REFERER') or 'tickets:procurement_list')

    procurement_request.status = AssetProcurementRequest.Status.CANCELLED
    procurement_request.save(update_fields=['status'])

    if procurement_request.mobilization_id:
        # Cancelling can be what clears the last thing a mobilization's
        # ticket was waiting on (e.g. 2 items ordered, 1 already received,
        # this one cancelled instead of arriving) — recheck the same way
        # receiving does.
        _maybe_fulfill_mobilization_ticket(procurement_request.mobilization, request)

    Notification.objects.create(
        recipient=procurement_request.requested_by,
        role=role_of(procurement_request.requested_by),
        message=f'❌ Procurement request for {procurement_request.item_name} was cancelled.',
        url=reverse('tickets:procurement_list')
    )
    messages.success(request, f'{procurement_request.item_name} procurement request cancelled.')
    return redirect(request.META.get('HTTP_REFERER') or 'tickets:procurement_list')


@login_required
def procurement_receive_modal(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    procurement_request = get_object_or_404(AssetProcurementRequest, pk=pk)
    if not procurement_request.is_open:
        return HttpResponse('<div class="p-4 text-center text-warning">This request is no longer open.</div>', status=400)

    return render(request, 'partials/procurement_receive_modal.html', {
        'procurement_request': procurement_request,
    })


@login_required
@require_POST
def procurement_receive(request, pk):
    """The item physically arrived — create the real Asset(s)/stock and,
    if this request was for a ticket or a mobilization, automatically
    finish that ticket/mobilization exactly as if the item had come from
    existing stock."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    procurement_request = get_object_or_404(AssetProcurementRequest, pk=pk)
    if not procurement_request.is_open:
        messages.error(request, 'This request is no longer open.')
        return redirect(request.META.get('HTTP_REFERER') or 'tickets:procurement_list')

    with transaction.atomic():
        category = procurement_request.category
        received_assets = []

        if category.is_consumable:
            asset, _ = Asset.objects.select_for_update().get_or_create(
                name=procurement_request.item_name,
                category=category,
                defaults={'created_by': request.user, 'procurement_request': procurement_request}
            )
            asset.quantity_in_stock += procurement_request.quantity
            asset.save(update_fields=['quantity_in_stock'])
            asset.refresh_low_stock_alert()
            received_assets.append(asset)
        else:
            for _ in range(procurement_request.quantity):
                asset = Asset.objects.create(
                    name=procurement_request.item_name,
                    category=category,
                    status=Asset.Status.IN_STORE,
                    created_by=request.user,
                    procurement_request=procurement_request,
                )
                received_assets.append(asset)

        if procurement_request.ticket_id and procurement_request.ticket.status in (
            Ticket.Status.PENDING_FULFILLMENT, Ticket.Status.PENDING_VENDOR
        ):
            ticket = procurement_request.ticket
            fulfillment_asset = received_assets[0]
            _fulfill_ticket_with_asset(
                ticket, fulfillment_asset, request.user, request,
                comment=f'Received from vendor procurement request #{procurement_request.pk}.'
            )
        elif procurement_request.mobilization_id:
            mobilization = procurement_request.mobilization
            for asset in received_assets:
                qty = procurement_request.quantity if category.is_consumable else 1
                MobilizationItem.objects.create(mobilization=mobilization, asset=asset, quantity=qty)
                if category.is_consumable:
                    asset.quantity_in_stock -= qty
                    asset.save(update_fields=['quantity_in_stock'])
                    asset.refresh_low_stock_alert()
                else:
                    asset.status = Asset.Status.MOBILIZED
                    asset.status_updated_at = timezone.now()
                    asset.status_updated_by = request.user
                    asset.save(update_fields=['status', 'status_updated_at', 'status_updated_by'])
                AssetLog.objects.create(
                    asset=asset,
                    action=AssetLog.Action.MOBILIZED,
                    actor=request.user,
                    details={
                        'mobilization_id': mobilization.pk,
                        'destination': mobilization.destination_display,
                        'quantity': qty,
                        'procurement_request_id': procurement_request.pk,
                    }
                )

        procurement_request.status = AssetProcurementRequest.Status.RECEIVED
        procurement_request.received_at = timezone.now()
        procurement_request.received_by = request.user
        procurement_request.save(update_fields=['status', 'received_at', 'received_by'])

        if procurement_request.mobilization_id:
            # Now that this one's marked RECEIVED, check whether it was the
            # last thing this mobilization's ticket (if any) was waiting on.
            _maybe_fulfill_mobilization_ticket(procurement_request.mobilization, request)

    Notification.objects.create(
        recipient=procurement_request.requested_by,
        role=role_of(procurement_request.requested_by),
        message=f'📦 {procurement_request.item_name} has been received and added to inventory.',
        url=reverse('tickets:procurement_list')
    )
    messages.success(request, f'📦 {procurement_request.item_name} received.')
    return redirect(request.META.get('HTTP_REFERER') or 'tickets:procurement_list')


@login_required
def procurement_export_pdf(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    procurement_request = get_object_or_404(
        AssetProcurementRequest.objects.select_related('category', 'vendor', 'ticket', 'mobilization', 'requested_by'),
        pk=pk
    )
    from .report_exporters import export_procurement_request_pdf
    return export_procurement_request_pdf(procurement_request, request)


@login_required
def available_assets_for_fulfillment(request):
    """HTMX endpoint to get available assets for a specific request."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    search = request.GET.get('search', '').strip()
    category = request.GET.get('category', '').strip()
    
    # Filter available assets (unassigned and active/in-store)
    assets = Asset.objects.filter(
        assigned_to__isnull=True,
        status__in=[Asset.Status.IN_STORE, Asset.Status.READY]
    ).select_related('category').order_by('name')
    
    # Filter by search term
    if search:
        assets = assets.filter(
            Q(name__icontains=search) |
            Q(tracking_id__icontains=search) |
            Q(serial_number__icontains=search) |
            Q(model__icontains=search) |
            Q(manufacturer__icontains=search)
        )

    # Optional: Filter by asset category based on the ticket's request category
    type_mapping = {
        'Hardware': ['Computer', 'Laptop', 'Printer', 'Server', 'Network Device'],
        'Software': ['Software License'],
        'Network': ['Network Device', 'Server'],
        'Printer': ['Printer'],
        'Computer': ['Computer', 'Laptop'],
    }

    if category in type_mapping:
        assets = assets.filter(category__name__in=type_mapping[category])

    # Limit results
    assets = assets[:20]
    
    return render(request, 'partials/available_assets_list.html', {
        'assets': assets,
    })


# apps/tickets/views.py - Add these new functions

# ==========================================================================
# ASSET CHECK-IN/CHECK-OUT
# ==========================================================================

@login_required
def asset_checkout_modal(request, pk):
    """Return the checkout modal for an asset."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    
    # Only allow checkout if asset is available
    if asset.is_checked_out:
        return HttpResponse('<div class="p-4 text-center text-error">This asset is already checked out.</div>', status=400)
    
    # Get users for dropdown (only active users)
    users = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
    
    return render(request, 'partials/asset_checkout_modal.html', {
        'asset': asset,
        'users': users,
    })


@login_required
@require_POST
def asset_checkout(request, pk):
    """Check out an asset to a user."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    user_id = request.POST.get('user_id')
    expected_return = request.POST.get('expected_return_date')
    notes = request.POST.get('notes', '').strip()

    if not user_id:
        messages.error(request, 'Please select a user to check out this asset.')
        return redirect('tickets:assets')

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('tickets:assets')

    with transaction.atomic():
        asset = get_object_or_404(Asset.objects.select_for_update(), pk=pk)

        # Only allow checkout if asset is available
        if asset.is_checked_out:
            messages.error(request, 'This asset is already checked out.')
            return redirect('tickets:assets')

        # Update asset
        asset.checked_out_to = user
        asset.checked_out_at = timezone.now()
        asset.assigned_to = user  # Keep the existing field in sync
        asset.status = Asset.Status.CHECKED_OUT
        asset.status_updated_at = timezone.now()
        asset.status_updated_by = request.user
        if expected_return:
            try:
                asset.expected_return_date = datetime.strptime(expected_return, '%Y-%m-%d').date()
            except ValueError:
                pass
        asset.save()
    
    # Create history record
    AssetCheckoutHistory.objects.create(
        asset=asset,
        checked_out_by=request.user,
        checked_out_to=user,
        checked_out_at=asset.checked_out_at,
        expected_return_date=asset.expected_return_date,
        notes=notes
    )
    
    # Create asset log
    AssetLog.objects.create(
        asset=asset,
        action=AssetLog.Action.ASSIGNED,
        actor=request.user,
        details={
            'action': 'checkout',
            'to': user.get_full_name() or user.email,
            'notes': notes
        }
    )
    
    # Add comment to asset notes
    checkout_note = f"🔄 **Asset checked out** by {request.user.get_full_name()} to {user.get_full_name()} on {timezone.now().strftime('%Y-%m-%d %H:%M')}"
    if notes:
        checkout_note += f"\nNotes: {notes}"
    if asset.notes:
        asset.notes = f"{asset.notes}\n\n{checkout_note}"
    else:
        asset.notes = checkout_note
    asset.save(update_fields=['notes'])
    
    # Notify user
    Notification.objects.create(
        recipient=user,
        role=role_of(user),
        message=f"📦 Asset {asset.name} ({asset.tracking_id}) has been checked out to you.",
        url=reverse('tickets:asset_detail', args=[asset.pk])
    )
    
    messages.success(request, f'Asset "{asset.name}" checked out to {user.get_full_name()}.')
    return redirect('tickets:assets')


@login_required
def asset_checkin_modal(request, pk):
    """Return the checkin modal for an asset."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    
    # Only allow checkin if asset is checked out
    if not asset.is_checked_out:
        return HttpResponse('<div class="p-4 text-center text-warning">This asset is not currently checked out.</div>', status=400)
    
    return render(request, 'partials/asset_checkin_modal.html', {
        'asset': asset,
        'return_reasons': Asset.ReturnReason.choices,
    })


@login_required
@require_POST
def asset_checkin(request, pk):
    """Check in an asset."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    
    # Only allow checkin if asset is checked out
    if not asset.is_checked_out:
        messages.error(request, 'This asset is not currently checked out.')
        return redirect('tickets:assets')
    
    return_reason = request.POST.get('return_reason')
    return_comment = request.POST.get('return_comment', '').strip()
    return_condition = request.POST.get('return_condition', '').strip()
    
    if not return_reason:
        messages.error(request, 'Please select a return reason.')
        return redirect('tickets:assets')
    
    # Get the active checkout history record
    history = AssetCheckoutHistory.objects.filter(
        asset=asset,
        checked_in_at__isnull=True
    ).first()
    
    # Update asset
    asset.return_reason = return_reason
    asset.return_comment = return_comment
    asset.return_condition = return_condition
    asset.returned_at = timezone.now()
    asset.checked_out_to = None
    asset.assigned_to = None  # Clear the legacy field too
    if return_condition.upper() in [Asset.Condition.DAMAGED, Asset.Condition.UNUSABLE]:
        asset.status = Asset.Status.MAINTENANCE
    else:
        asset.status = Asset.Status.IN_STORE
    asset.status_updated_at = timezone.now()
    asset.status_updated_by = request.user
    asset.save()
    
    # Update history record
    if history:
        history.checked_in_by = request.user
        history.checked_in_at = asset.returned_at
        history.return_reason = return_reason
        history.return_comment = return_comment
        history.return_condition = return_condition
        history.save()
    
    # Create asset log
    AssetLog.objects.create(
        asset=asset,
        action=AssetLog.Action.UNASSIGNED,
        actor=request.user,
        details={
            'action': 'checkin',
            'reason': asset.get_return_reason_display(),
            'condition': return_condition,
            'comment': return_comment
        }
    )
    
    # Add comment to asset notes
    checkin_note = f"🔄 **Asset checked in** by {request.user.get_full_name()} on {timezone.now().strftime('%Y-%m-%d %H:%M')}"
    checkin_note += f"\nReason: {asset.get_return_reason_display()}"
    if return_condition:
        checkin_note += f"\nCondition: {return_condition}"
    if return_comment:
        checkin_note += f"\nComment: {return_comment}"
    
    if asset.notes:
        asset.notes = f"{asset.notes}\n\n{checkin_note}"
    else:
        asset.notes = checkin_note
    asset.save(update_fields=['notes'])
    
    messages.success(request, f'Asset "{asset.name}" checked in successfully.')
    return redirect('tickets:assets')


@login_required
def asset_checkout_history(request, pk):
    """View checkout history for an asset."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'TEAM_LEAD']:
        return HttpResponse(status=403)
    
    asset = get_object_or_404(Asset, pk=pk)
    history = asset.checkout_history.all().order_by('-checked_out_at')
    
    return render(request, 'partials/asset_checkout_history.html', {
        'asset': asset,
        'history': history,
    })


# ==========================================================================
# MOBILIZATION / DEMOBILIZATION
# ==========================================================================

@login_required
def mobilizations(request):
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'AGENT', 'TEAM_LEAD'] or request.user.department != 'IT':
        return HttpResponse(status=403)

    job_filter = request.GET.get('filter_job', '')
    vessel_filter = request.GET.get('filter_vessel', '')
    system_filter = request.GET.get('filter_system', '')
    status_filter = request.GET.get('filter_status', '')

    mobilizations_list = Mobilization.objects.select_related('job_number', 'mobilized_by').prefetch_related('vessels', 'dive_systems', 'items__asset')

    if job_filter:
        mobilizations_list = mobilizations_list.filter(job_number_id=job_filter)
    if vessel_filter:
        mobilizations_list = mobilizations_list.filter(vessels__id=vessel_filter)
    if system_filter:
        mobilizations_list = mobilizations_list.filter(dive_systems__id=system_filter)
    if status_filter:
        mobilizations_list = mobilizations_list.filter(status=status_filter)

    mobilizations_list = mobilizations_list.distinct()

    paginator = Paginator(mobilizations_list, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'mobilizations': page_obj,
        'job_numbers': JobNumber.objects.filter(is_active=True),
        'vessels': Vessel.objects.filter(is_active=True),
        'dive_systems': DiveSystem.objects.filter(is_active=True),
        'status_choices': Mobilization.Status.choices,
        'selected_job': job_filter,
        'selected_vessel': vessel_filter,
        'selected_system': system_filter,
        'selected_status': status_filter,
        'sidebar_template': get_sidebar_template(request.user),
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/mobilization_table.html', context)

    return render(request, 'tickets/mobilization_list.html', context)


@login_required
def mobilization_detail(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN', 'AGENT', 'TEAM_LEAD'] or request.user.department != 'IT':
        return HttpResponse(status=403)

    mobilization = get_object_or_404(
        Mobilization.objects.select_related('job_number', 'mobilized_by', 'ticket').prefetch_related(
            'vessels', 'dive_systems', 'items__asset', 'date_extensions__extended_by'
        ),
        pk=pk
    )

    return render(request, 'tickets/mobilization_detail.html', {
        'mobilization': mobilization,
        'items': mobilization.items.select_related('asset', 'demobilized_by').all(),
        'date_extensions': mobilization.date_extensions.all(),
        'sidebar_template': get_sidebar_template(request.user),
    })


@login_required
def mobilization_create_modal(request):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    form = MobilizationForm()
    ticket_id = request.GET.get('ticket_id')
    ticket = Ticket.objects.filter(pk=ticket_id).first() if ticket_id else None

    prefill_category = None
    prefill_quantity = None
    if ticket:
        form = MobilizationForm(initial={
            'job_number': ticket.job_number_id,
            'vessels': ticket.vessels.values_list('id', flat=True),
            'dive_systems': ticket.dive_systems.values_list('id', flat=True),
            'notes': ticket.purpose,
        })

        # Carry over what the request itself already said it needed — the
        # ASSET field group's asset_type/number_of_assets — into the Quick
        # Add by Quantity picker, so the admin isn't retyping what the
        # requester already specified. No expected_return_date prefill:
        # nothing on the request captures a target return date today.
        if ticket.service_category and ticket.service_category.field_group == ServiceCategory.FieldGroup.ASSET:
            details = ticket.service_request_details or {}
            asset_type = details.get('asset_type')
            if asset_type:
                for f in fields_for_group(ServiceCategory.FieldGroup.ASSET):
                    if f.key == 'asset_type':
                        label = display_value_for_field(f, asset_type)
                        prefill_category = AssetCategory.objects.filter(name__iexact=label).first()
                        break
            try:
                prefill_quantity = int(details.get('number_of_assets') or 0) or None
            except (TypeError, ValueError):
                prefill_quantity = None

    return render(request, 'partials/mobilization_create_modal.html', {
        'form': form,
        'ticket': ticket,
        'trackable_categories': AssetCategory.objects.filter(is_consumable=False).order_by('name'),
        'asset_categories': AssetCategory.objects.all().order_by('name'),
        'vendors': Vendor.objects.filter(is_active=True).prefetch_related('categories').order_by('name'),
        'prefill_category': prefill_category,
        'prefill_quantity': prefill_quantity,
    })


@login_required
@require_POST
def mobilization_create(request):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    form = MobilizationForm(request.POST)
    asset_ids = request.POST.getlist('asset_ids')
    ticket_id = request.POST.get('ticket_id')

    # Vendor-request rows: item name / category / quantity / vendor /
    # expected date, one set of parallel arrays per row — same
    # multi-value-under-one-name shape as third_party_vessels above.
    procurement_item_names = request.POST.getlist('procurement_item_name')
    procurement_category_ids = request.POST.getlist('procurement_category_id')
    procurement_quantities = request.POST.getlist('procurement_quantity')
    procurement_vendor_ids = request.POST.getlist('procurement_vendor_id')
    procurement_vendor_names = request.POST.getlist('procurement_vendor_name')
    procurement_dates = request.POST.getlist('procurement_expected_date')
    has_procurement_rows = any(name.strip() for name in procurement_item_names)

    if not asset_ids and not has_procurement_rows:
        messages.error(request, 'Select at least one asset to mobilize, or add a vendor-request line item.')
        return redirect('tickets:mobilizations')

    if not form.is_valid():
        for field_errors in form.errors.values():
            for error in field_errors:
                messages.error(request, error)
        return redirect('tickets:mobilizations')

    with transaction.atomic():
        assets_qs = Asset.objects.select_for_update().filter(pk__in=asset_ids)
        unavailable = [a for a in assets_qs if not a.is_available]
        if unavailable:
            names = ', '.join(a.tracking_id for a in unavailable)
            messages.error(request, f'These assets are not available to mobilize: {names}.')
            return redirect('tickets:mobilizations')

        # Quantity per asset — only meaningful for consumable/bulk stock
        # (e.g. "5 units of cable ties"). Individually-tracked assets are
        # always exactly 1, regardless of what's posted.
        quantities = {}
        insufficient_stock = []
        for asset in assets_qs:
            if asset.is_consumable:
                try:
                    requested = int(request.POST.get(f'quantity_{asset.pk}', 1))
                except (TypeError, ValueError):
                    requested = 1
                requested = max(1, requested)
                if requested > asset.quantity_in_stock:
                    insufficient_stock.append(asset)
                quantities[asset.pk] = requested
            else:
                quantities[asset.pk] = 1
        if insufficient_stock:
            names = ', '.join(a.name for a in insufficient_stock)
            messages.error(request, f'Not enough stock to mobilize the requested quantity for: {names}.')
            return redirect('tickets:mobilizations')

        ticket = Ticket.objects.filter(pk=ticket_id).first() if ticket_id else None

        mobilization = form.save(commit=False)
        mobilization.mobilized_by = request.user
        mobilization.mobilized_at = timezone.now()
        mobilization.ticket = ticket
        mobilization.original_expected_return_date = mobilization.expected_return_date
        mobilization.save()
        form.save_m2m()

        # Third-party vessels: reuse an existing proposal case-insensitively,
        # else create one pending approval (is_active=False) — same
        # propose-and-approve shape as Job Number. The proposer's own
        # mobilization can reference it immediately even while pending.
        new_third_party_vessels = []
        for name in form.cleaned_data.get('third_party_vessels', []):
            vessel = Vessel.objects.filter(name__iexact=name).first()
            if not vessel:
                vessel = Vessel.objects.create(name=name, is_active=False, proposed_by=request.user)
                new_third_party_vessels.append(vessel)
            mobilization.vessels.add(vessel)

        # Vendor-request line items: items wanted for this job that aren't
        # in stock — recorded against this mobilization, fulfilled later via
        # the Procurement "Receive" step, same as an asset-request ticket.
        new_procurement_vendors = []
        for i, item_name in enumerate(procurement_item_names):
            item_name = item_name.strip()
            if not item_name:
                continue
            category_id = procurement_category_ids[i] if i < len(procurement_category_ids) else None
            category = AssetCategory.objects.filter(pk=category_id).first() if category_id else None
            if not category:
                continue
            try:
                qty = max(1, int(procurement_quantities[i])) if i < len(procurement_quantities) else 1
            except (TypeError, ValueError):
                qty = 1

            vendor = None
            vendor_id = procurement_vendor_ids[i] if i < len(procurement_vendor_ids) else ''
            vendor_name = procurement_vendor_names[i].strip() if i < len(procurement_vendor_names) else ''
            if vendor_id:
                vendor = Vendor.objects.filter(pk=vendor_id).first()
            elif vendor_name:
                vendor, created = Vendor.objects.get_or_create(
                    name__iexact=vendor_name, defaults={'name': vendor_name, 'is_active': False}
                )
                if created:
                    new_procurement_vendors.append(vendor)

            expected_date = procurement_dates[i] if i < len(procurement_dates) else ''

            AssetProcurementRequest.objects.create(
                item_name=item_name,
                category=category,
                quantity=qty,
                vendor=vendor,
                expected_arrival_date=expected_date or None,
                mobilization=mobilization,
                requested_by=request.user,
            )

        for asset in assets_qs:
            qty = quantities[asset.pk]
            MobilizationItem.objects.create(mobilization=mobilization, asset=asset, quantity=qty)

            if asset.is_consumable:
                # SKU-level record stays IN_STORE throughout — only the
                # remaining count changes, since other units of the same
                # stock may still be available.
                asset.quantity_in_stock -= qty
                asset.save(update_fields=['quantity_in_stock'])
                asset.refresh_low_stock_alert()
            else:
                asset.status = Asset.Status.MOBILIZED
                asset.status_updated_at = timezone.now()
                asset.status_updated_by = request.user
                asset.save(update_fields=['status', 'status_updated_at', 'status_updated_by'])

            AssetLog.objects.create(
                asset=asset,
                action=AssetLog.Action.MOBILIZED,
                actor=request.user,
                details={
                    'mobilization_id': mobilization.pk,
                    'destination': mobilization.destination_display,
                    'quantity': qty,
                }
            )

    if ticket:
        TicketComment.objects.create(
            ticket=ticket,
            author=request.user,
            body=f"📦 **Assets mobilized**: {', '.join(a.tracking_id for a in assets_qs)} sent to {mobilization.destination_display}.",
            visibility='PUBLIC'
        )
        # Only actually fulfills the ticket (and prompts the requester to
        # confirm receipt) once nothing on this mobilization is still on
        # order from a vendor — a procurement-only mobilization instead
        # routes the ticket to PENDING_VENDOR here and gets fulfilled later,
        # from procurement_receive/procurement_cancel, once that clears.
        _maybe_fulfill_mobilization_ticket(mobilization, request)

    for vessel in new_third_party_vessels:
        for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
            Notification.objects.create(
                recipient=admin,
                role=role_of(admin),
                message=(
                    f'{request.user.get_full_name()} mobilized assets to "{vessel.name}", a third-party vessel '
                    f'not yet in the system. Review and activate it under System Settings → Vessels if it should be added.'
                ),
                url=reverse('tickets:mobilization_detail', args=[mobilization.pk]),
            )

    for vendor in new_procurement_vendors:
        _notify_new_vendor_proposed(vendor, request.user, reverse('tickets:mobilization_detail', args=[mobilization.pk]))

    summary_parts = []
    if assets_qs.count():
        summary_parts.append(f'{assets_qs.count()} asset(s) mobilized')
    procurement_count = mobilization.procurement_requests.count()
    if procurement_count:
        summary_parts.append(f'{procurement_count} item(s) recorded as on order')
    messages.success(request, f'{" and ".join(summary_parts)} to {mobilization.destination_display}.')
    return redirect('tickets:mobilization_detail', pk=mobilization.pk)


@login_required
def mobilization_available_assets(request):
    """HTMX endpoint: assets available to add to a new mobilization."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    search = request.GET.get('search', '').strip()

    assets_qs = Asset.objects.filter(
        status__in=[Asset.Status.IN_STORE, Asset.Status.READY],
        checked_out_to__isnull=True,
    ).exclude(
        category__is_consumable=True, quantity_in_stock__lte=0,
    ).select_related('category').order_by('name')

    if search:
        assets_qs = assets_qs.filter(
            Q(name__icontains=search) |
            Q(tracking_id__icontains=search) |
            Q(serial_number__icontains=search) |
            Q(model__icontains=search) |
            Q(manufacturer__icontains=search)
        )

    assets_qs = assets_qs[:20]

    return render(request, 'partials/mobilization_available_assets_list.html', {
        'assets': assets_qs,
    })


@login_required
def mobilization_autopick_assets(request):
    """HTMX/JSON endpoint: given a category + quantity, return up to that
    many available individually-tracked assets in that category. This only
    speeds up *selection* — the returned IDs still go through the exact same
    `asset_ids` list and select_for_update() re-validation in
    mobilization_create as a manually-checked pick, so a race between pick
    and submit just surfaces the existing "not available" error there."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    category_id = request.GET.get('category_id')
    try:
        quantity = int(request.GET.get('quantity', 0))
    except (TypeError, ValueError):
        quantity = 0
    quantity = max(0, min(quantity, 50))

    if not category_id or quantity == 0:
        return JsonResponse({'assets': []})

    assets_qs = Asset.objects.filter(
        category_id=category_id,
        category__is_consumable=False,
        status__in=[Asset.Status.IN_STORE, Asset.Status.READY],
        checked_out_to__isnull=True,
    ).order_by('tracking_id')[:quantity]

    return JsonResponse({
        'assets': [
            {'id': asset.pk, 'name': asset.name, 'tracking_id': asset.tracking_id}
            for asset in assets_qs
        ]
    })


@login_required
def mobilization_item_demobilize_modal(request, item_pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    item = get_object_or_404(MobilizationItem.objects.select_related('asset', 'mobilization'), pk=item_pk)
    if not item.is_active:
        return HttpResponse('<div class="p-4 text-center text-warning">This asset has already been demobilized.</div>', status=400)

    return render(request, 'partials/mobilization_demobilize_modal.html', {
        'item': item,
        'condition_choices': Asset.Condition.choices,
    })


def _demobilize_item(item, return_condition, return_notes, actor, return_quantity=None):
    """Core of returning one MobilizationItem's asset to inventory — shared
    by the single-item demobilize view and the batch "Demobilize All" view.
    Does not call item.mobilization.refresh_status(); callers do that once
    after all items in a batch are processed, to avoid redundant recomputes."""
    asset = item.asset

    item.demobilized_at = timezone.now()
    item.demobilized_by = actor
    item.return_condition = return_condition
    item.return_notes = return_notes

    if asset.is_consumable:
        # Partial returns: only the portion actually coming back to usable
        # stock is restored. Damaged/unusable consumables aren't restocked
        # at all — they're treated as consumed, not returned.
        if return_quantity is None:
            return_quantity = item.quantity
        return_quantity = max(0, min(return_quantity, item.quantity))
        item.return_quantity = return_quantity
        item.save()

        if return_condition not in [Asset.Condition.DAMAGED, Asset.Condition.UNUSABLE]:
            asset.quantity_in_stock += return_quantity
            asset.save(update_fields=['quantity_in_stock'])
            asset.refresh_low_stock_alert()
    else:
        item.save()
        # Damaged/unusable gear goes to maintenance instead of straight back onto the shelf.
        if return_condition in [Asset.Condition.DAMAGED, Asset.Condition.UNUSABLE]:
            asset.status = Asset.Status.MAINTENANCE
        else:
            asset.status = Asset.Status.IN_STORE
        asset.condition = return_condition
        asset.status_updated_at = timezone.now()
        asset.status_updated_by = actor
        asset.save(update_fields=['status', 'condition', 'status_updated_at', 'status_updated_by'])

    AssetLog.objects.create(
        asset=asset,
        action=AssetLog.Action.DEMOBILIZED,
        actor=actor,
        details={
            'mobilization_id': item.mobilization_id,
            'condition': return_condition,
            'notes': return_notes,
        }
    )


@login_required
@require_POST
def mobilization_item_demobilize(request, item_pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    item = get_object_or_404(MobilizationItem.objects.select_related('asset', 'mobilization'), pk=item_pk)
    if not item.is_active:
        messages.error(request, 'This asset has already been demobilized.')
        return redirect('tickets:mobilization_detail', pk=item.mobilization_id)

    return_condition = request.POST.get('return_condition')
    return_notes = request.POST.get('return_notes', '').strip()

    if not return_condition:
        messages.error(request, 'Please select the returned condition.')
        return redirect('tickets:mobilization_detail', pk=item.mobilization_id)

    try:
        return_quantity = int(request.POST.get('return_quantity', item.quantity))
    except (TypeError, ValueError):
        return_quantity = item.quantity

    asset_name = item.asset.name
    _demobilize_item(item, return_condition, return_notes, request.user, return_quantity=return_quantity)
    item.mobilization.refresh_status()

    messages.success(request, f'Asset "{asset_name}" demobilized and returned to inventory.')
    return redirect('tickets:mobilization_detail', pk=item.mobilization_id)


@login_required
def mobilization_demobilize_all_modal(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    mobilization = get_object_or_404(Mobilization, pk=pk)
    active_items = mobilization.items.filter(demobilized_at__isnull=True).select_related('asset')
    if not active_items.exists():
        return HttpResponse('<div class="p-4 text-center text-warning">Every asset on this mobilization has already been demobilized.</div>', status=400)

    return render(request, 'partials/mobilization_demobilize_all_modal.html', {
        'mobilization': mobilization,
        'items': active_items,
        'condition_choices': Asset.Condition.choices,
    })


@login_required
@require_POST
def mobilization_demobilize_all(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    mobilization = get_object_or_404(Mobilization, pk=pk)
    return_condition = request.POST.get('return_condition')
    return_notes = request.POST.get('return_notes', '').strip()

    if not return_condition:
        messages.error(request, 'Please select the returned condition.')
        return redirect('tickets:mobilization_detail', pk=pk)

    with transaction.atomic():
        items = list(
            mobilization.items.select_for_update().filter(demobilized_at__isnull=True).select_related('asset')
        )
        if not items:
            messages.warning(request, 'Every asset on this mobilization has already been demobilized.')
            return redirect('tickets:mobilization_detail', pk=pk)

        for item in items:
            _demobilize_item(item, return_condition, return_notes, request.user)

        mobilization.refresh_status()

    messages.success(request, f'{len(items)} asset(s) demobilized and returned to inventory.')
    return redirect('tickets:mobilization_detail', pk=pk)


@login_required
def mobilization_extend_date_modal(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    mobilization = get_object_or_404(Mobilization, pk=pk)
    if mobilization.status != Mobilization.Status.ACTIVE:
        return HttpResponse('<div class="p-4 text-center text-warning">Only an active mobilization\'s return date can be extended.</div>', status=400)

    return render(request, 'partials/mobilization_extend_date_modal.html', {
        'mobilization': mobilization,
    })


@login_required
@require_POST
def mobilization_extend_date(request, pk):
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    mobilization = get_object_or_404(Mobilization, pk=pk)
    if mobilization.status != Mobilization.Status.ACTIVE:
        messages.error(request, 'Only an active mobilization\'s return date can be extended.')
        return redirect('tickets:mobilization_detail', pk=pk)

    new_date_raw = request.POST.get('new_date', '').strip()
    reason = request.POST.get('reason', '').strip()

    if not new_date_raw:
        messages.error(request, 'Please choose a new return date.')
        return redirect('tickets:mobilization_detail', pk=pk)

    try:
        new_date = date.fromisoformat(new_date_raw)
    except ValueError:
        messages.error(request, 'Invalid date.')
        return redirect('tickets:mobilization_detail', pk=pk)

    previous_date = mobilization.expected_return_date
    if previous_date and new_date <= previous_date:
        messages.error(request, 'The new return date must be after the current return date.')
        return redirect('tickets:mobilization_detail', pk=pk)

    MobilizationDateExtension.objects.create(
        mobilization=mobilization,
        previous_date=previous_date,
        new_date=new_date,
        reason=reason,
        extended_by=request.user,
    )
    mobilization.expected_return_date = new_date
    mobilization.save(update_fields=['expected_return_date'])

    messages.success(request, f'Return date extended to {new_date.strftime("%b %d, %Y")}.')
    return redirect('tickets:mobilization_detail', pk=pk)


@login_required
def job_mobilization_lookup(request):
    """HTMX endpoint used from the asset-request fulfillment screen: shows
    what's currently mobilized (out) for a given job/vessel/dive system, so
    an admin can check existing issue before approving more."""
    if request.user.role not in ['ADMIN', 'SUPERADMIN']:
        return HttpResponse(status=403)

    job_id = request.GET.get('job_number')
    vessel_ids = request.GET.getlist('vessel')
    system_ids = request.GET.getlist('dive_system')

    items = MobilizationItem.objects.filter(demobilized_at__isnull=True).select_related('asset', 'mobilization')

    filters = Q()
    matched = False
    if job_id:
        filters |= Q(mobilization__job_number_id=job_id)
        matched = True
    if vessel_ids:
        filters |= Q(mobilization__vessels__id__in=vessel_ids)
        matched = True
    if system_ids:
        filters |= Q(mobilization__dive_systems__id__in=system_ids)
        matched = True

    items = items.filter(filters).distinct() if matched else items.none()

    return render(request, 'partials/job_mobilization_lookup.html', {
        'items': items,
    })