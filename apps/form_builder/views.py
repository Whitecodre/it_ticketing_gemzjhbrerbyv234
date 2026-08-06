# apps/form_builder/views.py - Updated

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from django.urls import reverse
import json

from .models import FormDefinition, FormSubmission, FormTemplate
from .templates_data import TEMPLATES


def get_sidebar_template(user):
    """Returns the correct sidebar partial based on user's active role."""
    mapping = {
        'END_USER': 'partials/sidebar_end_user.html',
        'AGENT': 'partials/sidebar_agent.html',
        'TEAM_LEAD': 'partials/sidebar_team_lead.html',
        'ADMIN': 'partials/sidebar_admin.html',
        'SUPERADMIN': 'partials/sidebar_superadmin.html',
    }
    active_role = user.get_active_role()
    role_name = active_role.name if active_role else user.role
    return mapping.get(role_name, 'partials/sidebar_end_user.html')


def is_admin(user):
    return user.role in ['ADMIN', 'SUPERADMIN']


# apps/form_builder/views.py - Update form_list

@login_required
@user_passes_test(is_admin)
def form_list(request):
    """List all forms."""
    forms = FormDefinition.objects.all().order_by('-created_at')
    
    # Get template definitions with FULL schema
    templates = []
    for key, template in TEMPLATES.items():
        templates.append({
            'key': key,
            'name': template['name'],
            'icon': template['icon'],
            'description': template['description'],
            'schema': template['schema'],  # ✅ Include the full schema
        })
    
    context = {
        'forms': forms,
        'templates': templates,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'form_builder/list.html', context)


@login_required
@user_passes_test(is_admin)
def form_create_modal(request):
    """Return the create form modal with templates."""
    templates = []
    for key, template in TEMPLATES.items():
        templates.append({
            'key': key,
            'name': template['name'],
            'icon': template['icon'],
            'description': template['description'],
            'schema': template['schema'],
        })
    
    return render(request, 'form_builder/partials/create_modal.html', {
        'templates': templates,
    })


@login_required
@user_passes_test(is_admin)
def form_builder(request, pk=None):
    """Form builder view."""
    
    form_instance = None
    form_schema = {'fields': []}
    
    if pk:
        form_instance = get_object_or_404(FormDefinition, pk=pk)
        form_schema = form_instance.schema or {'fields': []}
    
    # Get form data for settings panel
    form_data = {
        'title': form_instance.title if form_instance else '',
        'slug': form_instance.slug if form_instance else '',
        'description': form_instance.description if form_instance else '',
        'status': form_instance.status if form_instance else 'DRAFT',
        'form_type': form_instance.form_type if form_instance else 'OTHER',
        'require_login': form_instance.require_login if form_instance else True,
        'confirmation_message': form_instance.confirmation_message if form_instance else 'Thank you! Your submission has been received.',
        'redirect_url': form_instance.redirect_url if form_instance else '',
        'theme_color': form_instance.theme_color if form_instance else '#0D9488',
        'logo_enabled': form_instance.logo_enabled if form_instance else False,
    }
    
    context = {
        'form_instance': form_instance,
        'form_schema': json.dumps(form_schema),
        'form_data': form_data,
        'is_edit': bool(pk),
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'form_builder/builder.html', context)


