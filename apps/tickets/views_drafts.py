# apps/tickets/views_drafts.py
"""
Auto-save/manual-save draft endpoints for the Incident/Service Request forms.
One draft per (user, ticket_type) — see TicketDraft in models.py. Actual
submission (create_ticket) discards the draft server-side on success, since
that's a normal full-page POST-redirect with no client-side "after submit"
hook to rely on.
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .models import TicketDraft

VALID_TYPES = ('INCIDENT', 'SERVICE_REQUEST')


@login_required
@require_POST
def save_draft(request):
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid payload'}, status=400)

    ticket_type = payload.get('ticket_type')
    if ticket_type not in VALID_TYPES:
        return JsonResponse({'error': 'Invalid ticket_type'}, status=400)

    form_data = payload.get('form_data')
    if not isinstance(form_data, dict):
        return JsonResponse({'error': 'form_data must be an object'}, status=400)

    TicketDraft.objects.update_or_create(
        user=request.user, ticket_type=ticket_type,
        defaults={'form_data': form_data},
    )
    return JsonResponse({'status': 'ok'})


@login_required
def get_draft(request):
    ticket_type = request.GET.get('type')
    if ticket_type not in VALID_TYPES:
        return HttpResponse(status=400)

    draft = TicketDraft.objects.filter(user=request.user, ticket_type=ticket_type).first()
    if not draft:
        return HttpResponse(status=204)

    return JsonResponse({'form_data': draft.form_data, 'updated_at': draft.updated_at.isoformat()})


@login_required
@require_POST
def discard_draft(request):
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        payload = {}

    ticket_type = payload.get('ticket_type')
    if ticket_type not in VALID_TYPES:
        return JsonResponse({'error': 'Invalid ticket_type'}, status=400)

    TicketDraft.objects.filter(user=request.user, ticket_type=ticket_type).delete()
    return JsonResponse({'status': 'ok'})
