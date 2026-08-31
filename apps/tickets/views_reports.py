# apps/tickets/views_reports.py
"""
Views for the enterprise Exportables feature — one shared "report builder"
page + one shared export endpoint, both generic over report_registry.REPORT_TYPES.
Kept out of views.py (already very large) since this is a self-contained feature.
"""
from collections import OrderedDict
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, Http404
from django.shortcuts import render

from .report_registry import (
    REPORT_TYPES, ASSET_HISTORY_FACETS, describe_filters, incident_form_sections,
    service_request_form_sections, maintenance_form_sections, asset_form_sections,
)
from .report_exporters import (
    build_export_response, export_incident_pdf, export_incident_docx,
    export_service_request_pdf, export_service_request_docx,
    export_maintenance_pdf, export_maintenance_docx,
    export_asset_pdf, export_asset_docx,
)
from .views import get_sidebar_template
from apps.common.permissions import effective_role_name


def _get_config_or_404(report_type):
    config = REPORT_TYPES.get(report_type)
    if not config:
        raise Http404('Unknown report type')
    return config


def _can_access_report(user, config):
    """`config.permission_roles` is a flat role list with no department
    concept — but a Team Lead outside IT is scoped solely to the
    service-request approval flow for now, so reports (which are otherwise
    IT-operational) stay off-limits to them regardless of role name."""
    role_name = effective_role_name(user)
    if role_name not in config.permission_roles:
        return False
    if role_name == 'TEAM_LEAD':
        return user.department == 'IT'
    return True


def _filter_fields_context(config, request):
    """Resolve each filter field's current value from the querystring so the
    template can render selected options / input values without needing a
    dict-lookup-by-variable template filter."""
    fields = []
    for f in config.filter_fields:
        choices = f.choices() if callable(f.choices) else f.choices
        fields.append({
            'key': f.key,
            'label': f.label,
            'kind': f.kind,
            'choices': choices,
            'placeholder': f.placeholder,
            'value': request.GET.get(f.key, ''),
        })
    return fields


# Display order for the Reports Hub's category sections — anything with a
# category not listed here (shouldn't happen; every ReportType sets one)
# would simply be appended at the end via the dict.setdefault below.
REPORT_HUB_CATEGORY_ORDER = ['Tickets & Requests', 'Assets', 'Maintenance', 'Documents', 'People & Access']


@login_required
def report_hub(request):
    """Landing page for the Exportables feature — a searchable, categorized
    card grid. Replaces the old pattern of one sidebar link per report
    type, which had grown to a dozen near-identical entries a non-technical
    user had to already know by name to find anything. Search itself is
    client-side (static/js/report_hub.js) — there are only a couple dozen
    report types at most, not worth a server round-trip to filter them."""
    accessible = [config for config in REPORT_TYPES.values() if _can_access_report(request.user, config)]

    # The three asset-history facets are one card here, not three — see
    # ASSET_HISTORY_FACETS docstring. Whichever facet the user has access to
    # first (in that list's order) becomes the card's link; report_builder
    # itself shows the tab strip to reach the other two once inside.
    facet_slugs = [slug for slug, _, _ in ASSET_HISTORY_FACETS]
    history_configs = [c for c in accessible if c.slug in facet_slugs]
    if history_configs:
        accessible = [c for c in accessible if c.slug not in facet_slugs]
        available_slugs = {c.slug for c in history_configs}
        default_slug = next(s for s in facet_slugs if s in available_slugs)
        accessible.append(SimpleNamespace(
            slug=default_slug,
            label='Asset History',
            icon='history',
            category='Assets',
            description='Everything that happened to an asset — activity, checkouts, and maintenance, in one place.',
        ))

    grouped = OrderedDict((category, []) for category in REPORT_HUB_CATEGORY_ORDER)
    for config in accessible:
        grouped.setdefault(config.category, []).append(config)
    grouped = OrderedDict(
        (category, sorted(configs, key=lambda c: c.label))
        for category, configs in grouped.items() if configs
    )

    context = {
        'grouped_reports': grouped,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'dashboards/report_hub.html', context)


