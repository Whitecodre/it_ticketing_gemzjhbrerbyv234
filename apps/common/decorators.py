# apps/common/decorators.py

from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from functools import wraps


def document_admin_required(view_func):
    """
    Restrict a view to users who can manage display documents/categories
    (Admin role or superuser). Deliberately narrower than the generic
    is_admin() check used elsewhere: SUPERADMIN role is excluded (reserved
    for the vendor, not a client-facing role) — only User.Role.ADMIN and
    is_superuser qualify.
    """
    check = user_passes_test(lambda user: user.is_authenticated and user.can_manage_display_documents())
    return check(view_func)


def xframe_options_exempt(view_func):
    """
    Mark a view as exempt from X-Frame-Options header restrictions.
    Allows the view to be embedded in an iframe.
    """
    def wrapped_view(*args, **kwargs):
        response = view_func(*args, **kwargs)
        # Remove the X-Frame-Options header if it exists
        if 'X-Frame-Options' in response:
            del response['X-Frame-Options']
        return response
    return wraps(view_func)(wrapped_view)