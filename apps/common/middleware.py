from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from datetime import datetime, timedelta
from django.utils import timezone

# apps/common/middleware.py

class CloudflareRealIPMiddleware(MiddlewareMixin):
    """Rewrites REMOTE_ADDR to the real client IP from Cloudflare's
    CF-Connecting-IP header before anything else runs (rate limiting, audit
    logs, ImpersonationLog, LoginHistory) — without this, every request
    behind Cloudflare/a Worker router appears to originate from Cloudflare's
    edge, breaking per-IP rate limiting and making audit trails useless.

    Must be first in MIDDLEWARE so downstream code sees the corrected value.
    Only takes effect when the header is present, so it's a no-op locally.
    Assumes the origin is only reachable through Cloudflare (Workers/
    Containers) — if the container is ever also exposed on a public IP
    directly, that path must be closed off, or this header becomes spoofable."""

    def process_request(self, request):
        real_ip = request.META.get('HTTP_CF_CONNECTING_IP')
        if real_ip:
            request.META['REMOTE_ADDR'] = real_ip
        return None


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Add additional security headers to all responses."""
    
    def process_response(self, request, response):
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS filter
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions policy — geolocation is allowed same-origin only, for
        # the Service Request form's device-location capture (see
        # templates/requester/service_request_form.html); microphone/camera
        # stay fully disabled, since nothing in the app uses them.
        response['Permissions-Policy'] = 'geolocation=(self), microphone=(), camera=()'

        # ================================================================
        # Skip X-Frame-Options for document viewer (PDF/Office previews)
        # ================================================================
        skip_frame_options = False

        # Check if this is a document viewer/serve request or PDF file
        if '/documents_display/document/' in request.path and ('/viewer/' in request.path or '/serve/' in request.path):
            skip_frame_options = True

        if '/media/display_docs/' in request.path:
            skip_frame_options = True

        # External (no-login) document share viewer's inline file-serving
        # endpoint — embedded via <embed>/<iframe> on document_share_external.html.
        if '/documents_display/share/' in request.path and '/serve/' in request.path:
            skip_frame_options = True

        # System Organogram export preview — framed in-app inside the export
        # modal's iframe. Only needs same-origin framing, unlike the document
        # viewer cases above, so allow that instead of skipping the header.
        if '/organogram/system/print/' in request.path:
            response['X-Frame-Options'] = 'SAMEORIGIN'
            skip_frame_options = True

        # Also check if the request is for a PDF
        if not skip_frame_options and hasattr(response, 'get'):
            content_type = response.get('Content-Type', '')
            if 'application/pdf' in content_type:
                skip_frame_options = True

        if not skip_frame_options:
            response['X-Frame-Options'] = 'DENY'
        elif response.get('X-Frame-Options') is None:
            # MIDDLEWARE lists django.middleware.clickjacking.XFrameOptionsMiddleware
            # BEFORE this middleware, which means — since Django runs
            # process_response in reverse middleware order — that builtin
            # middleware actually runs AFTER this one on the way out. Simply
            # leaving the header unset here doesn't mean "no restriction":
            # XFrameOptionsMiddleware then fills in its own default (DENY)
            # right afterward, silently undoing every skip_frame_options
            # case above (PDF previews included) regardless of the reasoning
            # here. xframe_options_exempt is the actual flag Django's
            # middleware checks before applying that default — set it
            # instead of relying on order-dependent header presence.
            response.xframe_options_exempt = True

        return response
    

class ImpersonationMiddleware(MiddlewareMixin):
    """
    Middleware to handle impersonation session.
    """
    
    def process_request(self, request):
        # Skip for login, logout, static, and impersonation paths
        skip_paths = [
            '/accounts/login',
            '/accounts/logout',
            '/static/',
            '/sw.js',
            '/accounts/impersonate/',
        ]
        for path in skip_paths:
            if request.path.startswith(path):
                return None
        
        # Check for impersonation data in session
        impersonate_data = request.session.get('impersonate')
        
        if impersonate_data:
            # Check if session has expired (1 hour)
            expires_at = impersonate_data.get('expires_at')
            if expires_at:
                try:
                    from datetime import datetime
                    expiry = datetime.fromisoformat(expires_at)
                    if timezone.now() > expiry:
                        # Session expired — actually end impersonation (log
                        # the admin back into their own account, close the
                        # audit log row), not just delete the session flag.
                        # The latter used to leave the admin fully
                        # authenticated as the target indefinitely, with no
                        # way back short of a full logout/login.
                        from apps.accounts.views.impersonate import end_impersonation
                        end_impersonation(request, impersonate_data)
                        messages.warning(
                            request,
                            'Impersonation session expired after 1 hour — you have been returned to your own account.'
                        )
                        return None
                except (ValueError, TypeError):
                    pass
            
            # Add impersonation data to request for context processors
            request.is_impersonating = True
            request.impersonation_data = {
                'target_user': impersonate_data.get('target_user_email'),
                'reason': impersonate_data.get('reason'),
                'original_user': impersonate_data.get('original_user_email'),
                'expires_at': impersonate_data.get('expires_at'),
            }

        return None


class LastSeenMiddleware(MiddlewareMixin):
    """Stamps User.last_seen on authenticated requests — the only signal the
    "online" indicator on the requester profile card (see
    apps.tickets.views.requester_profile_modal) is based on. Throttled to
    once per minute per user so it doesn't add a write to every request."""

    THROTTLE = timedelta(minutes=1)

    def process_request(self, request):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return None
        now = timezone.now()
        if user.last_seen and now - user.last_seen < self.THROTTLE:
            return None
        user.last_seen = now
        user.save(update_fields=['last_seen'])
        return None