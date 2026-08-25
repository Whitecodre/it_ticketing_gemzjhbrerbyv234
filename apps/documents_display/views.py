# apps/documents_display/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse, FileResponse
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from django.urls import reverse
from apps.common.decorators import xframe_options_exempt, document_admin_required
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from .utils import get_document_view, set_document_view
from .models import DisplayCategory, DisplayDocument, DisplayVersion, DocumentDepartmentAccess, DocumentShare, generate_share_token, DocumentFolder, FolderShare
from .forms import DisplayDocumentForm, DepartmentAccessFormSet, build_department_access_initial, ShareDocumentForm, DocumentFolderForm, ShareFolderForm
from apps.accounts.models import User
from apps.common.utils import send_email_via_brevo, role_of
from apps.common.models import Notification
from .utils import generate_preview_for_document
from apps.tickets.views import get_sidebar_template

import mimetypes
from django.conf import settings
from datetime import datetime, time
import os

def get_viewable_documents(user):
    """Return queryset of documents viewable by a user."""
    return DisplayDocument.objects.viewable_by(user)

@login_required
def dashboard(request):
    """Main dashboard with categories"""
    
    # ✅ Handle view toggle from request
    new_view = request.GET.get('view')
    if new_view in ['grid', 'list']:
        set_document_view(request, new_view)
        return redirect(request.path)  # Clean URL
    
    view_mode = get_document_view(request)
    
    categories = DisplayCategory.objects.filter(is_active=True).prefetch_related('documents')
    
    # ✅ Use get_viewable_documents to filter
    viewable_docs = get_viewable_documents(request.user)
    
    # Get categories that have at least one viewable document
    categories_with_docs = []
    for cat in categories:
        cat_doc_count = viewable_docs.filter(category=cat).count()
        if cat_doc_count > 0:
            cat.doc_count = cat_doc_count
            categories_with_docs.append(cat)
    
    recent_docs = viewable_docs.order_by('-created_at')[:10]
    
    context = {
        'categories': categories_with_docs,  # Only categories with documents
        'recent_documents': recent_docs,
        'view_mode': view_mode,  # ✅ Add this for the template
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/dashboard.html', context)


@login_required
def category_detail(request, slug):
    """View documents in a category"""
    category = get_object_or_404(DisplayCategory, slug=slug, is_active=True)

    # Handle view toggle from request
    new_view = request.GET.get('view')
    if new_view in ['grid', 'list']:
        set_document_view(request, new_view)
        # Redirect to remove query param (clean URL)
        return redirect(f"{request.path}?q={request.GET.get('q', '')}")
    
    view_mode = get_document_view(request)
    
    # ✅ Use get_viewable_documents to filter
    viewable_docs = get_viewable_documents(request.user)
    documents = viewable_docs.filter(category=category).order_by('title')
    
    # Search by document name (title) only
    query = request.GET.get('q', '')
    if query:
        documents = documents.filter(
            Q(title__icontains=query) |
            Q(file_name__icontains=query)
        )
    
    paginator = Paginator(documents, 20)
    page = request.GET.get('page', 1)
    documents_page = paginator.get_page(page)
    
    context = {
        'category': category,
        'documents': documents_page,
        'query': query,
        'view_mode': view_mode,
        'sidebar_template': get_sidebar_template(request.user),
    }
    if request.headers.get('HX-Request') == 'true':
        return render(request, 'documents_display/partials/category_documents.html', context)
    return render(request, 'documents_display/category_detail.html', context)

@login_required
def document_detail(request, slug):
    """View a single document (read-only)"""
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)

    # ✅ Check if user can view this document
    if not document.is_viewable_by(request.user):
        messages.error(request, 'You do not have permission to view this document.')
        return redirect('documents_display:dashboard')

    versions = document.versions.all()[:5]

    my_folders = []
    if request.user.can_manage_display_documents():
        folders_qs = DocumentFolder.objects.all() if request.user.is_superuser else DocumentFolder.objects.filter(created_by=request.user)
        my_folders = folders_qs.exclude(documents=document)

    context = {
        'document': document,
        'versions': versions,
        'can_edit': document.is_editable_by(request.user),
        'can_download': document.is_downloadable_by(request.user),
        'sidebar_template': get_sidebar_template(request.user),
        'viewer_url': request.build_absolute_uri(document.file.url) if document.file else None,
        'my_folders': my_folders,
    }
    return render(request, 'documents_display/document_detail.html', context)


