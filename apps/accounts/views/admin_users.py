# apps/accounts/admin_users.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model
from django.db.models import Q
from apps.accounts.models import Role

User = get_user_model()

def is_admin(user):
    return user.role in ['ADMIN', 'SUPERADMIN']

def is_superadmin(user):
    return user.role == 'SUPERADMIN'

@login_required
@user_passes_test(is_admin)
def admin_user_list(request):
    query = request.GET.get('q', '')
    role_filter = request.GET.get('role', '')
    department_filter = request.GET.get('department', '')

    users = User.objects.all()
    if query:
        users = users.filter(
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        )
    if role_filter:
        users = users.filter(role=role_filter)
    if department_filter:
        users = users.filter(department=department_filter)

    # Dynamic sidebar for admin vs superadmin
    sidebar_template = 'partials/sidebar_admin.html' if request.user.role == 'ADMIN' else 'partials/sidebar_superadmin.html'

    context = {
        'users': users,
        'query': query,
        'role_filter': role_filter,
        'department_filter': department_filter,
        'role_choices': User.Role.choices,
        'department_choices': User.DEPARTMENT_CHOICES,
        'all_roles': Role.objects.all().order_by('priority'),
        'sidebar_template': sidebar_template,
    }

    if request.headers.get('HX-Request'):
        return render(request, 'partials/user_table.html', context)
    return render(request, 'admin/user_management.html', context)


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_user_create(request):
    email = request.POST.get('email')
    first_name = request.POST.get('first_name')
    last_name = request.POST.get('last_name')
    position = request.POST.get('position', '')
    role = request.POST.get('role', 'END_USER')
    selected_role_names = request.POST.getlist('selected_roles')
    
    # ✅ Only Superadmin can create Superadmin
    if role == 'SUPERADMIN' and request.user.role != 'SUPERADMIN':
        return JsonResponse({'error': 'Only a Superadmin can create another Superadmin.'}, status=403)
    
    department = request.POST.get('department', '')
    
    # ✅ Validate: Support roles only allowed for IT department
    support_roles = ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    if role in support_roles and department != 'IT':
        return JsonResponse({'error': f'"{role}" role can only be assigned to IT department users.'}, status=400)
    
    # ✅ Validate selected roles - only IT department can have support roles
    if selected_role_names:
        for selected_role in selected_role_names:
            if selected_role in support_roles and department != 'IT':
                return JsonResponse({'error': f'"{selected_role}" role can only be assigned to IT department users.'}, status=400)
    
    # Generate random password
    import string
    import secrets
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for i in range(12))
    
    if not email or not password:
        return JsonResponse({'error': 'Email and password are required.'}, status=400)

    if User.objects.filter(email=email).exists():
        return JsonResponse({'error': 'User with this email already exists.'}, status=400)

    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
        position=position,
        role=role,
        department=department,
        is_active=True,
        email_verified=True,
        password_changed=False,
    )

    # Get the primary role object
    primary_role_obj = Role.objects.filter(name=role).first()
    
    roles_to_add = []
    
    if primary_role_obj:
        roles_to_add.append(primary_role_obj)
    
    # Add any additional selected roles (excluding duplicates of primary)
    if selected_role_names:
        selected_roles = Role.objects.filter(name__in=selected_role_names)
        for selected_role in selected_roles:
            if selected_role.name != role:
                roles_to_add.append(selected_role)
    
    if roles_to_add:
        user.roles.set(roles_to_add)
        
        if primary_role_obj:
            user.active_role = primary_role_obj
            user.active_role_id = primary_role_obj.id
            user.role = primary_role_obj.name
            user.save(update_fields=['active_role', 'active_role_id', 'role'])
        else:
            highest_role = user.roles.order_by('priority').first()
            if highest_role:
                user.active_role = highest_role
                user.active_role_id = highest_role.id
                user.role = highest_role.name
                user.save(update_fields=['active_role', 'active_role_id', 'role'])
    else:
        user.roles.clear()
        user.active_role = None
        user.active_role_id = None
        user.save(update_fields=['active_role', 'active_role_id'])

    # Send email with credentials
    from apps.common.utils import send_email_via_brevo
    from django.template.loader import render_to_string
    from django.conf import settings
    
    html_message = render_to_string('emails/user_created.html', {
        'first_name': first_name,
        'last_name': last_name,
        'email': email,
        'password': password,
        'login_url': request.build_absolute_uri('/accounts/login/'),
        'admin_name': request.user.get_full_name() or request.user.email,
    })
    
    success, result = send_email_via_brevo(
        to_email=email,
        subject="Your TicketSwipe Account Has Been Created",
        html_content=html_message,
        from_email=settings.DEFAULT_FROM_EMAIL
    )
    
    if not success:
        print(f"❌ Failed to send user creation email: {result}")
    
    return JsonResponse({'status': 'ok', 'user_id': user.pk})


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    if user.role == 'SUPERADMIN' and request.user.role != 'SUPERADMIN':
        return JsonResponse({'error': 'You cannot edit a Superadmin.'}, status=403)

    # Get the primary role from the dropdown
    new_role = request.POST.get('role', user.role)
    selected_role_names = request.POST.getlist('selected_roles')
    
    if new_role == 'SUPERADMIN' and request.user.role != 'SUPERADMIN':
        return JsonResponse({'error': 'Only a Superadmin can assign the Superadmin role.'}, status=403)

    # ✅ Validate: Support roles only allowed for IT department
    support_roles = ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']
    new_department = request.POST.get('department', user.department)
    
    if new_role in support_roles and new_department != 'IT':
        return JsonResponse({'error': f'"{new_role}" role can only be assigned to IT department users.'}, status=400)
    
    if selected_role_names:
        for selected_role in selected_role_names:
            if selected_role in support_roles and new_department != 'IT':
                return JsonResponse({'error': f'"{selected_role}" role can only be assigned to IT department users.'}, status=400)

    new_is_active = request.POST.get('is_active', 'true') == 'true'
    
    if not new_is_active and user == request.user:
        return JsonResponse({'error': 'You cannot deactivate your own account.'}, status=400)
    
    if not new_is_active and user.role in ['ADMIN', 'SUPERADMIN']:
        active_admins = User.objects.filter(role__in=['ADMIN', 'SUPERADMIN'], is_active=True).count()
        if active_admins <= 1:
            return JsonResponse({'error': 'Cannot deactivate the last admin/superadmin.'}, status=400)

    # Update basic user info
    user.first_name = request.POST.get('first_name', user.first_name)
    user.last_name = request.POST.get('last_name', user.last_name)
    user.position = request.POST.get('position', user.position)
    user.department = new_department
    user.is_active = new_is_active
    user.role = new_role
    user.save()

    # Get the primary role object
    primary_role_obj = Role.objects.filter(name=new_role).first()
    
    roles_to_add = []
    
    if primary_role_obj:
        roles_to_add.append(primary_role_obj)
    
    if selected_role_names:
        selected_roles = Role.objects.filter(name__in=selected_role_names)
        for selected_role in selected_roles:
            if selected_role.name != new_role:
                roles_to_add.append(selected_role)
    
    if roles_to_add:
        user.roles.set(roles_to_add)
        
        if primary_role_obj:
            user.active_role = primary_role_obj
            user.active_role_id = primary_role_obj.id
            user.role = primary_role_obj.name
            user.save(update_fields=['active_role', 'active_role_id', 'role'])
        else:
            highest_role = user.roles.order_by('priority').first()
            if highest_role:
                user.active_role = highest_role
                user.active_role_id = highest_role.id
                user.role = highest_role.name
                user.save(update_fields=['active_role', 'active_role_id', 'role'])
            else:
                user.active_role = None
                user.active_role_id = None
                user.role = new_role
                user.save(update_fields=['active_role', 'active_role_id', 'role'])
    else:
        user.roles.clear()
        user.active_role = None
        user.active_role_id = None
        user.role = new_role
        user.save(update_fields=['active_role', 'active_role_id', 'role'])
    
    return JsonResponse({'status': 'ok'})


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    if user.role == 'SUPERADMIN' and request.user.role != 'SUPERADMIN':
        return JsonResponse({'error': 'Only a Superadmin can modify another Superadmin.'}, status=403)
    
    if user == request.user:
        return JsonResponse({'error': 'You cannot deactivate your own account.'}, status=400)
    
    if not user.is_active:
        pass
    else:
        if user.role in ['ADMIN', 'SUPERADMIN']:
            active_admins = User.objects.filter(role__in=['ADMIN', 'SUPERADMIN'], is_active=True).count()
            if active_admins <= 1:
                return JsonResponse({'error': 'Cannot deactivate the last admin/superadmin.'}, status=400)
    
    user.is_active = not user.is_active
    user.save()
    
    return JsonResponse({'status': 'ok', 'is_active': user.is_active})


