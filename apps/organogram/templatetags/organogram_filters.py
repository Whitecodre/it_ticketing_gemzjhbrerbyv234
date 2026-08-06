# apps/organogram/templatetags/organogram_filters.py
from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary using a key."""
    if dictionary is None:
        return '#64748B'
    if key is None:
        return '#64748B'
    return dictionary.get(key, '#64748B')


@register.filter
def get_department_color(department, department_colors):
    """Get department color from colors dict."""
    if not department_colors:
        return '#64748B'
    return department_colors.get(department, '#64748B')