@login_required
@xframe_options_exempt
def document_viewer(request, slug):
    """View document inline (like WhatsApp)"""
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)

    # ✅ Check if user can view this document
    if not document.is_viewable_by(request.user):
        messages.error(request, 'You do not have permission to view this document.')
        return redirect('documents_display:dashboard')

    # Office files are pre-converted to PDF for inline preview at
    # upload/edit time; if that conversion previously failed (e.g. a
    # transient LibreOffice issue), retry it here so the document can
    # self-heal instead of staying permanently un-previewable. Guard
    # against two concurrent first-viewers both shelling out to
    # LibreOffice at once with a short-lived cache lock.
    if document.is_office_file and not document.preview_pdf:
        lock_key = f"doc-preview-gen-{document.pk}"
        if cache.add(lock_key, 1, timeout=130):
            try:
                generate_preview_for_document(document)
            finally:
                cache.delete(lock_key)

    # Get file URL
    file_url = request.build_absolute_uri(document.file.url)
    file_extension = document.file_extension
    
    context = {
        'document': document,
        'file_url': file_url,
        'file_extension': file_extension,
        'is_viewable_inline': document.is_viewable_inline,
        'is_office_file': document.is_office_file,
        'can_download': document.is_downloadable_by(request.user),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/document_viewer.html', context)


@login_required
@document_admin_required
def document_create(request):
    """Create a new document"""
    if request.method == 'POST':
        form = DisplayDocumentForm(request.POST, request.FILES)
        formset = DepartmentAccessFormSet(request.POST, initial=build_department_access_initial())
        if form.is_valid() and formset.is_valid():
            document = form.save(commit=False)
            document.created_by = request.user
            document.save()
            form.save_m2m()
            DocumentDepartmentAccess.objects.bulk_create([
                DocumentDepartmentAccess(
                    document=document,
                    department=row.cleaned_data['department'],
                    can_edit=row.cleaned_data['can_edit'],
                    can_download=row.cleaned_data['can_download'],
                )
                for row in formset if row.cleaned_data.get('grant')
            ])
            preview_ok = generate_preview_for_document(document)
            if not preview_ok:
                messages.warning(request, 'Preview generation failed for this file (LibreOffice unavailable or conversion error). The document was still saved; check server logs or contact IT.')

            messages.success(request, f'Document "{document.title}" created successfully.')
            return redirect('documents_display:document_detail', slug=document.slug)
    else:
        form = DisplayDocumentForm()
        formset = DepartmentAccessFormSet(initial=build_department_access_initial())

    context = {
        'form': form,
        'formset': formset,
        'department_rows': [
            {'label': label, 'form': row}
            for (code, label), row in zip(User.DEPARTMENT_CHOICES, formset)
        ],
        'action': 'create',
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/document_form.html', context)


@login_required
@document_admin_required
def document_edit(request, slug):
    """Edit a document (rename, replace file)"""
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)

    if not document.is_editable_by(request.user):
        messages.error(request, 'You do not have permission to edit this document.')
        return redirect('documents_display:document_detail', slug=document.slug)

    if request.method == 'POST':
        form = DisplayDocumentForm(request.POST, request.FILES, instance=document)
        formset = DepartmentAccessFormSet(request.POST, initial=build_department_access_initial(document))
        if form.is_valid() and formset.is_valid():
            old_file = document.file
            new_file = request.FILES.get('file')

            updated_doc = form.save(commit=False)

            preview_failed = False
            if new_file:
                # ✅ Update file metadata
                updated_doc.file = new_file
                updated_doc.file_name = new_file.name
                updated_doc.file_size = new_file.size

                # Create version record with old file
                DisplayVersion.objects.create(
                    document=document,
                    version_number=document.version,
                    file=old_file,
                    created_by=request.user,
                    comment=request.POST.get('version_comment', f'Replaced file by {request.user.get_full_name()}')
                )

                updated_doc.version += 1
                updated_doc.save()
                preview_failed = not generate_preview_for_document(updated_doc)
                messages.success(request, f'Document "{document.title}" updated to version {document.version}.')
            else:
                updated_doc.save()
                messages.info(request, 'No changes detected.')

            form.save_m2m()
            document.department_access.all().delete()
            DocumentDepartmentAccess.objects.bulk_create([
                DocumentDepartmentAccess(
                    document=updated_doc,
                    department=row.cleaned_data['department'],
                    can_edit=row.cleaned_data['can_edit'],
                    can_download=row.cleaned_data['can_download'],
                )
                for row in formset if row.cleaned_data.get('grant')
            ])
            if preview_failed:
                messages.warning(request, 'Preview generation failed for this file (LibreOffice unavailable or conversion error). The document was still saved; check server logs or contact IT.')

            return redirect('documents_display:document_detail', slug=document.slug)
    else:
        form = DisplayDocumentForm(instance=document)
        formset = DepartmentAccessFormSet(initial=build_department_access_initial(document))

    context = {
        'form': form,
        'formset': formset,
        'department_rows': [
            {'label': label, 'form': row}
            for (code, label), row in zip(User.DEPARTMENT_CHOICES, formset)
        ],
        'document': document,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/document_form.html', context)


@login_required
@document_admin_required
@require_POST
def document_delete(request, slug):
    """Soft delete a document"""
    document = get_object_or_404(DisplayDocument, slug=slug)
    
    if not document.is_editable_by(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    document.is_deleted = True
    document.deleted_by = request.user
    document.deleted_at = timezone.now()
    document.save()

    # Revoke any still-active shares so their links immediately show a clear
    # "no longer available" message instead of quietly dangling and 404ing.
    document.shares.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())

    messages.success(request, f'Document "{document.title}" has been deleted.')
    return redirect('documents_display:dashboard')


def _permission_denied_response(message='Permission denied'):
    """Small self-contained HTML response for permission failures that can
    render inside a document viewer's <embed>/<iframe> or an HTMX-swapped
    modal — a bare text HttpResponse looks broken in either context."""
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="display:flex;align-items:center;justify-content:center;height:100vh;margin:0;
             font-family:Arial,sans-serif;background:#F8FAFC;color:#64748B;">
    <p style="text-align:center;display:flex;align-items:center;justify-content:center;gap:6px;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> {message}</p>
</body></html>"""
    return HttpResponse(html, status=403)


def _file_download_response(file_field, filename):
    """Shared FileResponse + attachment-disposition construction for
    downloading a document's current file or one of its past versions."""
    response = FileResponse(file_field.open('rb'), content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def document_download(request, slug):
    """Download document file"""
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)

     # ✅ Check if user can download this document
    if not document.is_downloadable_by(request.user):
        messages.error(request, 'You do not have permission to download this document.')
        return redirect('documents_display:dashboard')

    if not document.file:
        messages.error(request, 'This document has no file attachment.')
        return redirect('documents_display:document_detail', slug=document.slug)

    return _file_download_response(document.file, document.file_name)


@login_required
def document_version_download(request, slug, version_id):
    """Download a specific past version of a document's file — routed
    through the same is_downloadable_by() check as the current file,
    instead of linking straight at the raw media URL."""
    version = get_object_or_404(DisplayVersion, pk=version_id, document__slug=slug)
    document = version.document

    if not document.is_downloadable_by(request.user):
        messages.error(request, 'You do not have permission to download this document.')
        return redirect('documents_display:document_detail', slug=slug)

    if not version.file:
        messages.error(request, 'This version has no file attachment.')
        return redirect('documents_display:document_detail', slug=slug)

    # DisplayVersion has no cached file_name field like DisplayDocument does.
    filename = os.path.basename(version.file.name)
    return _file_download_response(version.file, filename)


@login_required
def document_history(request, slug):
    """View version history (HTMX modal)"""
    document = get_object_or_404(DisplayDocument, slug=slug)

    if not document.is_viewable_by(request.user):
        return _permission_denied_response()

    versions = document.versions.all()
    can_download = document.is_downloadable_by(request.user)

    if request.headers.get('HX-Request'):
        return render(request, 'documents_display/partials/version_history.html', {
            'document': document,
            'versions': versions,
            'can_download': can_download,
        })

    # No page in this app links here directly outside the HTMX modal
    # opener on document_detail.html - documents_display/history.html
    # doesn't exist as a standalone page, so fall back to document_detail
    # rather than 500ing on a missing template.
    return redirect('documents_display:document_detail', slug=slug)


@login_required
@xframe_options_exempt
def document_serve_file(request, slug):
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)

    # ✅ Check if user can view this document
    if not document.is_viewable_by(request.user):
        return _permission_denied_response()

    # If preview requested and exists, serve that
    if request.GET.get('preview') == 'true' and document.preview_pdf:
        file_to_serve = document.preview_pdf
    else:
        file_to_serve = document.file

    if not file_to_serve:
        return HttpResponse('File not found', status=404)

    # Open the file via the storage API (not a raw path.open()) so this
    # keeps working under any storage backend, not just local disk.
    try:
        file_handle = file_to_serve.open('rb')
    except FileNotFoundError:
        return HttpResponse('File not found', status=404)

    response = FileResponse(file_handle, content_type='application/octet-stream')
    
    # Set content type
    if file_to_serve.name.endswith('.pdf'):
        response['Content-Type'] = 'application/pdf'
    else:
        mime_type, _ = mimetypes.guess_type(file_to_serve.name)
        if mime_type:
            response['Content-Type'] = mime_type
    
    response['Content-Disposition'] = f'inline; filename="{os.path.basename(file_to_serve.name)}"'
    
    # Remove X-Frame-Options (already handled by decorator)
    if 'X-Frame-Options' in response:
        del response['X-Frame-Options']

    return response


def _share_recipient_label(share):
    """Display label for a share's target, whichever kind it is."""
    return share.display_target


def _send_document_share_email(request, share):
    """Email the recipient (internal user or external address) a link to
    accept an active document share. Internal shares open the login-gated
    document_share_open flow; external ones open the no-login
    document_share_external flow, since the recipient has no account."""
    is_external = share.recipient_id is None
    url_name = 'documents_display:document_share_external' if is_external else 'documents_display:document_share_open'
    accept_url = request.build_absolute_uri(reverse(url_name, args=[share.token]))
    to_email = share.external_email if is_external else share.recipient.email

    html_message = render_to_string('emails/document_shared.html', {
        'recipient_label': _share_recipient_label(share),
        'is_external': is_external,
        'document': share.document,
        'shared_by': share.shared_by,
        'can_edit': share.can_edit,
        'can_download': share.can_download,
        'expires_at': share.expires_at,
        'accept_url': accept_url,
    })
    return send_email_via_brevo(
        to_email=to_email,
        subject=f'{share.document.title} has been shared with you',
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
    )


@login_required
@document_admin_required
def document_share(request, slug):
    """Manage shares for a document: list existing shares, add a new one -
    either an in-system user or an external email address."""
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)

    if request.method == 'POST':
        form = ShareDocumentForm(request.POST)
        if form.is_valid():
            recipient = form.cleaned_data['recipient']
            external_email = form.cleaned_data['external_email']
            expires_at = form.cleaned_data['expires_at']
            # A date-only picker; treat the expiry as valid through the end
            # of that day rather than midnight at its start.
            expires_at_dt = None
            if expires_at:
                expires_at_dt = timezone.make_aware(datetime.combine(expires_at, time.max))

            lookup = {'document': document, 'recipient': recipient} if recipient else {'document': document, 'external_email': external_email}
            share, _created = DocumentShare.objects.update_or_create(
                **lookup,
                defaults={
                    'shared_by': request.user,
                    'can_edit': form.cleaned_data['can_edit'],
                    'can_download': form.cleaned_data['can_download'],
                    'expires_at': expires_at_dt,
                    'revoked_at': None,
                    'token': generate_share_token(),
                    'accepted_at': None,
                },
            )
            success, _result = _send_document_share_email(request, share)
            label = _share_recipient_label(share)
            if recipient:
                Notification.objects.create(
                    sender=request.user,
                    recipient=recipient,
                    role=role_of(recipient),
                    message=f'{request.user.get_full_name()} shared "{document.title}" with you.',
                    url=reverse('documents_display:document_share_open', args=[share.token]),
                    type=Notification.Type.GENERAL,
                )
            if success:
                messages.success(request, f'"{document.title}" shared with {label}.')
            else:
                url_name = 'documents_display:document_share_external' if external_email else 'documents_display:document_share_open'
                manual_link = request.build_absolute_uri(reverse(url_name, args=[share.token]))
                messages.warning(request, f'Share created, but the notification email failed to send. Share the link manually: {manual_link}')
            return redirect('documents_display:document_share', slug=document.slug)
    else:
        form = ShareDocumentForm()

    context = {
        'document': document,
        'form': form,
        'shares': document.shares.select_related('recipient').all(),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/document_share.html', context)


@login_required
@document_admin_required
@require_POST
def document_share_revoke(request, slug, share_id):
    """Revoke a document share."""
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)
    share = get_object_or_404(DocumentShare, pk=share_id, document=document)
    share.revoke()
    messages.success(request, f'Access revoked for {_share_recipient_label(share)}.')
    return redirect('documents_display:document_share', slug=document.slug)


