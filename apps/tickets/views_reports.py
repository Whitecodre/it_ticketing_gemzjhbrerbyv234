# apps/tickets/views_reports.py
"""
Views for the enterprise Exportables feature — one shared "report builder"
page + one shared export endpoint, both generic over report_registry.REPORT_TYPES.
Kept out of views.py (already very large) since this is a self-contained feature.
"""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, Http404
from django.shortcuts import render

from .report_registry import (
    REPORT_TYPES, describe_filters, incident_form_sections, service_request_form_sections,
    maintenance_form_sections,
)
from .report_exporters import (
    build_export_response, export_incident_pdf, export_incident_docx,
    export_service_request_pdf, export_service_request_docx,
    export_maintenance_pdf, export_maintenance_docx,
)
from .views import get_sidebar_template


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
    if user.role not in config.permission_roles:
        return False
    if user.role == 'TEAM_LEAD':
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


@login_required
def report_builder(request, report_type):
    config = _get_config_or_404(report_type)
    if not _can_access_report(request.user, config):
        return HttpResponse(status=403)

    queryset = config.get_queryset(request)
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
        'columns': config.columns,
        'filter_fields': _filter_fields_context(config, request),
        'start_date': request.GET.get('start_date', ''),
        'end_date': request.GET.get('end_date', ''),
        'total_count': paginator.count,
        'querystring': request.GET.urlencode(),
        'base_qs': base_get.urlencode(),
        'sidebar_template': get_sidebar_template(request.user),
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
    else:
        context = {'obj': obj, 'row': config.row_from_obj(obj)}

    context.update({
        'config': config,
        'report_type': report_type,
        'sidebar_template': get_sidebar_template(request.user),
    })
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

    rows = [config.row_from_obj(obj)]
    from .report_exporters import EXPORTERS
    exporter = EXPORTERS.get(export_format)
    if not exporter:
        return HttpResponse('Invalid format', status=400)
    return exporter(rows, config.columns, config.label, f'{config.slug}_{pk}', request=request)