@login_required
def report_builder(request, report_type):
    config = _get_config_or_404(report_type)
    if not _can_access_report(request.user, config):
        return HttpResponse(status=403)

    queryset = config.get_queryset(request)
    # Universal sort toggle for every report type with zero per-type config:
    # get_queryset() always returns an already-ordered queryset, so flipping
    # it is exactly "oldest first" regardless of what that ordering is.
    active_sort = request.GET.get('sort', 'newest')
    if active_sort not in ('newest', 'oldest'):
        active_sort = 'newest'
    if active_sort == 'oldest':
        queryset = queryset.reverse()
    sort_options = [('newest', 'Newest First'), ('oldest', 'Oldest First')]
    paginator = Paginator(queryset, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    rows = []
    for obj in page_obj:
        row = config.row_from_obj(obj)
        row['_pk'] = obj.pk
        rows.append(row)

    base_get = request.GET.copy()
    base_get.pop('page', None)

    context = {
        'config': config,
        'report_type': report_type,
        'page_obj': page_obj,
        'rows': rows,
        'columns': config.preview_columns or config.columns,
        'filter_fields': _filter_fields_context(config, request),
        'start_date': request.GET.get('start_date', ''),
        'end_date': request.GET.get('end_date', ''),
        'total_count': paginator.count,
        'querystring': request.GET.urlencode(),
        'base_qs': base_get.urlencode(),
        'sidebar_template': get_sidebar_template(request.user),
        'asset_history_facets': ASSET_HISTORY_FACETS if any(report_type == s for s, _, _ in ASSET_HISTORY_FACETS) else None,
        'sort_options': sort_options,
        'active_sort': active_sort,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/report_preview_table.html', context)
    return render(request, 'dashboards/report_builder.html', context)


@login_required
def export_report(request, report_type):
    config = _get_config_or_404(report_type)
    if not _can_access_report(request.user, config):
        return HttpResponse(status=403)

    export_format = request.GET.get('format', 'csv')
    if report_type == 'assets' and export_format == 'csv':
        return HttpResponse('CSV export is not available for Assets.', status=400)
    filter_summary = describe_filters(config, request)
    return build_export_response(config, request, export_format, filter_summary=filter_summary)


def _get_record_or_404(config, request, pk):
    obj = config.get_queryset(request).filter(pk=pk).first()
    if not obj:
        raise Http404('Record not found')
    return obj


@login_required
def report_record_detail(request, report_type, pk):
    config = _get_config_or_404(report_type)
    if not _can_access_report(request.user, config):
        return HttpResponse(status=403)

    obj = _get_record_or_404(config, request, pk)

    if config.slug == 'incidents':
        context = incident_form_sections(obj)
    elif config.slug == 'service-requests':
        context = service_request_form_sections(obj)
    elif config.slug == 'maintenance':
        context = maintenance_form_sections(obj)
    elif config.slug == 'assets':
        context = asset_form_sections(obj)
    else:
        context = {'obj': obj, 'row': config.row_from_obj(obj)}

    context.update({
        'config': config,
        'report_type': report_type,
        'sidebar_template': get_sidebar_template(request.user),
    })

    # Report types with no bespoke "paper form" detail template (Audit Logs,
    # Asset Activity Logs, Impersonation Logs, etc. — just a flat key-value
    # grid) open as a modal over the report list instead of navigating to a
    # whole new page for a handful of fields. The five form-styled types
    # (detail_template set) keep full-page navigation — they're genuinely
    # richer documents. A direct/bookmarked GET (no HX-Request) still falls
    # back to the full generic page so the URL stays shareable.
    if not config.detail_template and request.headers.get('HX-Request'):
        return render(request, 'partials/report_record_modal.html', context)

    template = config.detail_template or 'reports/record_detail_generic.html'
    return render(request, template, context)


@login_required
def export_report_record(request, report_type, pk):
    config = _get_config_or_404(report_type)
    if not _can_access_report(request.user, config):
        return HttpResponse(status=403)

    obj = _get_record_or_404(config, request, pk)
    export_format = request.GET.get('format', 'pdf')

    if config.slug == 'incidents':
        if export_format == 'docx':
            return export_incident_docx(obj)
        return export_incident_pdf(obj, request)

    if config.slug == 'service-requests':
        if export_format == 'docx':
            return export_service_request_docx(obj)
        return export_service_request_pdf(obj, request)

    if config.slug == 'maintenance':
        if export_format == 'docx':
            return export_maintenance_docx(obj)
        return export_maintenance_pdf(obj, request)

    if config.slug == 'assets':
        if export_format == 'docx':
            return export_asset_docx(obj)
        return export_asset_pdf(obj, request)

    rows = [config.row_from_obj(obj)]
    from .report_exporters import EXPORTERS
    exporter = EXPORTERS.get(export_format)
    if not exporter:
        return HttpResponse('Invalid format', status=400)
    return exporter(rows, config.columns, config.label, f'{config.slug}_{pk}', request=request)
