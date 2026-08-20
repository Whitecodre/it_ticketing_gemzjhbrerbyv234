from django import template

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
