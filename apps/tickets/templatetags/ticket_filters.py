from django import template
from django.utils.html import format_html

# Captured before the filter below shadows the builtin `getattr` name in this
# module's namespace.
_builtin_getattr = getattr

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, 0)

@register.filter(name='getattr')
def get_attribute(obj, attr_name):
    value = _builtin_getattr(obj, attr_name, '')
    # A related manager (M2M/reverse-FK) doesn't stringify usefully — used
    # by the generic System Settings edit modal to pre-check the right
    # boxes for a multiselect field, so it needs the related objects' pks,
    # not the manager's repr. Generic over any future M2M settings field.
    if hasattr(value, 'all') and hasattr(value, 'model'):
        return ','.join(str(pk) for pk in value.values_list('pk', flat=True))
    return value


@register.filter
def settings_cell(row, col_attr):
    """Same lookup as the `getattr` filter above, but renders a boolean
    value as a status pill instead of the literal words True/False — used
    by the generic System Settings table (system_settings.html), which
    otherwise has no way to know a given column is a boolean."""
    value = get_attribute(row, col_attr)
    if isinstance(value, bool):
        if col_attr == 'is_active':
            label, css = ('Active', 'status-chip-success') if value else ('Inactive', 'status-chip-neutral')
        else:
            label, css = ('Yes', 'status-chip-success') if value else ('No', 'status-chip-neutral')
        return format_html('<span class="status-chip {} text-xs">{}</span>', css, label)
    return value
