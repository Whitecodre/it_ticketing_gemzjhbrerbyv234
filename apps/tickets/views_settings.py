# apps/tickets/views_settings.py
"""
System Settings page — generic CRUD over apps.tickets.settings_registry.SETTINGS_RESOURCES,
plus a dedicated branding (ClientSettings) editor. Admin/Superadmin only.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.forms import modelform_factory
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import Ticket
from .settings_registry import SETTINGS_RESOURCES
from .views import get_sidebar_template
from apps.common.permissions import is_admin as _is_admin

WIDGET_KIND_MAP = {
    'textarea': forms.Textarea(attrs={'rows': 3, 'class': 'block w-full rounded-lg border py-2 px-3 text-sm bg-background border-border text-text-primary'}),
    'checkbox': forms.CheckboxInput(attrs={'class': 'rounded border-border text-primary focus:ring-primary'}),
    'number': forms.NumberInput(attrs={'class': 'block w-full rounded-lg border py-2 px-3 text-sm bg-background border-border text-text-primary'}),
    'select': forms.Select(attrs={'class': 'block w-full rounded-lg border py-2 px-3 text-sm bg-background border-border text-text-primary'}),
    'text': forms.TextInput(attrs={'class': 'block w-full rounded-lg border py-2 px-3 text-sm bg-background border-border text-text-primary'}),
    'multiselect': forms.CheckboxSelectMultiple(),
}


def _get_resource_or_404(resource):
    config = SETTINGS_RESOURCES.get(resource)
    if not config:
        raise Http404('Unknown settings resource')
    return config


def _build_form_class(config):
    widgets = {f.name: WIDGET_KIND_MAP.get(f.kind, WIDGET_KIND_MAP['text']) for f in config.fields}
    return modelform_factory(config.model, fields=[f.name for f in config.fields], widgets=widgets)


def _unique_slug(model, base):
    slug = slugify(base) or 'item'
    candidate = slug
    n = 2
    while model.objects.filter(slug=candidate).exists():
        candidate = f'{slug}-{n}'
        n += 1
    return candidate


@login_required
def system_settings(request):
    if not _is_admin(request.user):
        return HttpResponse(status=403)

    from apps.accounts.models import ClientSettings
    client_settings, _ = ClientSettings.objects.get_or_create(id=1)

    resources_ctx = []
    for slug, config in SETTINGS_RESOURCES.items():
        pending = []
        if config.has_proposals:
            pending = list(config.model.objects.filter(is_active=False, proposed_by__isnull=False))
        resources_ctx.append({
            'config': config,
            'rows': config.model.objects.all(),
            'pending': pending,
        })

    context = {
        'resources': resources_ctx,
        'client_settings_obj': client_settings,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'dashboards/system_settings.html', context)


@login_required
@require_POST
def settings_resource_create(request, resource):
    if not _is_admin(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    config = _get_resource_or_404(resource)
    FormClass = _build_form_class(config)
    form = FormClass(request.POST)
    if not form.is_valid():
        return JsonResponse({'error': 'Invalid data', 'errors': form.errors}, status=400)

    instance = form.save(commit=False)
    if hasattr(instance, 'slug') and not instance.slug:
        instance.slug = _unique_slug(config.model, getattr(instance, 'name', 'item'))
    instance.save()
    form.save_m2m()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def settings_resource_update(request, resource, pk):
    if not _is_admin(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    config = _get_resource_or_404(resource)
    obj = get_object_or_404(config.model, pk=pk)
    FormClass = _build_form_class(config)
    form = FormClass(request.POST, instance=obj)
    if not form.is_valid():
        return JsonResponse({'error': 'Invalid data', 'errors': form.errors}, status=400)
    form.save()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def settings_resource_delete(request, resource, pk):
    if not _is_admin(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    config = _get_resource_or_404(resource)
    obj = get_object_or_404(config.model, pk=pk)

    # Guard against deleting a category/vessel/etc. still referenced by
    # existing tickets — SET_NULL on the FK means it wouldn't error, but
    # silently orphaning historical records' categorization is surprising.
    if config.model.__name__ == 'ServiceCategory' and Ticket.objects.filter(service_category=obj).exists():
        return JsonResponse({'error': 'This category is used by existing service requests and cannot be deleted. Deactivate it instead.'}, status=400)
    if config.model.__name__ == 'Vessel' and obj.tickets.exists():
        return JsonResponse({'error': 'This vessel is referenced by existing service requests and cannot be deleted. Deactivate it instead.'}, status=400)
    if config.model.__name__ == 'DiveSystem' and obj.tickets.exists():
        return JsonResponse({'error': 'This dive system is referenced by existing service requests and cannot be deleted. Deactivate it instead.'}, status=400)
    if config.model.__name__ == 'JobNumber' and obj.tickets.exists():
        return JsonResponse({'error': 'This job number is referenced by existing service requests and cannot be deleted. Deactivate it instead.'}, status=400)

    obj.delete()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def settings_resource_activate(request, resource, pk):
    """Approve a row a non-admin proposed inline elsewhere (a new vessel/
    job number/vendor typed on a mobilization/service-request/procurement
    form) — the one-click shortcut for the same thing Edit + checking
    "Active" + Save already does, surfaced from the pending-approval
    banner on this resource's System Settings tab."""
    if not _is_admin(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    config = _get_resource_or_404(resource)
    obj = get_object_or_404(config.model, pk=pk)
    if not hasattr(obj, 'is_active'):
        return JsonResponse({'error': 'This resource has no active state.'}, status=400)

    obj.is_active = True
    obj.save(update_fields=['is_active'])

    proposer = getattr(obj, 'proposed_by', None)
    if proposer:
        from apps.common.models import Notification
        from apps.common.utils import role_of
        label = getattr(obj, 'name', None) or getattr(obj, 'number', None) or str(obj)
        Notification.objects.create(
            recipient=proposer,
            role=role_of(proposer),
            message=f'"{label}" ({config.singular_label}) you proposed has been approved and is now active.',
            url='/tickets/settings/',
        )

    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def branding_update(request):
    if not _is_admin(request.user):
        return HttpResponse(status=403)

    from apps.accounts.models import ClientSettings
    client_settings, _ = ClientSettings.objects.get_or_create(id=1)

    company_name = request.POST.get('company_name', '').strip()
    if company_name:
        client_settings.company_name = company_name

    currency_symbol = request.POST.get('currency_symbol', '').strip()
    if currency_symbol:
        client_settings.currency_symbol = currency_symbol

    if 'logo' in request.FILES:
        logo = request.FILES['logo']
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        if logo.content_type not in allowed_types:
            messages.error(request, 'Please upload a valid image (JPEG, PNG, GIF, or WEBP).')
            return redirect('tickets:system_settings')
        if logo.size > 2 * 1024 * 1024:
            messages.error(request, 'Logo must be less than 2MB.')
            return redirect('tickets:system_settings')
        if client_settings.logo:
            try:
                client_settings.logo.delete(save=False)
            except Exception:
                pass
        client_settings.logo = logo

    client_settings.updated_by = request.user
    client_settings.save()
    messages.success(request, 'Branding updated successfully.')
    return redirect('tickets:system_settings')