@login_required
def document_share_open(request, token):
    """Landing page for an emailed internal share link. Must be opened while
    logged in as the intended recipient — the token identifies the grant,
    not a login bypass."""
    share = get_object_or_404(DocumentShare, token=token, recipient__isnull=False)

    if share.recipient_id != request.user.id:
        messages.error(request, 'This share link is for a different account. Log in as the intended recipient to access it.')
        return redirect('documents_display:dashboard')

    if share.revoked_at is not None:
        messages.error(request, 'This share link has been revoked.')
        return redirect('documents_display:dashboard')

    if share.is_expired:
        messages.error(request, 'This share link has expired.')
        return redirect('documents_display:dashboard')

    if share.accepted_at is None:
        share.accepted_at = timezone.now()
        share.save(update_fields=['accepted_at'])

    messages.success(request, f'You now have access to "{share.document.title}".')
    return redirect('documents_display:document_detail', slug=share.document.slug)


def _external_share_denied_response(share):
    if share.revoked_at is not None:
        message = 'This link has been revoked and no longer grants access.'
    elif share.is_expired:
        message = 'This link has expired.'
    else:
        message = 'This link is no longer valid.'
    return _permission_denied_response(message)


def document_share_external(request, token):
    """Standalone, no-login landing page for an externally-shared document -
    the token itself is the access, since the recipient has no account.
    Scoped to external_email shares only: an internal share's token must
    not work here, or it would bypass document_share_open's "log in as the
    intended recipient" check."""
    share = get_object_or_404(DocumentShare, token=token, external_email__isnull=False)

    if share.document.is_deleted or not share.is_active:
        return _external_share_denied_response(share)

    if share.accepted_at is None:
        share.accepted_at = timezone.now()
        share.save(update_fields=['accepted_at'])
        if share.shared_by_id:
            Notification.objects.create(
                recipient=share.shared_by,
                role=role_of(share.shared_by),
                message=f'{share.external_email} opened the external link you shared for "{share.document.title}".',
                url=reverse('documents_display:document_share', args=[share.document.slug]),
                type=Notification.Type.GENERAL,
            )

    document = share.document
    context = {
        'document': document,
        'share': share,
        'file_extension': document.file_extension,
        'is_viewable_inline': document.is_viewable_inline,
        'is_office_file': document.is_office_file,
    }
    return render(request, 'documents_display/document_share_external.html', context)


