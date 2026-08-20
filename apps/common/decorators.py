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
    Allows the view to be embedded in an iframe/embed.

    Deleting the header here isn't enough on its own: django.middleware.
    clickjacking.XFrameOptionsMiddleware (Django's built-in, in MIDDLEWARE
    in config/settings/base.py, positioned so its process_response runs
    *after* apps.common.middleware.SecurityHeadersMiddleware's) re-adds
    X-Frame-Options: DENY to any response that doesn't already have the
    header AND doesn't have `response.xframe_options_exempt = True` set -
    a name-alike but functionally different marker than this decorator's
    own name. Without setting that attribute, every view using this
    decorator (document previews, PDF exports, etc.) silently got the
    header put back, breaking in-browser embedding regardless of what this
    function or SecurityHeadersMiddleware intended.
    """
    def wrapped_view(*args, **kwargs):
        response = view_func(*args, **kwargs)
        if 'X-Frame-Options' in response:
            del response['X-Frame-Options']
        response.xframe_options_exempt = True
        return response
    return wraps(view_func)(wrapped_view)