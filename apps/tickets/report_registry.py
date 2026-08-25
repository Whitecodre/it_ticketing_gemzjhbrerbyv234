# apps/tickets/report_registry.py
"""
Central registry of exportable report types for the enterprise Exportables
feature. Each ReportType bundles: how to filter its queryset from request
GET params, how to turn one object into a flat row for export/preview, and
the filter-field UI to render. Adding a new exportable data type later means
adding one more ReportType entry here — the views, templates, and exporters
are all generic over this registry.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.utils import timezone

from .models import Ticket, Asset, ServiceCategory, AssetCategory
from apps.accounts.models import User
from apps.maintenance.models import MaintenanceSchedule, MaintenanceActivityLog, MaintenanceAssetConfirmation
from apps.common.permissions import effective_role_name


def _date_range_filter(request, field_name):
    """Shared start_date/end_date GET-param parsing (matches the pattern
    already used across the app's existing export views)."""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if not (start_date and end_date):
        return {}
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return {}
    return {f'{field_name}__date__gte': start, f'{field_name}__date__lte': end}


@dataclass
class FilterField:
    key: str
    label: str
    kind: str  # 'select' | 'text'
    choices: list = field(default_factory=list)
    placeholder: str = ''


@dataclass
class ReportType:
    slug: str
    label: str
    icon: str
    permission_roles: list
    get_queryset: object
    row_from_obj: object
    columns: list
    filter_fields: list = field(default_factory=list)
    date_field_label: str = 'Date'
    # Optional: overrides the generic key-value detail page with a
    # form-styled one (currently only Incidents/Service Requests have a real
    # paper form to match).
    detail_template: str = None


# ================================================================
# SERVICE REQUESTS
# ================================================================

def _service_requests_queryset(request):
    tickets = Ticket.objects.filter(type=Ticket.Type.SERVICE_REQUEST).select_related('requester', 'assigned_to', 'service_category').prefetch_related('vessels')
    status = request.GET.get('status')
    if status and status in dict(Ticket.Status.choices):
        tickets = tickets.filter(status=status)
    service_category = request.GET.get('service_category')
    if service_category:
        tickets = tickets.filter(service_category_id=service_category)
    tickets = tickets.filter(**_date_range_filter(request, 'created_at'))
    return tickets.order_by('-created_at')


def _service_request_row(ticket):
    vessels = ', '.join(v.name for v in ticket.vessels.all()) or '—'
    dive_systems = ', '.join(s.name for s in ticket.dive_systems.all()) or '—'
    return OrderedDict([
        ('Number', ticket.number),
        ('Title', ticket.title),
        ('Status', ticket.get_status_display()),
        ('Priority', ticket.get_priority_display()),
        ('Service Category', ticket.service_category.name if ticket.service_category else '—'),
        ('Purpose', ticket.purpose or '—'),
        ('Vessels', vessels),
        ('Job Number', ticket.job_number.number if ticket.job_number else '—'),
        ('Dive Systems', dive_systems),
        ('Requester', ticket.requester.get_full_name() or ticket.requester.email),
        ('Requester Department', ticket.requester.get_department_display()),
        ('Assigned To', ticket.assigned_to.get_full_name() if ticket.assigned_to else 'Unassigned'),
        ('Created', ticket.created_at.strftime('%Y-%m-%d %H:%M')),
        ('Fulfilled', ticket.fulfilled_at.strftime('%Y-%m-%d %H:%M') if ticket.fulfilled_at else '—'),
        ('Fulfilled By', ticket.fulfilled_by.get_full_name() if ticket.fulfilled_by else '—'),
        ('Receipt Confirmed', ticket.resolution_confirmed_at.strftime('%Y-%m-%d %H:%M') if ticket.resolution_confirmed_at else '—'),
        ('Receipt Confirmed By', ticket.resolution_confirmed_by.get_full_name() if ticket.resolution_confirmed_by else '—'),
        ('Resolved', ticket.resolved_at.strftime('%Y-%m-%d %H:%M') if ticket.resolved_at else '—'),
        ('Is Asset Request', 'Yes' if ticket.is_asset_request else 'No'),
        ('Is Mobilization Request', 'Yes' if ticket.is_mobilization_request else 'No'),
    ])


def _signoff_context(user, when):
    """Common shape consumed by the PDF templates, DOCX exporters, and
    detail-view templates for a single sign-off line: a signature image
    when the user has uploaded one, else a "captured digitally" text
    fallback with the date/time baked in — so layouts don't need a separate
    Date field alongside it (the date IS the field, when there's no image).
    `date` is still exposed on its own for the signature-image case, where
    nothing else on the line carries a date."""
    if not user:
        return {'user': None, 'signature_url': None, 'captured_text': '', 'name': '', 'date': None}
    name = user.get_full_name() or user.email
    captured_text = f'{name} — captured digitally, on {when.strftime("%Y-%m-%d")} at {when.strftime("%H:%M")}' if when else name
    return {
        'user': user,
        'signature_url': user.signature.url if user.signature else None,
        'captured_text': captured_text,
        'name': name,
        'date': when,
    }


def _location_context(ticket):
    """Best-effort device location captured at Service Request submission.
    Reverse geocoding commonly fails for offshore/at-sea coordinates, so the
    raw coordinates + a map link are kept as a fallback below the address."""
    lat, lon = ticket.submission_latitude, ticket.submission_longitude
    has_coordinates = lat is not None and lon is not None
    address = ticket.submission_location_address or None
    return {
        'address': address,
        'has_coordinates': has_coordinates,
        'latitude': lat,
        'longitude': lon,
        'map_url': f'https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}' if has_coordinates else None,
        'display': address or (f'{lat}, {lon}' if has_coordinates else None),
    }


def service_request_form_sections(ticket):
    """Field mapping for the HDG-IT-FRM-081 facsimile (screen + PDF + Word),
    reusing whatever the system already knows and marking anything not
    captured yet as pending rather than guessing."""
    from .models import TicketActivityLog

    manager_log = (
        TicketActivityLog.objects.filter(
            ticket=ticket,
            action__in=['manager_approved', 'manager_rejected', 'manager_requested_changes'],
        )
        .select_related('actor')
        .order_by('-created_at')
        .first()
    )

    from .service_request_fields import fields_for_group, display_value_for_field

    dynamic_fields = []
    if ticket.service_category:
        for f in fields_for_group(ticket.service_category.field_group):
            value = ticket.service_request_details.get(f.key)
            if value:
                value = display_value_for_field(f, value)
                dynamic_fields.append((f.label, value))

    return {
        'ticket': ticket,
        'requester_name': ticket.requester.get_full_name() or ticket.requester.email,
        'requester_department': ticket.requester.get_department_display(),
        'reported_to': ticket.assigned_to.get_full_name() if ticket.assigned_to else None,
        'requester_confirmed_at': ticket.created_at,
        'it_officer_name': ticket.fulfilled_by.get_full_name() if ticket.fulfilled_by else None,
        'it_officer_at': ticket.fulfilled_at,
        'feedback_comment': ticket.feedback_comment,
        'feedback_rating': ticket.feedback_rating,
        'requester_signoff_name': ticket.resolution_confirmed_by.get_full_name() if ticket.resolution_confirmed_by else None,
        'requester_signoff_at': ticket.resolution_confirmed_at,
        'manager_name': manager_log.actor.get_full_name() if manager_log and manager_log.actor else None,
        'manager_at': manager_log.created_at if manager_log else None,
        'service_category_name': ticket.service_category.name if ticket.service_category else None,
        'purpose': ticket.purpose,
        'vessels': list(ticket.vessels.all()),
        'job_number': ticket.job_number,
        'dive_systems': list(ticket.dive_systems.all()),
        'dynamic_fields': dynamic_fields,
        'requester_signoff': _signoff_context(ticket.requester, ticket.created_at),
        'it_officer_signoff': _signoff_context(ticket.fulfilled_by, ticket.fulfilled_at),
        'requester_feedback_signoff': _signoff_context(ticket.resolution_confirmed_by, ticket.resolution_confirmed_at),
        'it_manager_signoff': _signoff_context(
            manager_log.actor if manager_log else None,
            manager_log.created_at if manager_log else None,
        ),
        'location': _location_context(ticket),
    }


SERVICE_REQUESTS = ReportType(
    slug='service-requests',
    label='Service Requests',
    icon='file-text',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_service_requests_queryset,
    row_from_obj=_service_request_row,
    columns=['Number', 'Title', 'Status', 'Priority', 'Service Category', 'Purpose', 'Vessels', 'Job Number', 'Dive Systems', 'Requester', 'Requester Department', 'Assigned To', 'Created', 'Fulfilled', 'Fulfilled By', 'Receipt Confirmed', 'Receipt Confirmed By', 'Resolved', 'Is Asset Request', 'Is Mobilization Request'],
    date_field_label='Created Date',
    filter_fields=[
        FilterField('status', 'Status', 'select', list(Ticket.Status.choices)),
        FilterField('service_category', 'Service Category', 'select', lambda: [(str(pk), name) for pk, name in ServiceCategory.objects.filter(is_active=True).values_list('id', 'name')]),
    ],
    detail_template='reports/service_request_detail_form.html',
)


# ================================================================
# INCIDENTS
# ================================================================

def _incident_category_label(ticket):
    if not ticket.incident_category:
        return '—'
    if ticket.incident_category == Ticket.IncidentCategory.OTHER and ticket.incident_category_other:
        return ticket.incident_category_other
    return ticket.get_incident_category_display()


def _how_discovered_label(ticket):
    if not ticket.how_discovered:
        return '—'
    if ticket.how_discovered == Ticket.DiscoveryMethod.OTHER and ticket.how_discovered_other:
        return ticket.how_discovered_other
    return ticket.get_how_discovered_display()


def _incidents_queryset(request):
    tickets = Ticket.objects.filter(type=Ticket.Type.INCIDENT).select_related('requester', 'assigned_to', 'category')
    status = request.GET.get('status')
    if status and status in dict(Ticket.Status.choices):
        tickets = tickets.filter(status=status)
    urgency = request.GET.get('urgency')
    if urgency and urgency in dict(Ticket.Urgency.choices):
        tickets = tickets.filter(urgency=urgency)
    incident_category = request.GET.get('incident_category')
    if incident_category and incident_category in dict(Ticket.IncidentCategory.choices):
        tickets = tickets.filter(incident_category=incident_category)
    tickets = tickets.filter(**_date_range_filter(request, 'created_at'))
    return tickets.order_by('-created_at')


def _incident_row(ticket):
    return OrderedDict([
        ('Number', ticket.number),
        ('Title', ticket.title),
        ('Status', ticket.get_status_display()),
        ('Priority', ticket.get_priority_display()),
        ('Urgency', ticket.get_urgency_display()),
        ('Incident Category', _incident_category_label(ticket)),
        ('Business Impact', ticket.get_business_impact_display() if ticket.business_impact else '—'),
        ('How Discovered', _how_discovered_label(ticket)),
        ('Incident Date/Time', ticket.incident_datetime.strftime('%Y-%m-%d %H:%M') if ticket.incident_datetime else '—'),
        ('Location / Hostname', ticket.location_hostname or '—'),
        ('Requester', ticket.requester.get_full_name() or ticket.requester.email),
        ('Requester Department', ticket.requester.get_department_display()),
        ('Assigned To', ticket.assigned_to.get_full_name() if ticket.assigned_to else 'Unassigned'),
        ('Created', ticket.created_at.strftime('%Y-%m-%d %H:%M')),
        ('Resolved', ticket.resolved_at.strftime('%Y-%m-%d %H:%M') if ticket.resolved_at else '—'),
    ])


def incident_form_sections(ticket):
    """Field mapping for the HDG-IT-FRM-086 facsimile (screen + PDF + Word).
    Sections 1-3, 5 (partly), 8-10 are system-derived; Section 5 (Root
    Cause) and the "Steps Taken to Resolve" part of Section 6 are captured
    from the resolving agent at resolve time (see
    Ticket.resolution_root_cause/resolution_steps/
    resolution_root_cause_category, apps.tickets.views.resolve_ticket).
    Section 8 (Communication) is fixed system-derived fact, not a model
    field: every report now originates from this system (IT Helpdesk
    Ticket) and is only ever communicated to the IT Manager. The rest of
    Section 6, Section 4, and 7 are still IT-team-only and were never
    collected digitally, so the templates render those blank."""
    all_attachments = list(ticket.attachments.all())
    image_attachments = [a for a in all_attachments if a.content_type.startswith('image/')]
    non_image_attachments = [a for a in all_attachments if a not in image_attachments]
    return {
        'ticket': ticket,
        'incident_category_display': _incident_category_label(ticket),
        'how_discovered_display': _how_discovered_label(ticket),
        'attachments': non_image_attachments,
        'image_attachments': image_attachments,
        'prepared_by_signoff': _signoff_context(ticket.requester, ticket.created_at),
        'confirmed_resolved_signoff': _signoff_context(ticket.resolution_confirmed_by, ticket.resolution_confirmed_at),
        'it_manager_signoff': _signoff_context(ticket.incident_approved_by, ticket.incident_approved_at),
        'resolution_root_cause': ticket.resolution_root_cause,
        'resolution_steps': ticket.resolution_steps,
        'root_cause_category_values': ticket.resolution_root_cause_category,
        'root_cause_category_display': [
            label for value, label in Ticket.RootCauseCategory.choices
            if value in ticket.resolution_root_cause_category
        ],
    }


INCIDENTS = ReportType(
    slug='incidents',
    label='Incident Reports',
    icon='alert-circle',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_incidents_queryset,
    row_from_obj=_incident_row,
    columns=['Number', 'Title', 'Status', 'Priority', 'Urgency', 'Incident Category', 'Business Impact', 'How Discovered', 'Incident Date/Time', 'Location / Hostname', 'Requester', 'Requester Department', 'Assigned To', 'Created', 'Resolved'],
    date_field_label='Created Date',
    filter_fields=[
        FilterField('status', 'Status', 'select', list(Ticket.Status.choices)),
        FilterField('urgency', 'Urgency', 'select', list(Ticket.Urgency.choices)),
        FilterField('incident_category', 'Category', 'select', list(Ticket.IncidentCategory.choices)),
    ],
    detail_template='reports/incident_detail_form.html',
)


# ================================================================
# AUDIT LOGS
# ================================================================

def _audit_logs_queryset(request):
    # Imported lazily to avoid a circular import (views.py doesn't import
    # this module, but importing it at module load time would still run
    # views.py's full body before it's ready).
    from .views import LOG_CATEGORY_MAP
    from .models import TicketActivityLog
    from django.db.models import Q

    logs = TicketActivityLog.objects.select_related('ticket', 'actor').all()
    if effective_role_name(request.user) == 'TEAM_LEAD':
        # Narrow via the legacy `role` field or the roles M2M (either can lag
        # behind a user's actual active role), then resolve each candidate's
        # true active role in Python so a stale field doesn't drop a real
        # team member from scope.
        candidates = User.objects.filter(
            Q(role='AGENT') | Q(roles__name='AGENT'),
            department=request.user.department,
        ).distinct()
        team_members = [u for u in candidates if effective_role_name(u) == 'AGENT']
        logs = logs.filter(Q(ticket__assigned_to__in=team_members) | Q(ticket__requester__in=team_members))

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
    logs = logs.filter(**_date_range_filter(request, 'created_at'))
    return logs.order_by('-created_at')


def _audit_log_row(log):
    from .views import _log_category
    return OrderedDict([
        ('Time', log.created_at.strftime('%Y-%m-%d %H:%M:%S')),
        ('Category', _log_category(log.action)),
        ('Ticket', log.ticket.number if log.ticket else '—'),
        ('Action', log.action),
        ('Actor', log.actor.get_full_name() if log.actor else 'System'),
        ('Details', str(log.details) if log.details else ''),
    ])


def _audit_log_filter_fields():
    from .views import LOG_CATEGORY_MAP, LOG_CATEGORY_ORDER
    action_choices = [(a, a) for a in sorted(LOG_CATEGORY_MAP.keys())]
    category_choices = [(c, c) for c in LOG_CATEGORY_ORDER[:-1]]
    return [
        FilterField('action', 'Action', 'select', action_choices),
        FilterField('category', 'Category', 'select', category_choices),
        FilterField('ticket', 'Ticket #', 'text', placeholder='e.g. TK#1234'),
    ]


AUDIT_LOGS = ReportType(
    slug='audit-logs',
    label='Audit Logs',
    icon='file-search',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_audit_logs_queryset,
    row_from_obj=_audit_log_row,
    columns=['Time', 'Category', 'Ticket', 'Action', 'Actor', 'Details'],
    date_field_label='Event Date',
    filter_fields=_audit_log_filter_fields(),
)


# ================================================================
# ASSETS
# ================================================================

def _assets_queryset(request):
    from django.db.models import Q
    assets = Asset.objects.all().order_by('tracking_id')

    query = request.GET.get('q', '')
    if query:
        assets = assets.filter(
            Q(name__icontains=query) | Q(tracking_id__icontains=query) |
            Q(serial_number__icontains=query) | Q(model__icontains=query) |
            Q(manufacturer__icontains=query)
        )
    category = request.GET.get('category')
    if category:
        assets = assets.filter(category_id=category)
    status = request.GET.get('status')
    if status:
        assets = assets.filter(status=status)
    location = request.GET.get('location')
    if location:
        assets = assets.filter(location__icontains=location)
    if request.GET.get('filter_renewal_due'):
        assets = assets.filter(
            category__is_renewable=True,
            next_renewal_date__isnull=False,
            next_renewal_date__lte=timezone.now().date() + timedelta(days=30),
        )
    if request.GET.get('filter_low_stock'):
        from django.db.models import F
        assets = assets.filter(
            category__is_consumable=True,
            low_stock_threshold__isnull=False,
            quantity_in_stock__lte=F('low_stock_threshold'),
        )
    assets = assets.filter(**_date_range_filter(request, 'created_at'))
    return assets


def _asset_row(asset):
    return OrderedDict([
        ('Tracking ID', asset.tracking_id),
        ('Name', asset.name),
        ('Category', asset.category.name if asset.category else ''),
        ('Serial Number', asset.serial_number),
        ('Model', asset.model),
        ('Manufacturer', asset.manufacturer),
        ('Location', asset.location),
        ('Status', asset.status),
        ('Quantity In Stock', asset.quantity_in_stock if asset.is_consumable else '—'),
        ('Low Stock Threshold', asset.low_stock_threshold if asset.is_consumable and asset.low_stock_threshold is not None else '—'),
        ('Low Stock', 'Yes' if asset.is_low_stock else 'No'),
        ('Assigned To', asset.assigned_to.get_full_name() if asset.assigned_to else ''),
        ('Assigned Department', asset.assigned_to.get_department_display() if asset.assigned_to else ''),
        ('Purchase Date', asset.purchase_date.strftime('%Y-%m-%d') if asset.purchase_date else ''),
        ('Warranty Expiry', asset.warranty_expiry.strftime('%Y-%m-%d') if asset.warranty_expiry else ''),
        ('Warranty Duration (Years)', asset.warranty_duration_years),
        ('Renewable', 'Yes' if asset.is_renewable else 'No'),
        ('Next Renewal Date', asset.next_renewal_date.strftime('%Y-%m-%d') if asset.next_renewal_date else ''),
        ('Renewal Interval (months)', asset.renewal_interval_months if asset.renewal_interval_months else ''),
        ('Renewal Cost', asset.renewal_cost if asset.renewal_cost is not None else ''),
        ('Renewal Vendor', asset.renewal_vendor.name if asset.renewal_vendor else ''),
        ('Renewal Reference', asset.renewal_reference),
        ('Auto-Renews', 'Yes' if asset.auto_renews else 'No'),
        ('Notes', asset.notes),
        ('Created', asset.created_at.strftime('%Y-%m-%d %H:%M')),
        ('Updated', asset.updated_at.strftime('%Y-%m-%d %H:%M')),
    ])


ASSETS = ReportType(
    slug='assets',
    label='Assets',
    icon='hard-drive',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_assets_queryset,
    row_from_obj=_asset_row,
    columns=['Tracking ID', 'Name', 'Category', 'Serial Number', 'Model', 'Manufacturer', 'Location', 'Status', 'Quantity In Stock', 'Low Stock Threshold', 'Low Stock', 'Assigned To', 'Assigned Department', 'Purchase Date', 'Warranty Expiry', 'Warranty Duration (Years)', 'Renewable', 'Next Renewal Date', 'Renewal Interval (months)', 'Renewal Cost', 'Renewal Vendor', 'Renewal Reference', 'Auto-Renews', 'Notes', 'Created', 'Updated'],
    date_field_label='Added Date',
    filter_fields=[
        FilterField('q', 'Search', 'text', placeholder='Name, tracking ID, serial...'),
        FilterField('category', 'Category', 'select', lambda: [(str(pk), name) for pk, name in AssetCategory.objects.values_list('id', 'name')]),
        FilterField('status', 'Status', 'select', list(Asset.Status.choices)),
        FilterField('filter_renewal_due', 'Renewal Due Soon', 'select', [('1', 'Yes')]),
        FilterField('filter_low_stock', 'Low Stock Only', 'select', [('1', 'Yes')]),
    ],
)


# ================================================================
# USERS
# ================================================================

def _users_queryset(request):
    users = User.objects.all().order_by('first_name', 'last_name')
    role = request.GET.get('role')
    if role and role in dict(User.Role.choices):
        users = users.filter(role=role)
    status = request.GET.get('status')
    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'inactive':
        users = users.filter(is_active=False)
    department = request.GET.get('department')
    if department:
        users = users.filter(department=department)
    users = users.filter(**_date_range_filter(request, 'date_joined'))
    return users


def _user_row(u):
    return OrderedDict([
        ('Full Name', u.get_full_name() or u.email),
        ('Email', u.email),
        ('Department', u.get_department_display()),
        ('Role', u.get_role_display()),
        ('Status', 'Active' if u.is_active else 'Inactive'),
        ('Date Joined', u.date_joined.strftime('%Y-%m-%d %H:%M')),
    ])


USERS = ReportType(
    slug='users',
    label='Users',
    icon='users',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_users_queryset,
    row_from_obj=_user_row,
    columns=['Full Name', 'Email', 'Department', 'Role', 'Status', 'Date Joined'],
    date_field_label='Date Joined',
    filter_fields=[
        FilterField('role', 'Role', 'select', list(User.Role.choices)),
        FilterField('status', 'Status', 'select', [('active', 'Active'), ('inactive', 'Inactive')]),
        FilterField('department', 'Department', 'select', list(User.DEPARTMENT_CHOICES)),
    ],
)


# ================================================================
# MAINTENANCE
# ================================================================

def _maintenance_queryset(request):
    schedules = MaintenanceSchedule.objects.select_related('assigned_to', 'confirmed_by').prefetch_related(
        'additional_assignees', 'target_assets', 'vendors',
        'asset_confirmations__asset', 'asset_confirmations__confirmed_by',
    ).all()
    department = request.GET.get('department')
    if department and department in dict(MaintenanceSchedule.Department.choices):
        schedules = schedules.filter(departments__contains=[department])
    status = request.GET.get('status')
    if status and status in dict(MaintenanceSchedule.Status.choices):
        schedules = schedules.filter(status=status)
    schedules = schedules.filter(**_date_range_filter(request, 'scheduled_date'))
    return schedules.order_by('-scheduled_date')


def _maintenance_row(schedule):
    all_assignees = [schedule.assigned_to] if schedule.assigned_to else []
    all_assignees += list(schedule.additional_assignees.all())
    assignee_names = ', '.join(u.get_full_name() or u.email for u in all_assignees) or 'Unassigned'

    target_bits = [asset.tracking_id for asset in schedule.target_assets.all()]
    if schedule.facility_location:
        target_bits.append(schedule.facility_location)
    vendor_names = [v.name for v in schedule.vendors.all()]
    if vendor_names:
        target_bits.append(f"Vendor(s): {', '.join(vendor_names)}")
    target_display = '; '.join(target_bits) or '—'

    checklist_progress = (
        f'{len(schedule.completed_checklist)}/{len(schedule.checklist_items)}'
        if schedule.checklist_items else '—'
    )

    department_labels = dict(MaintenanceSchedule.Department.choices)
    confirmation_bits = []
    for c in schedule.asset_confirmations.all():
        dept_label = department_labels.get(c.asset.department, c.asset.department or '—')
        confirmation_bits.append(f'{c.asset.tracking_id} ({dept_label}): {c.get_status_display()}')
    confirmation_summary = '; '.join(confirmation_bits) or '—'

    return OrderedDict([
        ('Title', schedule.title),
        ('Target Department(s)', schedule.departments_display),
        ('Status', schedule.get_status_display()),
        ('Scheduled Date', schedule.scheduled_date.strftime('%Y-%m-%d')),
        ('Assigned Personnel', assignee_names),
        ('Target Asset(s)/Facility', target_display),
        ('Checklist Progress', checklist_progress),
        # Per-asset owner confirmation, not the deprecated schedule-level
        # confirmed_by/confirmed_at — kept as one summary column (not split
        # into one row per department) to avoid widening the shared
        # ReportType.row_from_obj contract used by every other report type.
        ('Asset Confirmation Summary', confirmation_summary),
        ('Created', schedule.created_at.strftime('%Y-%m-%d %H:%M')),
    ])


def maintenance_form_sections(schedule):
    """Field mapping for the Maintenance Schedule Report facsimile (screen +
    PDF + Word), mirroring service_request_form_sections()'s shape."""
    started_log = (
        MaintenanceActivityLog.objects.filter(
            schedule=schedule, action=MaintenanceActivityLog.Action.STATUS_CHANGED,
        )
        .order_by('created_at')
        .filter(details__to='IN_PROGRESS')
        .first()
    )

    all_assignees = ([schedule.assigned_to] if schedule.assigned_to else []) + list(
        schedule.additional_assignees.all()
    )
    checklist = [
        (item, item in schedule.completed_checklist) for item in schedule.checklist_items
    ]

    department_labels = dict(MaintenanceSchedule.Department.choices)
    all_confirmations = list(schedule.asset_confirmations.select_related('asset', 'confirmed_by').all())
    department_sections = [
        {
            'department': dept,
            'department_display': department_labels.get(dept, dept),
            'assets': list(schedule.target_assets.filter(department=dept)),
            'confirmations': [c for c in all_confirmations if c.asset.department == dept],
        }
        for dept in (schedule.departments or [])
    ]

    return {
        'schedule': schedule,
        'schedule_code': f'MS-{schedule.pk:05d}',
        'department_display': schedule.departments_display,
        'status_display': schedule.get_status_display(),
        'target_assets': list(schedule.target_assets.all()),
        'vendors': list(schedule.vendors.all()),
        'assignees': all_assignees,
        'checklist': checklist,
        'checklist_progress': schedule.get_progress_percentage(),
        'started_at': started_log.created_at if started_log else None,
        # Deprecated schedule-level sign-off — see MaintenanceSchedule.confirmed_by
        # docstring; retained only for schedules confirmed under the old flow.
        'confirmation_signoff': _signoff_context(schedule.confirmed_by, schedule.confirmed_at),
        'department_sections': department_sections,
        'confirmation_state': schedule.confirmation_state(),
    }


MAINTENANCE = ReportType(
    slug='maintenance',
    label='Maintenance',
    icon='wrench',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_maintenance_queryset,
    row_from_obj=_maintenance_row,
    columns=[
        'Title', 'Target Department(s)', 'Status', 'Scheduled Date', 'Assigned Personnel',
        'Target Asset(s)/Facility', 'Checklist Progress', 'Asset Confirmation Summary', 'Created',
    ],
    date_field_label='Scheduled Date',
    filter_fields=[
        FilterField('department', 'Target Department', 'select', list(MaintenanceSchedule.Department.choices)),
        FilterField('status', 'Status', 'select', list(MaintenanceSchedule.Status.choices)),
    ],
    detail_template='reports/maintenance_detail_form.html',
)


REPORT_TYPES = {
    rt.slug: rt for rt in [SERVICE_REQUESTS, INCIDENTS, AUDIT_LOGS, ASSETS, USERS, MAINTENANCE]
}


def describe_filters(config, request):
    """Human-readable summary of active filters, shown on the PDF export."""
    parts = []
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        parts.append(f'{config.date_field_label}: {start_date} to {end_date}')
    for f in config.filter_fields:
        value = request.GET.get(f.key)
        if not value:
            continue
        display_value = value
        if f.kind == 'select':
            choices = f.choices() if callable(f.choices) else f.choices
            display_value = dict(choices).get(value, value)
        parts.append(f'{f.label}: {display_value}')
    return ' · '.join(parts) if parts else 'No filters applied — all records'
