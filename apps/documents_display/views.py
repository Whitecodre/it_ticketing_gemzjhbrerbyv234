# apps/documents_display/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse, FileResponse
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from apps.common.decorators import xframe_options_exempt, document_admin_required
from django.views.decorators.http import require_POST
from .utils import get_document_view, set_document_view
from .models import DisplayCategory, DisplayDocument, DisplayVersion, DocumentDepartmentAccess
from .forms import DisplayDocumentForm, DepartmentAccessFormSet, build_department_access_initial
from apps.accounts.models import User
from .utils import generate_preview_for_document
from apps.tickets.views import get_sidebar_template

import mimetypes
from django.conf import settings
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

    context = {
        'document': document,
        'versions': versions,
        'can_edit': document.is_editable_by(request.user),
        'can_download': document.is_downloadable_by(request.user),
        'sidebar_template': get_sidebar_template(request.user),
        'viewer_url': request.build_absolute_uri(document.file.url) if document.file else None,
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
    
    messages.success(request, f'Document "{document.title}" has been deleted.')
    return redirect('documents_display:dashboard')


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
    
    response = FileResponse(document.file.open('rb'), content_type='application/octet-stream')
    response['Content-Disposition'] = f'attachment; filename="{document.file_name}"'
    return response


@login_required
def document_history(request, slug):
    """View version history (HTMX modal)"""
    document = get_object_or_404(DisplayDocument, slug=slug)

    if not document.is_viewable_by(request.user):
        return HttpResponse('Permission denied', status=403)

    versions = document.versions.all()
    can_download = document.is_downloadable_by(request.user)

    if request.headers.get('HX-Request'):
        return render(request, 'documents_display/partials/version_history.html', {
            'document': document,
            'versions': versions,
            'can_download': can_download,
        })

    return render(request, 'documents_display/history.html', {
        'document': document,
        'versions': versions,
        'can_download': can_download,
        'sidebar_template': get_sidebar_template(request.user),
    })


@login_required
@xframe_options_exempt
def document_serve_file(request, slug):
    document = get_object_or_404(DisplayDocument, slug=slug, is_deleted=False)

    # ✅ Check if user can view this document
    if not document.is_viewable_by(request.user):
        return HttpResponse('Permission denied', status=403)
    
    # If preview requested and exists, serve that
    if request.GET.get('preview') == 'true' and document.preview_pdf:
        file_to_serve = document.preview_pdf
    else:
        file_to_serve = document.file
    
    if not file_to_serve:
        return HttpResponse('File not found', status=404)
    
    # Open the file
    try:
        file_handle = open(file_to_serve.path, 'rb')
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