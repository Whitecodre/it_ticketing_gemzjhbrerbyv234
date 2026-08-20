# apps/knowledge_base/sanitize.py
"""
Sanitizes Article.content HTML before it's ever persisted. Written by the
single TipTap-based editor (static/js/kb_editor_src.js) used for all article
authoring, including ticket-conversion drafts — so the allowlist below is
exactly what that one editor's extensions can produce, not a generic guess.
Content authored here can be visibility=PUBLIC by the lowest-trust KB role
(Agent), so this is a real stored-XSS boundary, not just tidiness.
"""
import bleach
from bleach.css_sanitizer import CSSSanitizer

# TipTap extensions in use: StarterKit (headings, blockquote, hr, code
# blocks, strike, lists), Link, Image, Table/TableRow/TableCell/TableHeader,
# and the callout node (a styled div/blockquote carrying a "kb-callout"
# class — see kb_editor_src.js).
ALLOWED_TAGS = [
    'p', 'br', 'hr', 'div',
    'strong', 'b', 'em', 'i', 'u', 's', 'strike',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote',
    'a', 'img',
    'code', 'pre', 'span',
    'table', 'thead', 'tbody', 'tr', 'td', 'th',
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'span': ['style'],
    'p': ['style'],
    'h1': ['style'], 'h2': ['style'], 'h3': ['style'],
    'h4': ['style'], 'h5': ['style'], 'h6': ['style'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
    # Callout box variant (note/warning/tip) and any styled wrapper —
    # class values aren't restricted by bleach itself, but this field is
    # only ever written by AGENT/TEAM_LEAD/ADMIN/SUPERADMIN, same trust
    # level already extended to inline `style` above.
    'div': ['class'],
    'blockquote': ['class'],
}

# TinyMCE's forecolor/backcolor and alignleft/center/right/justify buttons
# both emit inline style="..." — nothing else in either editor's toolbar
# produces inline styles beyond color and text-align.
ALLOWED_STYLES = ['color', 'background-color', 'text-align']

# 'data' intentionally included: TinyMCE's paste_data_images=True pastes
# clipboard images as data: URIs with no separate upload step — without
# this, pasted images silently vanish on save.
ALLOWED_PROTOCOLS = ['http', 'https', 'mailto', 'data']

_css_sanitizer = CSSSanitizer(allowed_css_properties=ALLOWED_STYLES)


def sanitize_html(raw_html):
    """Strips any tag/attribute/style/protocol not on the allowlist above,
    keeping the enclosed text. Safe to call on already-clean content (no-op)."""
    if not raw_html:
        return raw_html
    return bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        css_sanitizer=_css_sanitizer,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
