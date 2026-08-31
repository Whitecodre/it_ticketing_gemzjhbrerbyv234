from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
# from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
from datetime import timedelta
import secrets
import logging

from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.utils import send_email_via_brevo, role_of
from apps.common.permissions import effective_role_name

logger = logging.getLogger(__name__)


def can_impersonate(user):
    """Deliberately ADMIN-only — unlike apps.common.permissions.is_admin,
    SUPERADMIN does not qualify here (impersonation is reserved for
    client-side Admins, not the vendor role)."""
    return effective_role_name(user) == 'ADMIN'


@login_required
def impersonate_modal(request):
    """Return the impersonation modal content."""
    if not can_impersonate(request.user):
        return HttpResponse(status=403)

    user_id = request.GET.get('user_id')
    user_name = request.GET.get('user_name', 'User')

    return render(request, 'partials/impersonate_modal.html', {
        'user_id': user_id,
        'user_name': user_name,
    })


# @csrf_exempt
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
    if not can_impersonate(request.user):
        return JsonResponse({
            'success': False,
            'message': 'You must be an Admin to impersonate.'
        }, status=403)

    target_user = get_object_or_404(User, pk=user_id)

    # SAFEGUARD 1: Cannot impersonate Admins or Superadmins — checked against
    # every role the target holds, not just their currently active one.
    # effective_role_name() alone isn't enough here: a dual-role account can
    # hold ADMIN while displaying as e.g. AGENT, and impersonation logs in as
    # their real account, so the impersonating Admin could otherwise just
    # switch_role() the session into that account's ADMIN role afterwards.
    target_role_names = set(target_user.roles.values_list('name', flat=True))
    target_role_names.add(target_user.role)
    if target_role_names & {'ADMIN', 'SUPERADMIN'}:
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
    
    # NOTE: the audit log entry, notification email, and in-app notification
    # used to all fire right here — the moment impersonation is *requested*,
    # not when it's actually used. If the admin never followed the link (tab
    # closed, token left to expire), the target user still got told "an
    # administrator has logged in as you" for something that never happened,
    # and the audit trail gained a permanent open-ended log row. They now
    # fire in impersonate_token(), on successful redemption, below.

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

    # Never log the raw token/URL — it's a live "log in as this user" secret
    # for the next 5 minutes. Log only non-secret identifiers.
    logger.info(f"Impersonation token {impersonation_token.pk} created: admin={request.user.email} target={target_user.email}")

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
    from apps.accounts.models import ImpersonationToken

    impersonation_token = get_object_or_404(ImpersonationToken, token=token)
    logger.info(f"impersonate_token redemption attempt: token_id={impersonation_token.pk}")
    
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

    # Audit log, email, and in-app notification now fire here — on actual
    # redemption — rather than back in impersonate_start() when it was only
    # requested. See the note there for why that used to misfire.
    from apps.accounts.models import ImpersonationLog
    ImpersonationLog.objects.create(
        admin=admin_user,
        target_user=target_user,
        reason=impersonation_reason,
    )

    try:
        html_message = render_to_string('emails/impersonation_notification.html', {
            'user_name': target_user.get_full_name() or target_user.email,
            'admin_name': admin_user.get_full_name() or admin_email,
            'admin_email': admin_email,
            'reason': impersonation_reason,
            'login_url': request.build_absolute_uri(reverse('accounts:login')),
            'support_email': settings.DEFAULT_FROM_EMAIL,
            'now': timezone.now(),
        })

        success, result = send_email_via_brevo(
            to_email=target_user.email,
            subject="⚠️ An administrator has logged in as you",
            html_content=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL
        )
        if not success:
            logger.error(f"Failed to send impersonation notification email: {result}")
    except Exception as e:
        logger.error(f"Email error: {e}")

    Notification.objects.create(
        recipient=target_user,
        role=role_of(target_user),
        message=f"{admin_user.get_full_name()} has logged in as you for: {impersonation_reason}",
        url=reverse('dashboard'),
        type=Notification.Type.GENERAL
    )

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

    logger.info(f"Impersonation session started: admin={admin_email} target={target_user.email}")

    messages.success(request, f"You are now viewing as {target_user.get_full_name()} (Impersonation Mode).")
    
    # Redirect to dashboard
    return redirect('dashboard')


def end_impersonation(request, impersonate_data):
    """Actually terminates impersonation: logs the admin back into their own
    account and closes the ImpersonationLog row. Shared by impersonate_stop
    (manual "Return to my account") and the expiry paths in
    ImpersonationMiddleware / impersonation_context — both of which used to
    just delete the session flag and leave the admin fully authenticated as
    the target user indefinitely once the 1-hour window passed, with no
    way back short of a full logout/login.

    Returns the original admin User on success, or None if the session data
    was unusable (caller should just drop the session key and move on)."""
    from apps.accounts.models import ImpersonationLog

    original_user_id = impersonate_data.get('original_user_id')
    original_user = User.objects.filter(pk=original_user_id).first() if original_user_id else None
    if not original_user:
        request.session.pop('impersonate', None)
        return None

    impersonation_log = ImpersonationLog.objects.filter(
        admin=original_user,
        target_user_id=impersonate_data.get('target_user_id'),
        ended_at__isnull=True,
    ).order_by('-started_at').first()
    if impersonation_log:
        impersonation_log.ended_at = timezone.now()
        impersonation_log.save(update_fields=['ended_at'])

    logout(request)
    backend_path = settings.AUTHENTICATION_BACKENDS[0]
    original_user.backend = backend_path
    login(request, original_user)

    request.session.pop('impersonate', None)
    request.session.save()
    return original_user


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

    original_user = end_impersonation(request, impersonate_data)

    if not original_user:
        messages.error(request, 'Could not find original user session. Please log in again.')
        request.session.flush()
        return redirect('accounts:login')

    messages.success(request, f"Returned to your account as {original_user.get_full_name()}.")
    return redirect('dashboard')


def impersonation_banner(request):
    """Render the impersonation banner partial."""
    return render(request, 'partials/impersonation_banner.html', {})