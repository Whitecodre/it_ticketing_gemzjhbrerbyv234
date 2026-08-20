# apps/maintenance/templatetags/maintenance_tags.py
from django import template
from ..views import can_change_maintenance_status

register = template.Library()


@register.simple_tag
def can_change_status(schedule, user):
    return can_change_maintenance_status(user, schedule)
