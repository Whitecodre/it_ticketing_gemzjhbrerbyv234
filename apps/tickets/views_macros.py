# apps/tickets/views_macros.py
"""
Agent-facing macro management page — create/edit/delete the canned replies
surfaced in the ticket conversation composer's macro dropdown (macro_list in
views.py). Shared/team-visible by default (Public/Internal, matching the
dropdown's original behavior), with an optional Private ("only me") option.
"""
from django import forms
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from .models import Macro
from .views import get_sidebar_template
from apps.common.permissions import effective_role_name

# Macros are a personal/team productivity tool for whoever actually
# responds to tickets — not an admin-configured system setting, so
# Admin/Superadmin deliberately aren't included here.
ALLOWED_ROLES = ['TEAM_LEAD', 'AGENT']

FIELD_CLASS = 'block w-full rounded-lg border py-2 px-3 text-sm bg-background border-border text-text-primary'


class MacroForm(forms.ModelForm):
    class Meta:
        model = Macro
        fields = ['title', 'body', 'type', 'visibility']
        widgets = {
            'title': forms.TextInput(attrs={'class': FIELD_CLASS}),
            'body': forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 5}),
            'type': forms.Select(attrs={'class': FIELD_CLASS}),
            'visibility': forms.Select(attrs={'class': FIELD_CLASS}),
        }


def visible_macros_for(user):
    """Macros a user can see/use in the composer dropdown and management
    list: everyone's Public/Internal macros, plus their own Private ones."""
    return Macro.objects.filter(
        Q(visibility__in=[Macro.Visibility.PUBLIC, Macro.Visibility.INTERNAL]) |
        Q(visibility=Macro.Visibility.PRIVATE, created_by=user)
    )


def _can_edit(user, macro):
    return user == macro.created_by or (effective_role_name(user) == 'TEAM_LEAD' and user.department == 'IT')


@login_required
def macro_management(request):
    if effective_role_name(request.user) not in ALLOWED_ROLES or request.user.department != 'IT':
        return HttpResponse(status=403)

    macros = visible_macros_for(request.user).select_related('created_by').order_by('-created_at')
    context = {
        'macros': macros,
        'form': MacroForm(),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'tickets/macro_management.html', context)


@login_required
@require_POST
def macro_create(request):
    if request.user.role not in ALLOWED_ROLES or request.user.department != 'IT':
        return JsonResponse({'error': 'Forbidden'}, status=403)

    form = MacroForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'error': 'Invalid data', 'errors': form.errors}, status=400)

    macro = form.save(commit=False)
    macro.created_by = request.user
    macro.save()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def macro_update(request, pk):
    macro = get_object_or_404(Macro, pk=pk)
    if not _can_edit(request.user, macro):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    form = MacroForm(request.POST, instance=macro)
    if not form.is_valid():
        return JsonResponse({'error': 'Invalid data', 'errors': form.errors}, status=400)
    form.save()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def macro_delete(request, pk):
    macro = get_object_or_404(Macro, pk=pk)
    if not _can_edit(request.user, macro):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    macro.delete()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def macro_bulk_delete(request):
    ids = request.POST.getlist('ids')
    if not ids:
        return JsonResponse({'error': 'No macros selected'}, status=400)

    macros = Macro.objects.filter(pk__in=ids)
    not_allowed = [m for m in macros if not _can_edit(request.user, m)]
    if not_allowed:
        return JsonResponse({'error': 'You can only delete your own macros (or your team\'s, as Team Lead).'}, status=403)

    deleted_count = macros.count()
    macros.delete()
    return JsonResponse({'status': 'ok', 'deleted': deleted_count})
