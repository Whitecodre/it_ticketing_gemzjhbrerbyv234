from html import unescape

from django import template
from django.utils.html import strip_tags

register = template.Library()


@register.filter
def plain_preview(value, length=120):
    """Article content -> safe plain-text card preview.

    Article content is real HTML with entity-escaped text (e.g. ticket
    scaffolds store literal apostrophes as `&#x27;` — see
    _build_ticket_scaffold_html), meant to be rendered with the `safe`
    filter. `strip_tags` alone leaves those entities undecoded, so the
    template's normal autoescaping re-escapes the `&` and the entity shows
    up as literal text instead of the character it represents. Decoding
    here, before autoescape runs, avoids that.
    """
    text = unescape(strip_tags(value or ''))
    length = int(length)
    if len(text) > length:
        text = text[:length].rstrip() + '…'
    return text
