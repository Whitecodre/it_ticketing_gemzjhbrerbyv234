from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from datetime import datetime
from django.utils import timezone

class SecurityHeadersMiddleware(MiddlewareMixin):
    """Add additional security headers to all responses."""
    
    def process_response(self, request, response):
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Enable XSS filter
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer policy
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions policy (blocks features that could be abused)
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
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