@xframe_options_exempt
def document_share_external_serve(request, token):
    """Inline file serving for the external share viewer - mirrors
    document_serve_file, but keyed on the share token instead of a
    slug + logged-in user's is_viewable_by()."""
    share = get_object_or_404(DocumentShare, token=token, external_email__isnull=False)
    if share.document.is_deleted or not share.is_active:
        return _permission_denied_response()

    document = share.document
    if request.GET.get('preview') == 'true' and document.preview_pdf:
        file_to_serve = document.preview_pdf
    else:
        file_to_serve = document.file

    if not file_to_serve:
        return HttpResponse('File not found', status=404)

    try:
        file_handle = file_to_serve.open('rb')
    except FileNotFoundError:
        return HttpResponse('File not found', status=404)

    response = FileResponse(file_handle, content_type='application/octet-stream')
    if file_to_serve.name.endswith('.pdf'):
        response['Content-Type'] = 'application/pdf'
    else:
        mime_type, _ = mimetypes.guess_type(file_to_serve.name)
        if mime_type:
            response['Content-Type'] = mime_type
    response['Content-Disposition'] = f'inline; filename="{os.path.basename(file_to_serve.name)}"'
    if 'X-Frame-Options' in response:
        del response['X-Frame-Options']
    return response


def document_share_external_download(request, token):
    """Download for an externally-shared document, gated on the share's
    can_download flag rather than an authenticated user's permissions."""
    share = get_object_or_404(DocumentShare, token=token, external_email__isnull=False)
    if share.document.is_deleted or not share.is_active:
        return _permission_denied_response()
    if not share.can_download:
        return _permission_denied_response('This link does not allow downloading.')

    document = share.document
    if not document.file:
        return _permission_denied_response('This document has no file attachment.')

    return _file_download_response(document.file, document.file_name)