@login_required
@user_passes_test(is_admin)
@require_POST
def admin_user_change_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    
    if user.role == 'SUPERADMIN' and request.user.role != 'SUPERADMIN':
        return JsonResponse({'error': 'Only a Superadmin can change another Superadmin\'s password.'}, status=403)

    new_password = request.POST.get('password', '').strip()
    
    if len(new_password) < 8:
        return JsonResponse({'error': 'Password must be at least 8 characters.'}, status=400)

    user.set_password(new_password)
    user.password_changed = True
    user.save()
    
    return JsonResponse({'status': 'ok', 'message': 'Password changed successfully.'})


@login_required
@user_passes_test(lambda u: u.role == 'ADMIN')
def client_logo_upload(request):
    """Upload or update the client company logo. Admin only."""
    if request.method == 'POST':
        from apps.accounts.models import ClientSettings
        
        settings, created = ClientSettings.objects.get_or_create(id=1)
        
        if 'logo' in request.FILES:
            logo = request.FILES['logo']
            
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
            if logo.content_type not in allowed_types:
                messages.error(request, 'Please upload a valid image (JPEG, PNG, GIF, or WEBP).')
                return redirect('accounts:profile')
            
            if logo.size > 2 * 1024 * 1024:
                messages.error(request, 'Logo must be less than 2MB.')
                return redirect('accounts:profile')
            
            if settings.logo and settings.logo.name != 'logos/default.png':
                try:
                    settings.logo.delete(save=False)
                except:
                    pass
            
            settings.logo = logo
            settings.updated_by = request.user
            settings.save()
            messages.success(request, 'Company logo updated successfully!')
            return redirect('accounts:profile')
        
        company_name = request.POST.get('company_name', '').strip()
        if company_name:
            settings.company_name = company_name
            settings.updated_by = request.user
            settings.save()
            messages.success(request, 'Company name updated successfully!')
            return redirect('accounts:profile')
        
        messages.error(request, 'No changes were made.')
        return redirect('accounts:profile')
    
    return redirect('accounts:profile')