from django import template


register = template.Library()


@register.filter
def get_item(mapping, key):
    """Return a value from JSON submission data without failing on missing keys."""
    if not isinstance(mapping, dict):
        return None
    return mapping.get(key)
