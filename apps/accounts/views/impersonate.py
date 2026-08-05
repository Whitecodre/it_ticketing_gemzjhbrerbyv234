from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
from datetime import timedelta
import secrets
import logging

from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.utils import send_email_via_brevo

logger = logging.getLogger(__name__)


def is_admin(user):
    """Check if user is an Admin (can impersonate)."""
    return user.role == 'ADMIN'


def impersonate_modal(request):
    """Return the impersonation modal content."""
    user_id = request.GET.get('user_id')
    user_name = request.GET.get('user_name', 'User')
    
    return render(request, 'partials/impersonate_modal.html', {
        'user_id': user_id,
        'user_name': user_name,
    })


@csrf_exempt
@require_POST
def impersonate_start(request, user_id):
    """
    Start impersonating a user - creates a one-time token.
    This is called via AJAX from an authenticated session.
    """
    # Check if user is authenticated via session
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'message': 'You must be logged in to impersonate.'
        }, status=401)
    
    # Check if user is admin
    if request.user.role != 'ADMIN':
        return JsonResponse({
            'success': False,
            'message': 'You must be an Admin to impersonate.'
        }, status=403)
    
    target_user = get_object_or_404(User, pk=user_id)
    
    # SAFEGUARD 1: Cannot impersonate Admins or Superadmins
    if target_user.role in ['ADMIN', 'SUPERADMIN']:
        return JsonResponse({
            'success': False,
            'message': 'You cannot impersonate another Admin or Superadmin.'
        }, status=403)
    
    # SAFEGUARD 2: Cannot impersonate yourself
    if target_user == request.user:
        return JsonResponse({
            'success': False,
            'message': 'You cannot impersonate yourself.'
        }, status=403)
    
    # SAFEGUARD 3: Justification required
    reason = request.POST.get('reason', '').strip()
    if not reason:
        return JsonResponse({
            'success': False,
            'message': 'Please provide a reason for impersonation.'
        }, status=400)
    
    # SAFEGUARD 4: Check if user is active
    if not target_user.is_active:
        return JsonResponse({
            'success': False,
            'message': 'Cannot impersonate an inactive user.'
        }, status=400)
    
    # SAFEGUARD 5: Audit Log
    from apps.accounts.models import ImpersonationLog
    ImpersonationLog.objects.create(
        admin=request.user,
        target_user=target_user,
        reason=reason,
    )
    
    # SAFEGUARD 6: Notify the user (email)
    try:
        html_message = render_to_string('emails/impersonation_notification.html', {
            'user_name': target_user.get_full_name() or target_user.email,
            'admin_name': request.user.get_full_name() or request.user.email,
            'admin_email': request.user.email,
            'reason': reason,
            'login_url': request.build_absolute_uri(reverse('accounts:login')),
            'support_email': settings.DEFAULT_FROM_EMAIL,
            'now': timezone.now(),
        })
        
        success, result = send_email_via_brevo(
            to_email=target_user.email,
            subject=f"⚠️ An administrator has logged in as you",
            html_content=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL
        )
        if not success:
            logger.error(f"Failed to send impersonation notification email: {result}")
    except Exception as e:
        logger.error(f"Email error: {e}")
    
    # SAFEGUARD 7: In-app notification
    Notification.objects.create(
        recipient=target_user,
        message=f"⚠️ {request.user.get_full_name()} has logged in as you for: {reason}",
        url=reverse('dashboard'),
        type=Notification.Type.GENERAL
    )
    
    # ================================================================
    # TOKEN-BASED IMPERSONATION
    # ================================================================
    from apps.accounts.models import ImpersonationToken
    
    # Generate a secure token
    token = secrets.token_urlsafe(32)
    
    # Create token record
    impersonation_token = ImpersonationToken.objects.create(
        token=token,
        admin=request.user,
        target_user=target_user,
        reason=reason,
        expires_at=timezone.now() + timedelta(minutes=5),
    )
    
    # Build the token URL
    token_url = request.build_absolute_uri(
        reverse('accounts:impersonate_token', args=[token])
    )
    
    logger.info(f"Impersonation token created: {token_url}")
    
    # Return the redirect URL to the frontend
    return JsonResponse({
        'success': True,
        'message': f'Redirecting to {target_user.get_full_name()}...',
        'redirect': token_url
    })


