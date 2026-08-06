# apps/maintenance/templatetags/maintenance_filters.py
from django import template

register = template.Library()

@register.filter
def split(value, arg):
    """Split a string by the given delimiter."""
    if not value:
        return []
    return value.split(arg)