@login_required
@user_passes_test(is_admin)
@require_POST
def form_save(request):
    """Save form definition."""
    
    try:
        data = json.loads(request.body)
        
        form_id = data.get('form_id')
        title = data.get('title', '').strip()
        description = data.get('description', '').strip()
        status = data.get('status', 'DRAFT')
        schema = data.get('schema', {'fields': []})
        require_login = data.get('require_login', True)
        confirmation_message = data.get('confirmation_message', 'Thank you! Your submission has been received.')
        redirect_url = data.get('redirect_url', '')
        form_type = data.get('form_type', 'OTHER')
        theme_color = data.get('theme_color', '#0D9488')
        logo_enabled = data.get('logo_enabled', False)
        
        if not title:
            return JsonResponse({'success': False, 'error': 'Title is required.'})
        
        if not schema.get('fields'):
            return JsonResponse({'success': False, 'error': 'Form must have at least one field.'})
        
        if form_id:
            form = get_object_or_404(FormDefinition, pk=form_id)
            form.title = title
            form.description = description
            form.status = status
            form.schema = schema
            form.require_login = require_login
            form.confirmation_message = confirmation_message
            form.redirect_url = redirect_url
            form.form_type = form_type
            form.theme_color = theme_color
            form.logo_enabled = logo_enabled
            form.save()
            message = f'Form "{form.title}" updated successfully!'
        else:
            form = FormDefinition.objects.create(
                title=title,
                description=description,
                status=status,
                schema=schema,
                created_by=request.user,
                require_login=require_login,
                confirmation_message=confirmation_message,
                redirect_url=redirect_url,
                form_type=form_type,
                theme_color=theme_color,
                logo_enabled=logo_enabled,
            )
            message = f'Form "{form.title}" created successfully!'
        
        return JsonResponse({
            'success': True,
            'message': message,
            'form_id': form.pk,
            'form_slug': form.slug,
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data.'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@user_passes_test(is_admin)
def form_preview(request, pk):
    """Preview form."""
    form = get_object_or_404(FormDefinition, pk=pk)
    
    context = {
        'form_instance': form,
        'sidebar_template': get_sidebar_template(request.user),
    }
    return render(request, 'form_builder/preview.html', context)


@login_required
def form_render(request, slug):
    """Render and handle form submissions."""
    
    form = get_object_or_404(FormDefinition, slug=slug, status=FormDefinition.Status.PUBLISHED)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            submission_data = data.get('data', {})
            
            submission = FormSubmission.objects.create(
                form=form,
                submitted_by=request.user if request.user.is_authenticated else None,
                data=submission_data,
            )
            
            return JsonResponse({
                'success': True,
                'message': form.confirmation_message,
                'redirect_url': form.redirect_url or '',
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid data.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    context = {
        'form_instance': form,
    }
    return render(request, 'form_builder/render.html', context)


@login_required
@user_passes_test(is_admin)
@require_POST
def form_delete(request, pk):
    """Delete a form."""
    
    form = get_object_or_404(FormDefinition, pk=pk)
    title = form.title
    
    if form.submission_count > 0:
        messages.warning(request, f'Cannot delete form with submissions. Archive it instead.')
        return redirect('form_builder:list')
    
    form.delete()
    messages.success(request, f'Form "{title}" deleted successfully.')
    return redirect('form_builder:list')


@login_required
@user_passes_test(is_admin)
@require_POST
def form_duplicate(request, pk):
    """Duplicate a form."""
    
    original = get_object_or_404(FormDefinition, pk=pk)
    
    new_form = FormDefinition.objects.create(
        title=f"{original.title} (Copy)",
        description=original.description,
        status=FormDefinition.Status.DRAFT,
        schema=original.schema,
        created_by=request.user,
        require_login=original.require_login,
        confirmation_message=original.confirmation_message,
        redirect_url=original.redirect_url,
        form_type=original.form_type,
        theme_color=original.theme_color,
        logo_enabled=original.logo_enabled,
    )
    
    messages.success(request, f'Form "{new_form.title}" created successfully.')
    return redirect('form_builder:builder', pk=new_form.pk)

# apps/form_builder/views.py - Add these functions

@login_required
@user_passes_test(is_admin)
def form_settings(request, pk):
    """Render form settings modal."""
    
    form = get_object_or_404(FormDefinition, pk=pk)
    
    context = {
        'form_instance': form,
        'form_data': {
            'title': form.title,
            'description': form.description,
            'form_type': form.form_type,
            'status': form.status,
            'require_login': form.require_login,
            'confirmation_message': form.confirmation_message,
            'redirect_url': form.redirect_url,
            'theme_color': form.theme_color if hasattr(form, 'theme_color') else '#0D9488',
            'logo_enabled': form.logo_enabled if hasattr(form, 'logo_enabled') else False,
        },
    }
    return render(request, 'form_builder/partials/settings_modal.html', context)


@login_required
@user_passes_test(is_admin)
@require_POST
def form_settings_save(request, pk):
    """Save form settings."""
    
    form = get_object_or_404(FormDefinition, pk=pk)
    
    form.title = request.POST.get('title', form.title).strip()
    form.description = request.POST.get('description', form.description).strip()
    form.form_type = request.POST.get('form_type', form.form_type)
    form.status = request.POST.get('status', form.status)
    form.require_login = request.POST.get('require_login') == 'on'
    form.confirmation_message = request.POST.get('confirmation_message', form.confirmation_message)
    form.redirect_url = request.POST.get('redirect_url', form.redirect_url).strip()
    form.theme_color = request.POST.get('theme_color', '#0D9488')
    form.logo_enabled = request.POST.get('logo_enabled') == 'on'
    form.save()
    
    messages.success(request, 'Form settings updated successfully!')
    
    if request.headers.get('HX-Request'):
        return HttpResponse('')
    return redirect('form_builder:builder', pk=form.pk)

    # apps/form_builder/views.py - Add this function

@login_required
def form_redirect(request, slug):
    """Redirect to the dynamic form renderer for known form slugs."""
    try:
        form = FormDefinition.objects.get(slug=slug, status=FormDefinition.Status.PUBLISHED)
        return redirect('form_builder:render', slug=slug)
    except FormDefinition.DoesNotExist:
        messages.error(request, f'Form "{slug}" not found.')
        return redirect('dashboard')