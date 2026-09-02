# apps/tickets/views_drafts.py
"""
Auto-save/manual-save draft endpoints for the Incident/Service Request forms.
One draft per (user, ticket_type) — see TicketDraft in models.py. Actual
submission (create_ticket) discards the draft server-side on success, since
that's a normal full-page POST-redirect with no client-side "after submit"
hook to rely on.

Attachments are handled separately from the JSON form-field autosave below
(save_draft_attachment/discard_draft_attachment) since a file has to be
uploaded and stored server-side the moment it's picked — a browser can never
re-populate a file input on restore, so waiting for the debounced text-field
autosave would mean a picked-then-abandoned-tab file is simply gone.
"""
import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST

from .models import TicketDraft, TicketDraftAttachment
from .views import MAX_SIZE_MB, ALLOWED_MIMES, sniffed_mime_matches

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

    draft = TicketDraft.objects.filter(user=request.user, ticket_type=ticket_type).prefetch_related('draft_attachments').first()
    if not draft:
        return HttpResponse(status=204)

    return JsonResponse({
        'form_data': draft.form_data,
        'updated_at': draft.updated_at.isoformat(),
        'attachments': [
            {'id': att.pk, 'filename': att.filename, 'size': att.size}
            for att in draft.draft_attachments.all()
        ],
    })


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

    draft = TicketDraft.objects.filter(user=request.user, ticket_type=ticket_type).first()
    if draft:
        for att in draft.draft_attachments.all():
            if att.file:
                att.file.delete(save=False)
        draft.delete()
    return JsonResponse({'status': 'ok'})


@login_required
@require_POST
def save_draft_attachment(request):
    """Uploads one or more files onto the current draft immediately — called
    on the attachment picker's change event, not the debounced text-field
    autosave. Reuses the same size/MIME validation as real ticket
    submission (save_attachments in views.py) so nothing gets stored here
    that would be rejected at actual submit time anyway."""
    ticket_type = request.POST.get('ticket_type')
    if ticket_type not in VALID_TYPES:
        return JsonResponse({'error': 'Invalid ticket_type'}, status=400)

    files = request.FILES.getlist('attachments')
    if not files:
        return JsonResponse({'error': 'No files provided'}, status=400)

    draft, _ = TicketDraft.objects.get_or_create(user=request.user, ticket_type=ticket_type)

    created = []
    rejected = []
    for f in files:
        if f.size > MAX_SIZE_MB * 1024 * 1024:
            rejected.append({'name': f.name, 'reason': f'exceeds the {MAX_SIZE_MB}MB limit'})
            continue
        mime = f.content_type.split(';')[0].strip().lower()
        if mime not in ALLOWED_MIMES or not sniffed_mime_matches(f, mime):
            rejected.append({'name': f.name, 'reason': 'file type not allowed'})
            continue
        att = TicketDraftAttachment.objects.create(
            draft=draft, file=f, filename=f.name, content_type=mime, size=f.size,
        )
        created.append({'id': att.pk, 'filename': att.filename, 'size': att.size})

    return JsonResponse({'created': created, 'rejected': rejected})


@login_required
@require_POST
def discard_draft_attachment(request):
    """Removes one draft attachment — used when the user removes a restored
    "from draft" chip before submitting. Scoped to the requesting user's own
    draft so an id can't be poked to delete someone else's file."""
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        payload = {}

    attachment_id = payload.get('attachment_id')
    qs = TicketDraftAttachment.objects.filter(pk=attachment_id, draft__user=request.user)
    att = qs.first()
    if not att:
        return JsonResponse({'error': 'Not found'}, status=404)

    if att.file:
        att.file.delete(save=False)
    att.delete()
    return JsonResponse({'status': 'ok'})