@login_required
@document_admin_required
def document_bulk_create(request):
    """Bulk upload: select multiple files at once, apply one shared
    category/visibility/department-access set to all of them, and create
    one DisplayDocument per file (title taken from each filename, editable
    afterward via the normal single-document edit form). Replaces the old
    standalone bulk-permissions screen — per-document department grants are
    already available on the regular create/edit form for the single-file
    case; this is only for applying the same grants across a whole batch at
    upload time."""
    if request.method == 'POST':
        files = request.FILES.getlist('files')
        category_id = request.POST.get('category')
        category_other = request.POST.get('category_other', '').strip()
        document_date = request.POST.get('document_date') or None
        visibility = request.POST.get('visibility', DisplayDocument.Visibility.PUBLIC)
        public_can_edit = request.POST.get('public_can_edit') == 'on'
        public_can_download = request.POST.get('public_can_download') == 'on'
        dept_formset = DepartmentAccessFormSet(request.POST, initial=build_department_access_initial())

        if category_id == 'OTHER' and category_other:
            category, _created = DisplayCategory.objects.get_or_create(name=category_other)
        else:
            category = DisplayCategory.objects.filter(pk=category_id).first() if category_id else None

        if not files:
            messages.error(request, 'Select at least one file to upload.')
        elif category_id == 'OTHER' and not category_other:
            messages.error(request, 'Enter a name for the custom category.')
        elif not category:
            messages.error(request, 'Choose a category for this batch.')
        elif not dept_formset.is_valid():
            messages.error(request, 'Please fix the department access grants below.')
        else:
            grants = [
                {
                    'department': row.cleaned_data['department'],
                    'can_edit': row.cleaned_data['can_edit'],
                    'can_download': row.cleaned_data['can_download'],
                }
                for row in dept_formset if row.cleaned_data.get('grant')
            ]
            created = []
            for f in files:
                title = os.path.splitext(f.name)[0]
                document = DisplayDocument.objects.create(
                    title=title,
                    category=category,
                    file=f,
                    document_date=document_date,
                    visibility=visibility,
                    public_can_edit=public_can_edit,
                    public_can_download=public_can_download,
                    created_by=request.user,
                )
                DocumentDepartmentAccess.objects.bulk_create([
                    DocumentDepartmentAccess(document=document, **grant) for grant in grants
                ])
                generate_preview_for_document(document)
                created.append(document)

            messages.success(request, f'Uploaded {len(created)} document(s) to "{category.name}".')
            return redirect('documents_display:category_detail', slug=category.slug)
    else:
        dept_formset = DepartmentAccessFormSet(initial=build_department_access_initial())

    context = {
        'categories': DisplayCategory.objects.filter(is_active=True).order_by('display_order', 'name'),
        'department_rows': [
            {'label': label, 'form': row}
            for (code, label), row in zip(User.DEPARTMENT_CHOICES, dept_formset)
        ],
        'dept_formset': dept_formset,
        'visibility_choices': DisplayDocument.Visibility.choices,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/document_bulk_create.html', context)


# ==========================================================================
# FOLDERS — admin-curated, private-to-creator collections used to share
# several documents at once instead of one at a time.
# ==========================================================================

def _get_manageable_folder(request, slug):
    """Shared 404 + private-to-creator ownership check used by every
    folder-management view below."""
    folder = get_object_or_404(DocumentFolder, slug=slug)
    if not folder.is_manageable_by(request.user):
        return None
    return folder


@login_required
@document_admin_required
def folder_list(request):
    """The admin's own folders (Superadmin sees every folder, since
    is_manageable_by grants them access to all of them)."""
    if request.user.is_superuser:
        folders = DocumentFolder.objects.all()
    else:
        folders = DocumentFolder.objects.filter(created_by=request.user)
    folders = folders.prefetch_related('documents')

    if request.method == 'POST':
        form = DocumentFolderForm(request.POST)
        if form.is_valid():
            folder = form.save(commit=False)
            folder.created_by = request.user
            folder.save()
            messages.success(request, f'Folder "{folder.name}" created.')
            return redirect('documents_display:folder_detail', slug=folder.slug)
    else:
        form = DocumentFolderForm()

    context = {
        'folders': folders,
        'form': form,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/folder_list.html', context)


@login_required
@document_admin_required
def folder_detail(request, slug):
    """A single folder's documents, plus a picker to add more from
    everything the admin can already view."""
    folder = _get_manageable_folder(request, slug)
    if folder is None:
        messages.error(request, 'You do not have permission to manage this folder.')
        return redirect('documents_display:folder_list')

    folder_document_ids = set(folder.documents.values_list('pk', flat=True))
    query = request.GET.get('q', '')
    available_documents = get_viewable_documents(request.user).exclude(pk__in=folder_document_ids)
    if query:
        available_documents = available_documents.filter(
            Q(title__icontains=query) | Q(file_name__icontains=query)
        )

    context = {
        'folder': folder,
        'documents': folder.documents.select_related('category').order_by('title'),
        'available_documents': available_documents.select_related('category').order_by('title')[:100],
        'query': query,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/folder_detail.html', context)


@login_required
@document_admin_required
@require_POST
def folder_add_documents(request, slug):
    """Add one or more existing documents to a folder (bulk checkbox picker
    on folder_detail, or a single-document 'Add to folder' quick action)."""
    folder = _get_manageable_folder(request, slug)
    if folder is None:
        return HttpResponse(status=403)

    document_ids = request.POST.getlist('document_ids')
    documents = get_viewable_documents(request.user).filter(pk__in=document_ids)
    folder.documents.add(*documents)
    count = documents.count()
    if count:
        messages.success(request, f'Added {count} document(s) to "{folder.name}".')
    else:
        messages.warning(request, 'No documents were added.')
    return redirect('documents_display:folder_detail', slug=folder.slug)


@login_required
@document_admin_required
@require_POST
def folder_remove_document(request, slug, document_id):
    folder = _get_manageable_folder(request, slug)
    if folder is None:
        return HttpResponse(status=403)

    document = get_object_or_404(DisplayDocument, pk=document_id)
    folder.documents.remove(document)
    messages.success(request, f'Removed "{document.title}" from "{folder.name}".')
    return redirect('documents_display:folder_detail', slug=folder.slug)


@login_required
@document_admin_required
@require_POST
def folder_delete(request, slug):
    folder = _get_manageable_folder(request, slug)
    if folder is None:
        return HttpResponse(status=403)

    name = folder.name
    folder.delete()
    messages.success(request, f'Folder "{name}" deleted.')
    return redirect('documents_display:folder_list')


def _send_folder_share_email(request, share):
    """Email the recipient a link to accept an active folder share - mirrors
    _send_document_share_email, listing the folder's documents instead of a
    single document."""
    is_external = share.recipient_id is None
    url_name = 'documents_display:folder_share_external' if is_external else 'documents_display:folder_share_open'
    accept_url = request.build_absolute_uri(reverse(url_name, args=[share.token]))
    to_email = share.external_email if is_external else share.recipient.email

    html_message = render_to_string('emails/folder_shared.html', {
        'recipient_label': share.display_target,
        'is_external': is_external,
        'folder': share.folder,
        'documents': share.folder.documents.all(),
        'shared_by': share.shared_by,
        'can_download': share.can_download,
        'expires_at': share.expires_at,
        'accept_url': accept_url,
    })
    return send_email_via_brevo(
        to_email=to_email,
        subject=f'"{share.folder.name}" has been shared with you',
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
    )


@login_required
@document_admin_required
def folder_share(request, slug):
    """Manage shares for a folder: list existing shares, add a new one -
    either an in-system user or an external email address. Mirrors
    document_share."""
    folder = _get_manageable_folder(request, slug)
    if folder is None:
        messages.error(request, 'You do not have permission to manage this folder.')
        return redirect('documents_display:folder_list')

    if request.method == 'POST':
        form = ShareFolderForm(request.POST)
        if form.is_valid():
            recipient = form.cleaned_data['recipient']
            external_email = form.cleaned_data['external_email']
            expires_at = form.cleaned_data['expires_at']
            expires_at_dt = None
            if expires_at:
                expires_at_dt = timezone.make_aware(datetime.combine(expires_at, time.max))

            lookup = {'folder': folder, 'recipient': recipient} if recipient else {'folder': folder, 'external_email': external_email}
            share, _created = FolderShare.objects.update_or_create(
                **lookup,
                defaults={
                    'shared_by': request.user,
                    'can_download': form.cleaned_data['can_download'],
                    'expires_at': expires_at_dt,
                    'revoked_at': None,
                    'token': generate_share_token(),
                    'accepted_at': None,
                },
            )
            success, _result = _send_folder_share_email(request, share)
            label = share.display_target
            if recipient:
                Notification.objects.create(
                    sender=request.user,
                    recipient=recipient,
                    role=role_of(recipient),
                    message=f'{request.user.get_full_name()} shared the folder "{folder.name}" with you.',
                    url=reverse('documents_display:folder_share_open', args=[share.token]),
                    type=Notification.Type.GENERAL,
                )
            if success:
                messages.success(request, f'"{folder.name}" shared with {label}.')
            else:
                url_name = 'documents_display:folder_share_external' if external_email else 'documents_display:folder_share_open'
                manual_link = request.build_absolute_uri(reverse(url_name, args=[share.token]))
                messages.warning(request, f'Share created, but the notification email failed to send. Share the link manually: {manual_link}')
            return redirect('documents_display:folder_share', slug=folder.slug)
    else:
        form = ShareFolderForm()

    context = {
        'folder': folder,
        'form': form,
        'shares': folder.shares.select_related('recipient').all(),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/folder_share.html', context)


@login_required
@document_admin_required
@require_POST
def folder_share_revoke(request, slug, share_id):
    folder = _get_manageable_folder(request, slug)
    if folder is None:
        return HttpResponse(status=403)

    share = get_object_or_404(FolderShare, pk=share_id, folder=folder)
    share.revoke()
    messages.success(request, f'Access revoked for {share.display_target}.')
    return redirect('documents_display:folder_share', slug=folder.slug)


@login_required
def folder_share_open(request, token):
    """Landing page for an emailed internal folder-share link. Must be
    opened while logged in as the intended recipient."""
    share = get_object_or_404(FolderShare, token=token, recipient__isnull=False)

    if share.recipient_id != request.user.id:
        messages.error(request, 'This share link is for a different account. Log in as the intended recipient to access it.')
        return redirect('documents_display:dashboard')

    if share.revoked_at is not None:
        messages.error(request, 'This share link has been revoked.')
        return redirect('documents_display:dashboard')

    if share.is_expired:
        messages.error(request, 'This share link has expired.')
        return redirect('documents_display:dashboard')

    if share.accepted_at is None:
        share.accepted_at = timezone.now()
        share.save(update_fields=['accepted_at'])

    messages.success(request, f'You now have access to "{share.folder.name}".')
    return redirect('documents_display:folder_shared_view', token=share.token)


@login_required
def folder_shared_view(request, token):
    """Read-only listing of a folder's documents for an internal recipient
    who has accepted the share - links into each document's normal
    document_detail page, which now succeeds because is_viewable_by checks
    active folder shares."""
    share = get_object_or_404(FolderShare, token=token, recipient__isnull=False)
    if share.recipient_id != request.user.id or not share.is_active:
        messages.error(request, 'This share link is no longer valid.')
        return redirect('documents_display:dashboard')

    context = {
        'folder': share.folder,
        'share': share,
        'documents': share.folder.documents.select_related('category').order_by('title'),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'documents_display/folder_shared_view.html', context)


def _external_folder_share_denied_response(share):
    if share.revoked_at is not None:
        message = 'This link has been revoked and no longer grants access.'
    elif share.is_expired:
        message = 'This link has expired.'
    else:
        message = 'This link is no longer valid.'
    return _permission_denied_response(message)


def folder_share_external(request, token):
    """Standalone, no-login landing page for an externally-shared folder -
    lists every document with per-document view/download links scoped to
    this token."""
    share = get_object_or_404(FolderShare, token=token, external_email__isnull=False)

    if not share.is_active:
        return _external_folder_share_denied_response(share)

    if share.accepted_at is None:
        share.accepted_at = timezone.now()
        share.save(update_fields=['accepted_at'])
        if share.shared_by_id:
            Notification.objects.create(
                recipient=share.shared_by,
                role=role_of(share.shared_by),
                message=f'{share.external_email} opened the external link you shared for "{share.folder.name}".',
                url=reverse('documents_display:folder_share', args=[share.folder.slug]),
                type=Notification.Type.GENERAL,
            )

    context = {
        'folder': share.folder,
        'share': share,
        'documents': share.folder.documents.select_related('category').order_by('title'),
    }
    return render(request, 'documents_display/folder_share_external.html', context)


@xframe_options_exempt
def folder_share_external_serve(request, token, document_id):
    """Inline file serving for a document within an externally-shared
    folder - keyed on the share token + document id, verifying the
    document actually belongs to the shared folder."""
    share = get_object_or_404(FolderShare, token=token, external_email__isnull=False)
    if not share.is_active:
        return _permission_denied_response()

    document = share.folder.documents.filter(pk=document_id, is_deleted=False).first()
    if document is None:
        return _permission_denied_response()

    if request.GET.get('preview') == 'true' and document.preview_pdf:
        file_to_serve = document.preview_pdf
    else:
        file_to_serve = document.file

    if not file_to_serve:
        return HttpResponse('File not found', status=404)

    try:
        file_handle = file_to_serve.open('rb')
    except FileNotFoundError:
        return HttpResponse('File not found', status=404)

    response = FileResponse(file_handle, content_type='application/octet-stream')
    if file_to_serve.name.endswith('.pdf'):
        response['Content-Type'] = 'application/pdf'
    else:
        mime_type, _ = mimetypes.guess_type(file_to_serve.name)
        if mime_type:
            response['Content-Type'] = mime_type
    response['Content-Disposition'] = f'inline; filename="{os.path.basename(file_to_serve.name)}"'
    if 'X-Frame-Options' in response:
        del response['X-Frame-Options']
    return response


def folder_share_external_download(request, token, document_id):
    """Download for a document within an externally-shared folder, gated
    on the share's can_download flag."""
    share = get_object_or_404(FolderShare, token=token, external_email__isnull=False)
    if not share.is_active:
        return _permission_denied_response()
    if not share.can_download:
        return _permission_denied_response('This link does not allow downloading.')

    document = share.folder.documents.filter(pk=document_id, is_deleted=False).first()
    if document is None:
        return _permission_denied_response()
    if not document.file:
        return _permission_denied_response('This document has no file attachment.')

    return _file_download_response(document.file, document.file_name)