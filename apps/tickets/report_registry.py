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

from django.db.models import Q
from django.utils import timezone

from .models import (
    Ticket, Asset, ServiceCategory, AssetCategory, AssetLog, Mobilization, MobilizationItem,
    AssetCheckoutHistory, AssetMaintenanceLog,
)
from apps.accounts.models import User
from apps.maintenance.models import MaintenanceSchedule, MaintenanceActivityLog, MaintenanceAssetConfirmation
from apps.common.permissions import effective_role_name


def _date_range_filter(request, field_name, is_date_field=False):
    """Shared start_date/end_date GET-param parsing (matches the pattern
    already used across the app's existing export views). The `__date`
    transform only applies to DateTimeField columns (it extracts the date
    part from a datetime) — a plain DateField like MaintenanceSchedule.
    scheduled_date has no such lookup and errors, so is_date_field=True
    skips straight to __gte/__lte instead."""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if not (start_date and end_date):
        return {}
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        return {}
    if is_date_field:
        return {f'{field_name}__gte': start, f'{field_name}__lte': end}
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
    # Trimmed column set shown in the on-screen preview table (report_builder
    # /report_preview_table.html) so it stays scannable at a glance instead of
    # scrolling through every exportable field — exports still use the full
    # `columns` list above via build_export_response(), untouched by this.
    # Falls back to `columns` when left empty.
    preview_columns: list = field(default_factory=list)
    # One-line plain-English description per column name, shown under each
    # checkbox in the export column-picker modal (components/export_menu.html)
    # so someone new to the system knows what a column like "Is Asset
    # Request" or "Receipt Confirmed" actually means before they export it.
    # Keyed to match `columns` exactly; a column with no entry just renders
    # without a description.
    column_help: dict = field(default_factory=dict)
    filter_fields: list = field(default_factory=list)
    date_field_label: str = 'Date'
    # Optional: overrides the generic key-value detail page with a
    # form-styled one (currently only Incidents/Service Requests have a real
    # paper form to match).
    detail_template: str = None
    # Plain-language grouping + one-liner for the Reports Hub landing page
    # (report_hub view/template) — lets someone browse/search by "what
    # question does this answer" instead of needing to already know a
    # report's technical name.
    category: str = 'General'
    description: str = ''
    # Org-wide document control number (e.g. 'HDG-IT-FRM-091') shown in every
    # export format's header, same numbering convention as the paper forms'
    # _docx_letterhead form_code (HDG-IT-FRM-081/086/090). Blank renders no
    # Control No. row rather than a placeholder.
    control_number: str = ''


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

    # The form's one signature line is literally labeled "IT Manager
    # Signature" (see templates/reports/service_request_form_pdf*.html) —
    # scoped to the IT-stage approval specifically (it_approved/etc, the
    # second of the two review stages), not the department lead's earlier
    # approval. That department-lead stage has no dedicated slot on this
    # physical form; adding one is a separate form-redesign decision.
    manager_log = (
        TicketActivityLog.objects.filter(
            ticket=ticket,
            action__in=['it_approved', 'it_rejected', 'it_requested_changes'],
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
    category='Tickets & Requests',
    description='Every service request submitted, with status, requester, and vessel/dive-system details.',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_service_requests_queryset,
    row_from_obj=_service_request_row,
    columns=['Number', 'Title', 'Status', 'Priority', 'Service Category', 'Purpose', 'Vessels', 'Job Number', 'Dive Systems', 'Requester', 'Requester Department', 'Assigned To', 'Created', 'Fulfilled', 'Fulfilled By', 'Receipt Confirmed', 'Receipt Confirmed By', 'Resolved', 'Is Asset Request', 'Is Mobilization Request'],
    preview_columns=['Number', 'Title', 'Status', 'Priority', 'Requester', 'Assigned To', 'Created'],
    column_help={
        'Number': 'Unique ticket reference number (e.g. SRV#1024)',
        'Title': 'Short summary of what was requested',
        'Status': 'Current workflow status of this request',
        'Priority': 'Urgency level assigned to this request (P1 highest – P4 lowest)',
        'Service Category': 'The type of service being requested (e.g. Access, Hardware)',
        'Purpose': 'The stated reason or justification for the request',
        'Vessels': 'Vessel(s) this request relates to, if applicable',
        'Job Number': 'Linked job/work order number, if applicable',
        'Dive Systems': 'Dive system(s) this request relates to, if applicable',
        'Requester': 'The person who submitted this request',
        'Requester Department': 'The department of the person who submitted this request',
        'Assigned To': 'The IT staff member handling this request',
        'Created': 'Date and time the request was submitted',
        'Fulfilled': 'Date and time the request was marked fulfilled',
        'Fulfilled By': 'The staff member who fulfilled the request',
        'Receipt Confirmed': 'Date and time the requester confirmed receipt',
        'Receipt Confirmed By': 'The person who confirmed receipt of the fulfilled request',
        'Resolved': 'Date and time the request was closed as resolved',
        'Is Asset Request': 'Whether this request involved issuing a physical IT asset',
        'Is Mobilization Request': 'Whether this request is part of a personnel/equipment mobilization',
    },
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
    category='Tickets & Requests',
    description='Every incident ticket, with priority, resolution, and manager sign-off.',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_incidents_queryset,
    row_from_obj=_incident_row,
    columns=['Number', 'Title', 'Status', 'Priority', 'Urgency', 'Incident Category', 'Business Impact', 'How Discovered', 'Incident Date/Time', 'Location / Hostname', 'Requester', 'Requester Department', 'Assigned To', 'Created', 'Resolved'],
    preview_columns=['Number', 'Title', 'Status', 'Priority', 'Urgency', 'Requester', 'Created'],
    column_help={
        'Number': 'Unique ticket reference number (e.g. TK#1024)',
        'Title': 'Short summary of the incident',
        'Status': 'Current workflow status of this incident',
        'Priority': 'Business priority assigned to this incident (P1 highest – P4 lowest)',
        'Urgency': 'How time-sensitive this incident is',
        'Incident Category': 'The type of issue reported (e.g. Hardware, Network, Software)',
        'Business Impact': 'How much this incident disrupted normal business operations',
        'How Discovered': 'How the incident was first identified (e.g. User Report, Monitoring)',
        'Incident Date/Time': 'When the incident actually occurred (may differ from when it was reported)',
        'Location / Hostname': 'Physical location or device hostname affected',
        'Requester': 'The person who reported the incident',
        'Requester Department': 'The department of the person who reported the incident',
        'Assigned To': 'The IT staff member investigating/resolving this incident',
        'Created': 'Date and time the incident was reported',
        'Resolved': 'Date and time the incident was marked resolved',
    },
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
    category='Tickets & Requests',
    description='A timeline of what happened to tickets — status changes, assignments, comments, escalations.',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_audit_logs_queryset,
    row_from_obj=_audit_log_row,
    columns=['Time', 'Category', 'Ticket', 'Action', 'Actor', 'Details'],
    preview_columns=['Time', 'Category', 'Ticket', 'Action', 'Actor'],
    column_help={
        'Time': 'Date and time the logged event occurred',
        'Category': 'The type of action performed (e.g. Ticket Update, Assignment)',
        'Ticket': 'The ticket this log entry relates to, if any',
        'Action': 'The specific system action that was recorded',
        'Actor': 'The user (or System) who performed the action',
        'Details': 'Additional context captured about the action',
    },
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
        assets = assets.filter(location_id=location)
    department = request.GET.get('department')
    if department:
        assets = assets.filter(department_id=department)
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
        ('Location', asset.location.full_name() if asset.location else ''),
        ('Department', asset.department.name if asset.department else ''),
        ('Status', asset.status),
        ('Quantity In Stock', asset.quantity_in_stock if asset.is_consumable else '—'),
        ('Low Stock Threshold', asset.low_stock_threshold if asset.is_consumable and asset.low_stock_threshold is not None else '—'),
        ('Low Stock', 'Yes' if asset.is_low_stock else 'No'),
        ('Assigned To', asset.assigned_to.get_full_name() if asset.assigned_to else ''),
        ('Unresolved Assignee Hint', asset.unresolved_assignee_hint),
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


# Groups Asset.Status into the same 4-color vocabulary the maintenance
# report's confirmation badges use (green/blue/red/gray), so a reader
# scanning both report types learns the color meaning once.
_ASSET_STATUS_BADGE_COLORS = {
    'available': {'bg': '#dcfce7', 'fg': '#166534', 'border': '#166534'},
    'in_use': {'bg': '#dbeafe', 'fg': '#1e40af', 'border': '#1e40af'},
    'attention': {'bg': '#fee2e2', 'fg': '#991b1b', 'border': '#991b1b'},
    'inactive': {'bg': '#f3f4f6', 'fg': '#374151', 'border': '#6b7280'},
}
_ASSET_STATUS_BADGE_GROUP = {
    Asset.Status.IN_STORE: 'available', Asset.Status.READY: 'available',
    Asset.Status.IN_USE: 'in_use', Asset.Status.MOBILIZED: 'in_use',
    Asset.Status.MAINTENANCE: 'attention', Asset.Status.REPAIR: 'attention', Asset.Status.DAMAGED: 'attention',
    Asset.Status.RETIRED: 'inactive', Asset.Status.SCRAPPED: 'inactive',
    Asset.Status.LOST: 'attention', Asset.Status.STOLEN: 'attention', Asset.Status.DISPOSED: 'inactive',
}


def asset_form_sections(asset):
    """Field mapping for the individual Asset Record facsimile (screen + PDF
    + Word), mirroring the shape of the other *_form_sections() functions.

    Recent Activity is deliberately capped at the last 10 AssetLog entries —
    unlike a ticket or maintenance schedule, an asset has no natural single
    "event" to report on; it's an ongoing record that can accumulate years
    of history, so the full audit trail would make the document grow
    unbounded rather than staying a fixed-shape one-page-ish report.

    Section 4 (Notes) is only shown when there's actually a note — numbered
    on the fly, same reasoning as the procurement request form, so Recent
    Activity stays "Section 4" rather than always being "Section 5"."""
    recent_activity = list(asset.logs.select_related('actor').order_by('-created_at')[:10])

    notes_section = None
    next_section = 4
    if asset.notes:
        notes_section = next_section
        next_section += 1
    activity_section = next_section

    status_group = _ASSET_STATUS_BADGE_GROUP.get(asset.status, 'inactive')
    status_badge = {'label': asset.get_status_display(), **_ASSET_STATUS_BADGE_COLORS[status_group]}

    return {
        'asset': asset,
        'recent_activity': recent_activity,
        'notes_section': notes_section,
        'activity_section': activity_section,
        'status_badge': status_badge,
    }


def mobilization_audit_sections(mobilization):
    """Full lifecycle audit trail for a single Mobilization — mobilized →
    receipt acknowledgement/dispute → requester self-report → admin
    demobilize confirmation → resulting inventory effect — backing the
    admin-facing audit report/export linked from the mobilization detail
    page. Unlike asset_form_sections' capped 'Recent Activity' (an asset's
    history is open-ended), this is the complete trail for exactly this
    one mobilization — a naturally fixed-size record."""
    items = list(
        mobilization.items.select_related(
            'asset', 'acknowledged_by', 'return_requested_by', 'demobilized_by'
        ).order_by('asset__name')
    )

    audit_rows = []
    for item in items:
        if not item.demobilized_at:
            inventory_effect = 'Still mobilized — not yet returned to inventory'
        elif item.asset.is_consumable:
            if item.return_condition in (Asset.Condition.DAMAGED, Asset.Condition.UNUSABLE):
                inventory_effect = f'Not restocked ({item.get_return_condition_display()})'
            else:
                returned_qty = item.return_quantity if item.return_quantity is not None else item.quantity
                inventory_effect = f'+{returned_qty} returned to stock'
        elif item.return_condition in (Asset.Condition.DAMAGED, Asset.Condition.UNUSABLE):
            inventory_effect = f'Sent to Maintenance ({item.get_return_condition_display()})'
        else:
            inventory_effect = 'Returned to store (In Store)'

        audit_rows.append({'item': item, 'inventory_effect': inventory_effect})

    return {
        'mobilization': mobilization,
        'vessel_names': list(mobilization.vessels.values_list('name', flat=True)),
        'dive_system_names': list(mobilization.dive_systems.values_list('name', flat=True)),
        'audit_rows': audit_rows,
    }


ASSETS = ReportType(
    slug='assets',
    label='Assets',
    icon='hard-drive',
    category='Assets',
    description='The full asset register — every tracked item, its status, location, and owner.',
    control_number='HDG-IT-FRM-091',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_assets_queryset,
    row_from_obj=_asset_row,
    columns=['Tracking ID', 'Name', 'Category', 'Serial Number', 'Model', 'Manufacturer', 'Location', 'Department', 'Status', 'Quantity In Stock', 'Low Stock Threshold', 'Low Stock', 'Assigned To', 'Unresolved Assignee Hint', 'Assigned Department', 'Purchase Date', 'Warranty Expiry', 'Warranty Duration (Years)', 'Renewable', 'Next Renewal Date', 'Renewal Interval (months)', 'Renewal Cost', 'Renewal Vendor', 'Renewal Reference', 'Auto-Renews', 'Notes', 'Created', 'Updated'],
    preview_columns=['Tracking ID', 'Name', 'Category', 'Status', 'Location', 'Assigned To'],
    column_help={
        'Tracking ID': "The asset's unique system-generated tag/ID",
        'Name': 'The asset\'s descriptive name (e.g. Dell Latitude 5420)',
        'Category': 'The type of asset (e.g. Laptop, Monitor, Printer)',
        'Serial Number': "Manufacturer-assigned serial number",
        'Model': "Manufacturer's model name/number",
        'Manufacturer': 'The company that made the asset',
        'Location': 'Where the asset is physically kept or deployed',
        'Department': 'The department that owns this asset',
        'Status': 'Current lifecycle status (e.g. In Use, In Store, Maintenance)',
        'Quantity In Stock': 'Units currently available (consumable assets only)',
        'Low Stock Threshold': 'Stock level at which this item is flagged as low (consumables only)',
        'Low Stock': 'Whether current stock is at or below the low-stock threshold',
        'Assigned To': 'The person this asset is currently assigned to',
        'Unresolved Assignee Hint': "The 'assigned to' name from an import row that didn't match a real user account — kept so the asset can be claimed once a matching account exists",
        'Assigned Department': 'The department of the person this asset is assigned to',
        'Purchase Date': 'Date the asset was purchased',
        'Warranty Expiry': 'Date the manufacturer warranty ends',
        'Warranty Duration (Years)': 'Length of the warranty period in years',
        'Renewable': 'Whether this asset has a recurring renewal (e.g. license, subscription)',
        'Next Renewal Date': 'Date the next renewal is due',
        'Renewal Interval (months)': 'How often this asset renews, in months',
        'Renewal Cost': 'Cost of each renewal',
        'Renewal Vendor': 'The vendor this asset renews through',
        'Renewal Reference': 'Reference/contract number for the renewal',
        'Auto-Renews': 'Whether the renewal happens automatically',
        'Notes': 'Free-text notes recorded against this asset',
        'Created': 'Date and time this asset was added to the system',
        'Updated': "Date and time this asset's record was last changed",
    },
    date_field_label='Added Date',
    filter_fields=[
        FilterField('q', 'Search', 'text', placeholder='Name, tracking ID, serial...'),
        FilterField('category', 'Category', 'select', lambda: [(str(pk), name) for pk, name in AssetCategory.objects.values_list('id', 'name')]),
        FilterField('status', 'Status', 'select', list(Asset.Status.choices)),
        FilterField('filter_renewal_due', 'Renewal Due Soon', 'select', [('1', 'Yes')]),
        FilterField('filter_low_stock', 'Low Stock Only', 'select', [('1', 'Yes')]),
    ],
    detail_template='reports/asset_detail_form.html',
)


# ================================================================
# ASSETS BY PERSON — reconstructs the client's original "who has what"
# grouped view. Reuses the same flat export machinery as every other
# ReportType (one row per Asset) but ordered/sorted so everything for one
# person, department, and location is contiguous when read top to bottom —
# no new nested-rendering code, works across CSV/Excel/PDF immediately.
# ================================================================

def _assets_by_person_queryset(request):
    return _assets_queryset(request).select_related(
        'department', 'location', 'assigned_to', 'category'
    ).order_by(
        'department__name', 'assigned_to__last_name', 'assigned_to__first_name', 'location__name', 'tracking_id'
    )


def _asset_by_person_row(asset):
    return OrderedDict([
        ('Department', asset.department.name if asset.department else '—'),
        ('Assigned To', asset.assigned_to.get_full_name() if asset.assigned_to else 'Unassigned'),
        ('Unresolved Assignee Hint', asset.unresolved_assignee_hint),
        ('Location', asset.location.full_name() if asset.location else '—'),
        ('Tracking ID', asset.tracking_id),
        ('Name', asset.name),
        ('Category', asset.category.name if asset.category else ''),
        ('Serial Number', asset.serial_number),
        ('Status', asset.status_display['label']),
    ])


ASSETS_BY_PERSON = ReportType(
    slug='assets-by-person',
    label='Assets by Person',
    icon='users',
    category='Assets',
    description="What's currently checked out to each person, grouped by holder.",
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_assets_by_person_queryset,
    row_from_obj=_asset_by_person_row,
    columns=['Department', 'Assigned To', 'Unresolved Assignee Hint', 'Location', 'Tracking ID', 'Name', 'Category', 'Serial Number', 'Status'],
    preview_columns=['Department', 'Assigned To', 'Location', 'Tracking ID', 'Name', 'Status'],
    # Every column here is also an ASSETS column with the same meaning —
    # reuse its descriptions rather than duplicating them.
    column_help={k: v for k, v in ASSETS.column_help.items() if k in (
        'Department', 'Assigned To', 'Unresolved Assignee Hint', 'Location', 'Tracking ID', 'Name', 'Category', 'Serial Number', 'Status'
    )},
    date_field_label='Added Date',
    filter_fields=[
        FilterField('q', 'Search', 'text', placeholder='Name, tracking ID, serial...'),
        FilterField('category', 'Category', 'select', lambda: [(str(pk), name) for pk, name in AssetCategory.objects.values_list('id', 'name')]),
        FilterField('status', 'Status', 'select', list(Asset.Status.choices)),
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
    # Mirror apps.maintenance.views.schedule_detail's own restriction: a Team
    # Lead (already IT-only per _can_access_report) only sees/exports
    # schedules that target their own department, so Reports can't be used
    # to reach schedules the maintenance app itself would block them from.
    if effective_role_name(request.user) == 'TEAM_LEAD':
        schedules = schedules.filter(departments__contains=[request.user.department])
    department = request.GET.get('department')
    if department and department in dict(MaintenanceSchedule.Department.choices):
        schedules = schedules.filter(departments__contains=[department])
    status = request.GET.get('status')
    if status and status in dict(MaintenanceSchedule.Status.choices):
        schedules = schedules.filter(status=status)
    schedules = schedules.filter(**_date_range_filter(request, 'scheduled_date', is_date_field=True))
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

    confirmation_bits = []
    for c in schedule.asset_confirmations.select_related('asset__department').all():
        # Asset.department is its own AssetDepartment model (not a
        # MaintenanceSchedule.Department code) — read its name directly
        # rather than looking it up in department_labels.
        dept_label = c.asset.department.name if c.asset.department_id else '—'
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
    all_confirmations = list(schedule.asset_confirmations.select_related('asset__department', 'confirmed_by').all())

    def _counts(confirmations):
        return {
            'confirmed': sum(1 for c in confirmations if c.status == MaintenanceAssetConfirmation.Status.CONFIRMED),
            'disputed': sum(1 for c in confirmations if c.status == MaintenanceAssetConfirmation.Status.DISPUTED),
            'pending': sum(1 for c in confirmations if c.status == MaintenanceAssetConfirmation.Status.PENDING),
            'total': len(confirmations),
        }

    department_sections = [
        {
            'department': dept,
            'department_display': department_labels.get(dept, dept),
            # Asset.department is its own AssetDepartment model now — match
            # against MaintenanceSchedule's legacy department code through
            # AssetDepartment.legacy_user_department_code.
            'assets': list(schedule.target_assets.filter(department__legacy_user_department_code=dept)),
            'confirmations': (dept_confirmations := [
                c for c in all_confirmations
                if c.asset.department_id and c.asset.department.legacy_user_department_code == dept
            ]),
            'counts': _counts(dept_confirmations),
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
        'confirmation_counts': _counts(all_confirmations),
    }


MAINTENANCE = ReportType(
    slug='maintenance',
    label='Maintenance',
    icon='wrench',
    category='Maintenance',
    description='Scheduled and completed maintenance activities, by department and asset.',
    permission_roles=['ADMIN', 'SUPERADMIN', 'TEAM_LEAD'],
    get_queryset=_maintenance_queryset,
    row_from_obj=_maintenance_row,
    columns=[
        'Title', 'Target Department(s)', 'Status', 'Scheduled Date', 'Assigned Personnel',
        'Target Asset(s)/Facility', 'Checklist Progress', 'Asset Confirmation Summary', 'Created',
    ],
    preview_columns=['Title', 'Target Department(s)', 'Status', 'Scheduled Date', 'Assigned Personnel', 'Checklist Progress'],
    column_help={
        'Title': 'Short name of the maintenance schedule',
        'Target Department(s)': 'Department(s) this maintenance activity applies to',
        'Status': 'Current progress status of the maintenance schedule',
        'Scheduled Date': 'Date the maintenance is/was scheduled for',
        'Assigned Personnel': 'Staff member(s) responsible for carrying out the maintenance',
        'Target Asset(s)/Facility': 'The assets or facility location being maintained',
        'Checklist Progress': 'How many checklist items have been completed',
        'Asset Confirmation Summary': 'Per-asset confirmation status from each department owner',
        'Created': 'Date and time this maintenance schedule was created',
    },
    date_field_label='Scheduled Date',
    filter_fields=[
        FilterField('department', 'Target Department', 'select', list(MaintenanceSchedule.Department.choices)),
        FilterField('status', 'Status', 'select', list(MaintenanceSchedule.Status.choices)),
    ],
    detail_template='reports/maintenance_detail_form.html',
)


# ================================================================
# ASSET ACTIVITY LOGS — AssetLog was already written on every asset
# lifecycle event (assign/unassign/scrap/mobilize/renew/stock-adjust) but
# had no standalone report; only the last 10 rows appeared embedded in the
# Asset detail PDF. This makes the full trail filterable/exportable.
# ================================================================

def _asset_activity_logs_queryset(request):
    logs = AssetLog.objects.select_related('asset', 'actor').all()
    action = request.GET.get('action')
    if action and action in dict(AssetLog.Action.choices):
        logs = logs.filter(action=action)
    asset_q = request.GET.get('asset')
    if asset_q:
        logs = logs.filter(Q(asset__tracking_id__icontains=asset_q) | Q(asset__name__icontains=asset_q))
    logs = logs.filter(**_date_range_filter(request, 'created_at'))
    return logs.order_by('-created_at')


def _asset_activity_log_row(log):
    return OrderedDict([
        ('Time', log.created_at.strftime('%Y-%m-%d %H:%M:%S')),
        ('Asset', f'{log.asset.name} ({log.asset.tracking_id})' if log.asset_id else '—'),
        ('Action', log.get_action_display()),
        ('Actor', log.actor.get_full_name() if log.actor else 'System'),
        ('Details', log.get_details_display()),
    ])


ASSET_ACTIVITY_LOGS = ReportType(
    slug='asset-activity-logs',
    label='Asset Activity Logs',
    icon='file-search',
    category='Assets',
    description='Everything that happened to an asset — assigned, scrapped, mobilized, renewed.',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_asset_activity_logs_queryset,
    row_from_obj=_asset_activity_log_row,
    columns=['Time', 'Asset', 'Action', 'Actor', 'Details'],
    preview_columns=['Time', 'Asset', 'Action', 'Actor'],
    column_help={
        'Time': 'Date and time the action was recorded',
        'Asset': 'The asset this log entry relates to',
        'Action': 'What happened — assigned, scrapped, mobilized, renewed, etc.',
        'Actor': 'The user (or System) who performed the action',
        'Details': 'Additional context captured about the action',
    },
    date_field_label='Event Date',
    filter_fields=[
        FilterField('action', 'Action', 'select', list(AssetLog.Action.choices)),
        FilterField('asset', 'Asset', 'text', placeholder='Name or tracking ID'),
    ],
)


# ================================================================
# ASSET CHECKOUT HISTORY — who has borrowed what, for how long, and
# what's overdue. AssetCheckoutHistory existed but only powered the live
# "pending returns" queue; nothing let an admin export the full trail.
# ================================================================

def _asset_checkout_history_queryset(request):
    history = AssetCheckoutHistory.objects.select_related(
        'asset', 'checked_out_to', 'checked_out_by', 'checked_in_by'
    ).all()
    status = request.GET.get('status')
    today = timezone.now().date()
    if status == 'outstanding':
        history = history.filter(checked_in_at__isnull=True)
    elif status == 'returned':
        history = history.filter(checked_in_at__isnull=False)
    elif status == 'overdue':
        history = history.filter(checked_in_at__isnull=True, expected_return_date__lt=today)
    asset_q = request.GET.get('asset')
    if asset_q:
        history = history.filter(Q(asset__tracking_id__icontains=asset_q) | Q(asset__name__icontains=asset_q))
    history = history.filter(**_date_range_filter(request, 'checked_out_at'))
    return history.order_by('-checked_out_at')


def _asset_checkout_history_row(h):
    if h.checked_in_at:
        status = 'Returned'
    elif h.expected_return_date and h.expected_return_date < timezone.now().date():
        status = 'Overdue'
    else:
        status = 'Outstanding'
    return OrderedDict([
        ('Checked Out At', h.checked_out_at.strftime('%Y-%m-%d %H:%M:%S')),
        ('Asset', f'{h.asset.name} ({h.asset.tracking_id})'),
        ('Checked Out To', h.checked_out_to.get_full_name()),
        ('Checked Out By', h.checked_out_by.get_full_name()),
        ('Expected Return', h.expected_return_date.strftime('%Y-%m-%d') if h.expected_return_date else '—'),
        ('Status', status),
        ('Checked In At', h.checked_in_at.strftime('%Y-%m-%d %H:%M:%S') if h.checked_in_at else '—'),
        ('Checked In By', h.checked_in_by.get_full_name() if h.checked_in_by else '—'),
        ('Return Reason', h.get_return_reason_display() if h.return_reason else '—'),
        ('Return Condition', h.return_condition_rating or h.return_condition or '—'),
        ('Notes', h.notes or ''),
    ])


ASSET_CHECKOUT_HISTORY = ReportType(
    slug='asset-checkout-history',
    label='Asset Checkout History',
    icon='arrow-left-right',
    category='Assets',
    description="Who has borrowed which asset, when it's due back, and what's overdue.",
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_asset_checkout_history_queryset,
    row_from_obj=_asset_checkout_history_row,
    columns=[
        'Checked Out At', 'Asset', 'Checked Out To', 'Checked Out By', 'Expected Return', 'Status',
        'Checked In At', 'Checked In By', 'Return Reason', 'Return Condition', 'Notes',
    ],
    preview_columns=['Checked Out At', 'Asset', 'Checked Out To', 'Expected Return', 'Status'],
    column_help={
        'Checked Out At': 'When the asset was handed over',
        'Asset': 'The asset that was checked out',
        'Checked Out To': 'Who received the asset',
        'Checked Out By': 'Who processed the handover',
        'Expected Return': 'Date the asset was due back, if set',
        'Status': 'Outstanding, Returned, or Overdue (past its expected return date and not yet checked in)',
        'Checked In At': 'When the asset was actually returned',
        'Checked In By': 'Who processed the return',
        'Return Reason': 'Why it was returned (disposal, termination, upgraded, etc.)',
        'Return Condition': 'Condition the asset was in when returned',
        'Notes': 'Free-text notes recorded on the checkout',
    },
    date_field_label='Checked Out Date',
    filter_fields=[
        FilterField('status', 'Status', 'select', [
            ('outstanding', 'Outstanding'), ('returned', 'Returned'), ('overdue', 'Overdue'),
        ]),
        FilterField('asset', 'Asset', 'text', placeholder='Name or tracking ID'),
    ],
)


# ================================================================
# ASSET MAINTENANCE HISTORY — per-asset repair/maintenance events
# (AssetMaintenanceLog), distinct from the facility-level MAINTENANCE
# report above (MaintenanceSchedule). Had no report entry at all before.
# ================================================================

def _asset_maintenance_history_queryset(request):
    logs = AssetMaintenanceLog.objects.select_related('asset', 'performed_by').all()
    maintenance_type = request.GET.get('maintenance_type')
    if maintenance_type and maintenance_type in dict(AssetMaintenanceLog.Type.choices):
        logs = logs.filter(maintenance_type=maintenance_type)
    asset_q = request.GET.get('asset')
    if asset_q:
        logs = logs.filter(Q(asset__tracking_id__icontains=asset_q) | Q(asset__name__icontains=asset_q))
    logs = logs.filter(**_date_range_filter(request, 'performed_at', is_date_field=True))
    return logs.order_by('-performed_at')


def _asset_maintenance_history_row(log):
    return OrderedDict([
        ('Date', log.performed_at.strftime('%Y-%m-%d')),
        ('Asset', f'{log.asset.name} ({log.asset.tracking_id})'),
        ('Type', log.get_maintenance_type_display()),
        ('Title', log.title),
        ('Performed By', log.performed_by.get_full_name()),
        ('Cost', str(log.cost) if log.cost is not None else '—'),
        ('Parts Replaced', log.parts_replaced or '—'),
        ('Next Maintenance Date', log.next_maintenance_date.strftime('%Y-%m-%d') if log.next_maintenance_date else '—'),
        ('Notes', log.notes or ''),
    ])


ASSET_MAINTENANCE_HISTORY = ReportType(
    slug='asset-maintenance-history',
    label='Asset Maintenance History',
    icon='wrench',
    category='Assets',
    description='Repair and service history per asset — cost, parts, technician.',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_asset_maintenance_history_queryset,
    row_from_obj=_asset_maintenance_history_row,
    columns=['Date', 'Asset', 'Type', 'Title', 'Performed By', 'Cost', 'Parts Replaced', 'Next Maintenance Date', 'Notes'],
    preview_columns=['Date', 'Asset', 'Type', 'Title', 'Performed By', 'Cost'],
    column_help={
        'Date': 'Date the maintenance/repair was performed',
        'Asset': 'The asset that was serviced',
        'Type': 'Preventive, Corrective, Emergency, Upgrade, Inspection, etc.',
        'Title': 'Short description of the work',
        'Performed By': 'Who carried out the work',
        'Cost': 'Cost of the work, if recorded',
        'Parts Replaced': 'Parts/components replaced, if any',
        'Next Maintenance Date': 'When this asset is next due for maintenance',
        'Notes': 'Free-text notes on the work performed',
    },
    date_field_label='Performed Date',
    filter_fields=[
        FilterField('maintenance_type', 'Type', 'select', list(AssetMaintenanceLog.Type.choices)),
        FilterField('asset', 'Asset', 'text', placeholder='Name or tracking ID'),
    ],
)


# ================================================================
# DOCUMENT SHARING ACTIVITY — ShareAuditLog exists and is written
# correctly (create/email/open/view/download/revoke/expiry-reminder) but
# was only ever visible via Django admin, unlike every other report
# category. `share` is a GenericFK to DocumentShare or FolderShare, so
# both are handled defensively (a share row can also have been deleted).
# ================================================================

def _document_sharing_logs_queryset(request):
    from apps.documents_display.models import ShareAuditLog
    logs = ShareAuditLog.objects.select_related('actor', 'content_type').all()
    event = request.GET.get('event')
    if event and event in dict(ShareAuditLog.Event.choices):
        logs = logs.filter(event=event)
    logs = logs.filter(**_date_range_filter(request, 'created_at'))
    return logs.order_by('-created_at')


def _document_sharing_log_row(log):
    share = log.share
    if share is None:
        target = '(share deleted)'
    else:
        item = getattr(share, 'document', None) or getattr(share, 'folder', None)
        item_name = getattr(item, 'title', None) or getattr(item, 'name', None) or str(item)
        if getattr(share, 'recipient_id', None):
            recipient = share.recipient.get_full_name()
        else:
            recipient = getattr(share, 'external_email', '') or '—'
        target = f'{item_name} → {recipient}'
    return OrderedDict([
        ('Time', log.created_at.strftime('%Y-%m-%d %H:%M:%S')),
        ('Event', log.get_event_display()),
        ('Shared Item / Recipient', target),
        ('Actor', log.actor.get_full_name() if log.actor else 'External/System'),
        ('Detail', log.detail or ''),
    ])


def _document_sharing_filter_fields():
    from apps.documents_display.models import ShareAuditLog
    return [FilterField('event', 'Event', 'select', list(ShareAuditLog.Event.choices))]


DOCUMENT_SHARING_LOGS = ReportType(
    slug='document-sharing-logs',
    label='Document Sharing Activity',
    icon='share-2',
    category='Documents',
    description='Who shared which document with whom, and whether it was opened or downloaded.',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_document_sharing_logs_queryset,
    row_from_obj=_document_sharing_log_row,
    columns=['Time', 'Event', 'Shared Item / Recipient', 'Actor', 'Detail'],
    preview_columns=['Time', 'Event', 'Shared Item / Recipient', 'Actor'],
    column_help={
        'Time': 'Date and time the event occurred',
        'Event': 'Created, emailed, opened, viewed, downloaded, revoked, or expiry-reminder-sent',
        'Shared Item / Recipient': 'What document/folder was shared and with whom',
        'Actor': 'Who triggered the event, if a logged-in user did (blank for token-based external actions)',
        'Detail': 'Additional free-text context recorded on the event',
    },
    date_field_label='Event Date',
    filter_fields=_document_sharing_filter_fields(),
)


# ================================================================
# IMPERSONATION LOGS — already the most sensitive audit trail in the
# system, but stuck behind an on-screen-only "System" tab of the Logs
# page with no way to export it like every other report category.
# ================================================================

def _impersonation_logs_queryset(request):
    from apps.accounts.models import ImpersonationLog
    logs = ImpersonationLog.objects.select_related('admin', 'target_user').all()
    admin_q = request.GET.get('admin')
    if admin_q:
        logs = logs.filter(
            Q(admin__first_name__icontains=admin_q) | Q(admin__last_name__icontains=admin_q) |
            Q(admin__email__icontains=admin_q)
        )
    logs = logs.filter(**_date_range_filter(request, 'started_at'))
    return logs.order_by('-started_at')


def _impersonation_log_row(log):
    duration = '—'
    if log.ended_at:
        minutes = int((log.ended_at - log.started_at).total_seconds() // 60)
        duration = f'{minutes} min'
    return OrderedDict([
        ('Started At', log.started_at.strftime('%Y-%m-%d %H:%M:%S')),
        ('Admin', log.admin.get_full_name()),
        ('Target User', log.target_user.get_full_name()),
        ('Reason', log.reason),
        ('Ended At', log.ended_at.strftime('%Y-%m-%d %H:%M:%S') if log.ended_at else 'Still active'),
        ('Duration', duration),
    ])


IMPERSONATION_LOGS = ReportType(
    slug='impersonation-logs',
    label='Impersonation Logs',
    icon='user-cog',
    category='People & Access',
    description='Every time an admin logged in as another user, and why.',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_impersonation_logs_queryset,
    row_from_obj=_impersonation_log_row,
    columns=['Started At', 'Admin', 'Target User', 'Reason', 'Ended At', 'Duration'],
    preview_columns=['Started At', 'Admin', 'Target User', 'Reason', 'Ended At'],
    column_help={
        'Started At': 'When the impersonation session began',
        'Admin': 'The admin/superadmin who initiated the impersonation',
        'Target User': 'The account that was impersonated',
        'Reason': 'Reason given for the impersonation',
        'Ended At': 'When the session ended, if it has',
        'Duration': 'Length of the impersonation session',
    },
    date_field_label='Session Date',
    filter_fields=[FilterField('admin', 'Admin', 'text', placeholder='Name or email')],
)


# ================================================================
# NOTIFICATIONS SENT — the Notification model backs both in-app and push
# delivery but had no report; confirming "was user X notified about Y"
# required a raw DB/admin query.
# ================================================================

def _notifications_queryset(request):
    from apps.common.models import Notification
    notes = Notification.objects.select_related('recipient', 'sender').all()
    ntype = request.GET.get('type')
    if ntype and ntype in dict(Notification.Type.choices):
        notes = notes.filter(type=ntype)
    read_status = request.GET.get('read_status')
    if read_status == 'read':
        notes = notes.filter(is_read=True)
    elif read_status == 'unread':
        notes = notes.filter(is_read=False)
    recipient_q = request.GET.get('recipient')
    if recipient_q:
        notes = notes.filter(
            Q(recipient__first_name__icontains=recipient_q) | Q(recipient__last_name__icontains=recipient_q) |
            Q(recipient__email__icontains=recipient_q)
        )
    notes = notes.filter(**_date_range_filter(request, 'created_at'))
    return notes.order_by('-created_at')


def _notification_row(n):
    return OrderedDict([
        ('Time', n.created_at.strftime('%Y-%m-%d %H:%M:%S')),
        ('Recipient', n.recipient.get_full_name()),
        ('Sender', n.sender.get_full_name() if n.sender else 'System'),
        ('Type', n.get_type_display()),
        ('Message', n.message),
        ('Read', 'Yes' if n.is_read else 'No'),
        ('URL', n.url or '—'),
    ])


def _notifications_filter_fields():
    from apps.common.models import Notification
    return [
        FilterField('type', 'Type', 'select', list(Notification.Type.choices)),
        FilterField('read_status', 'Read Status', 'select', [('read', 'Read'), ('unread', 'Unread')]),
        FilterField('recipient', 'Recipient', 'text', placeholder='Name or email'),
    ]


NOTIFICATIONS = ReportType(
    slug='notifications',
    label='Notifications Sent',
    icon='bell',
    category='People & Access',
    description='Every notification sent, to whom, and whether it was read.',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_notifications_queryset,
    row_from_obj=_notification_row,
    columns=['Time', 'Recipient', 'Sender', 'Type', 'Message', 'Read', 'URL'],
    preview_columns=['Time', 'Recipient', 'Type', 'Message', 'Read'],
    column_help={
        'Time': 'When the notification was created',
        'Recipient': 'Who the notification was sent to',
        'Sender': 'Who triggered it, or System for automated notifications',
        'Type': 'General, Ticket, Remote Session, Manager Review, Approval, or Resolution Confirmation',
        'Message': 'The notification text',
        'Read': 'Whether the recipient has opened/read it',
        'URL': 'Where the notification links to, if anywhere',
    },
    date_field_label='Sent Date',
    filter_fields=_notifications_filter_fields(),
)


# ================================================================
# ADMIN ACTION LOG — user-account changes (role/department/active-state/
# password reset) and system-configuration changes (SLA/escalation/business
# calendar, the generic Settings registry, branding) that previously left
# zero trace. See apps.common.models.AdminActionLog / log_admin_action().
# ================================================================

def _admin_action_logs_queryset(request):
    from apps.common.models import AdminActionLog
    logs = AdminActionLog.objects.select_related('actor').all()
    category = request.GET.get('category')
    if category and category in AdminActionLog.Category.values:
        logs = logs.filter(category=category)
    actor_q = request.GET.get('actor')
    if actor_q:
        logs = logs.filter(
            Q(actor__first_name__icontains=actor_q) | Q(actor__last_name__icontains=actor_q) |
            Q(actor__email__icontains=actor_q)
        )
    logs = logs.filter(**_date_range_filter(request, 'created_at'))
    return logs.order_by('-created_at')


def _admin_action_log_row(log):
    return OrderedDict([
        ('Time', log.created_at.strftime('%Y-%m-%d %H:%M:%S')),
        ('Category', log.get_category_display()),
        ('Action', log.action),
        ('Target', log.target_repr),
        ('Actor', log.actor.get_full_name() if log.actor else 'System'),
        ('Details', log.details),
    ])


ADMIN_ACTION_LOGS = ReportType(
    slug='admin-action-logs',
    label='Admin Activity Log',
    icon='shield-alert',
    category='People & Access',
    description='User-account changes and system-configuration changes (SLA, settings, branding) — who changed what, when.',
    permission_roles=['ADMIN', 'SUPERADMIN'],
    get_queryset=_admin_action_logs_queryset,
    row_from_obj=_admin_action_log_row,
    columns=['Time', 'Category', 'Action', 'Target', 'Actor', 'Details'],
    preview_columns=['Time', 'Category', 'Action', 'Target', 'Actor'],
    column_help={
        'Time': 'When the action was performed',
        'Category': 'User Management, SLA & Escalation, or System Settings',
        'Action': 'What was done (e.g. "Deactivated user", "Deleted SLA policy")',
        'Target': 'What was affected',
        'Actor': 'The admin who performed the action',
        'Details': 'Before/after or other context captured about the change',
    },
    date_field_label='Event Date',
    filter_fields=[
        FilterField('category', 'Category', 'select', [
            ('USER_MANAGEMENT', 'User Management'), ('SLA_CONFIG', 'SLA & Escalation'), ('SYSTEM_SETTINGS', 'System Settings'),
        ]),
        FilterField('actor', 'Actor', 'text', placeholder='Name or email'),
    ],
)


# The three asset "history" report types above are facets of one underlying
# question ("what happened with this asset") rather than three separate
# things a user should have to already know to look for by name. The
# Reports Hub (report_hub view) merges them into a single "Asset History"
# card, and report_builder.html shows an in-page tab strip (using this same
# list) to switch between the three underlying reports once you're in one —
# each facet keeps its own columns/filters/export, only the entry point and
# navigation between them are unified.
ASSET_HISTORY_FACETS = [
    ('asset-activity-logs', 'Activity', 'file-search'),
    ('asset-checkout-history', 'Checkouts', 'arrow-left-right'),
    ('asset-maintenance-history', 'Maintenance', 'wrench'),
]


REPORT_TYPES = {
    rt.slug: rt for rt in [
        SERVICE_REQUESTS, INCIDENTS, AUDIT_LOGS, ASSETS, ASSETS_BY_PERSON, MAINTENANCE,
        ASSET_ACTIVITY_LOGS, ASSET_CHECKOUT_HISTORY, ASSET_MAINTENANCE_HISTORY,
        DOCUMENT_SHARING_LOGS, IMPERSONATION_LOGS, NOTIFICATIONS, ADMIN_ACTION_LOGS,
    ]
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