def impersonate_token(request, token):
    """
    Validate the token and log in as the target user.
    This view is public (no login_required) because the user is not authenticated yet.
    """
    logger.info(f"impersonate_token called with token: {token}")
    from apps.accounts.models import ImpersonationToken
    
    impersonation_token = get_object_or_404(ImpersonationToken, token=token)
    
    # Check if token is valid
    if not impersonation_token.is_valid():
        if impersonation_token.used_at:
            messages.error(request, 'This impersonation link has already been used.')
        else:
            messages.error(request, 'This impersonation link has expired (5 minutes).')
        return redirect('accounts:login')
    
    # Get the target user
    target_user = impersonation_token.target_user
    
    # Check if the target user is still active
    if not target_user.is_active:
        messages.error(request, 'The target user account is inactive.')
        return redirect('accounts:login')
    
    # Store the original admin info before logout
    admin_user = impersonation_token.admin
    admin_id = admin_user.id
    admin_email = admin_user.email
    impersonation_reason = impersonation_token.reason
    token_id = impersonation_token.id
    
    # Logout the current user (if any)
    if request.user.is_authenticated:
        logout(request)
    
    # Login as the target user using the configured backend so the session
    # remains authenticated across the following redirect.
    backend_path = settings.AUTHENTICATION_BACKENDS[0]
    target_user.backend = backend_path
    login(request, target_user)
    
    # Mark token as used
    impersonation_token.use()
    
    # Store impersonation data in session for the banner
    request.session['impersonate'] = {
        'original_user_id': admin_id,
        'original_user_email': admin_email,
        'target_user_id': target_user.id,
        'target_user_email': target_user.email,
        'reason': impersonation_reason,
        'started_at': timezone.now().isoformat(),
        'expires_at': (timezone.now() + timedelta(hours=1)).isoformat(),
        'token_id': token_id,
    }
    
    # ================================================================
    # FORCE SESSION SAVE
    # ================================================================
    request.session.save()
    request.session.modified = True
    
    # Log the session key for debugging
    logger.info(f"Session saved with key: {request.session.session_key}")
    logger.info(f"Impersonation data: {request.session.get('impersonate')}")
    
    messages.success(request, f"You are now viewing as {target_user.get_full_name()} (Impersonation Mode).")
    
    # Redirect to dashboard
    return redirect('dashboard')


@login_required
@require_POST
def impersonate_stop(request):
    """
    Stop impersonating and return to original admin account.
    """
    impersonate_data = request.session.get('impersonate')
    
    if not impersonate_data:
        messages.error(request, 'You are not currently impersonating anyone.')
        return redirect('dashboard')
    
    original_user_id = impersonate_data.get('original_user_id')
    
    if not original_user_id:
        messages.error(request, 'Could not find original user session. Please log in again.')
        request.session.flush()
        return redirect('accounts:login')
    
    original_user = get_object_or_404(User, pk=original_user_id)
    
    # Audit Log - update end time
    from apps.accounts.models import ImpersonationLog
    impersonation_log = ImpersonationLog.objects.filter(
        admin=original_user,
        target_user=request.user,
        ended_at__isnull=True
    ).order_by('-started_at').first()

    if impersonation_log:
        impersonation_log.ended_at = timezone.now()
        impersonation_log.save()
    
    # Store original user info before logout
    original_user_email = original_user.email
    original_user_id = original_user.id
    
    # Logout the impersonated user
    logout(request)
    
    # Login as the original admin using the configured backend so the session
    # remains authenticated after stopping impersonation.
    backend_path = settings.AUTHENTICATION_BACKENDS[0]
    original_user.backend = backend_path
    login(request, original_user)
    
    # Clear impersonation data from session
    request.session.pop('impersonate', None)
    request.session.save()
    
    messages.success(request, f"✅ Returned to your account as {original_user.get_full_name()}.")
    return redirect('dashboard')


def impersonation_banner(request):
    """Render the impersonation banner partial."""
    return render(request, 'partials/impersonation_banner.html', {})