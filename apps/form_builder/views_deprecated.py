# apps/form_builder/views_deprecated.py

from django.shortcuts import render
from django.http import HttpResponseGone
from django.contrib.auth.decorators import login_required


@login_required
def form_builder_deprecated(request):
    """Display a deprecation message for the Form Builder."""
    return render(request, 'form_builder/deprecated.html', {
        'title': 'Form Builder - Deprecated',
        'message': 'The Form Builder has been deprecated. Please contact your administrator for assistance.',
    })


@login_required
def form_redirect_deprecated(request, slug=None):
    """Redirect deprecated form URLs to the deprecation page."""
    return render(request, 'form_builder/deprecated.html', {
        'title': 'Form Not Available',
        'message': f'The form "{slug}" is no longer available. Please use the standard ticket creation process.',
    })