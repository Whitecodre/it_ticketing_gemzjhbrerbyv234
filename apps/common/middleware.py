from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from datetime import datetime
from django.utils import timezone

# apps/common/middleware.py

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
                        # Session expired - clear it
                        request.session.pop('impersonate', None)
                        messages.warning(
                            request,
                            '⚠️ Impersonation session expired after 1 hour.'
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