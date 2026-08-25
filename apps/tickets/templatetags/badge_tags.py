import datetime
import json
from urllib.parse import urlencode as _urlencode

from django import template
from django.utils import timezone

register = template.Library()


@register.simple_tag
def build_qs(**kwargs):
    """Builds a URL querystring from arbitrary key=value kwargs, e.g.
    {% build_qs q=query category=selected_category %} -> "q=foo&category=bar".
    Used to hand a filter-scoped querystring to components/export_menu.html
    without a view needing to pre-build it — chaining |urlencode through
    Django's `add` filter can't safely encode individual values inside a
    concatenated string (it would double-encode or encode the separators).
    """
    return _urlencode({k: v for k, v in kwargs.items() if v is not None})


@register.inclusion_tag('components/breadcrumbs.html')
def breadcrumbs(*args):
    """Renders a breadcrumb trail for pages with real 3+ level navigation
    depth, replacing a bare back-arrow that can't show how deep the user is.

    Usage: {% url 'documents_display:dashboard' as docs_url %}
           {% breadcrumbs "Dashboard" dash_url "Documents" docs_url document.title %}

    Pass label,url pairs left to right. An unpaired trailing label (odd arg
    count) is the current page — rendered as plain text, not a link. Build
    any {% url %} value into a variable first (`{% url '...' as x %}`)
    since tag arguments can't contain template tags inline.
    """
    items = []
    rest = list(args)
    while rest:
        label = rest.pop(0)
        url = rest.pop(0) if rest else None
        items.append({'label': label, 'url': url})
    return {'items': items}


# ================================================================
# CENTRALIZED STATUS/PRIORITY/URGENCY/CONDITION → COLOR MAPPING
#
# Single source of truth for the "badge" components (components/status_badge.html).
# Reuses the existing .status-chip[.slug] / .priority-chip[.level] CSS
# classes already defined in theme.css rather than inventing new colors —
# this only centralizes the *lookup*, which was previously duplicated as
# inline {% if %}/{% elif %} chains per-template (asset_table.html,
# ticket_table.html, report_preview_table.html, etc.).
# ================================================================

# ONE canonical severity scale — Priority and Urgency represent the same
# kind of signal (how serious/urgent something is), so both are derived
# from this single ordered list rather than two independently-maintained
# mappings that happen to agree today. `.priority-chip.<level>` in
# theme.css is what actually assigns the colors (critical=red, high=orange,
# medium=gray, low=green) — this only guarantees Priority and Urgency pick
# the same level for the same severity.
SEVERITY_SCALE = ['critical', 'high', 'medium', 'low']

TICKET_PRIORITY_LEVELS = dict(zip(['P1', 'P2', 'P3', 'P4'], SEVERITY_SCALE))
TICKET_URGENCY_LEVELS = dict(zip(['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'], SEVERITY_SCALE))

ASSET_CONDITION_LEVELS = {
    'EXCELLENT': 'success',
    'GOOD': 'info',
    'FAIR': 'warning',
    'POOR': 'danger',
    'DAMAGED': 'danger',
}

# Best-effort text→tone matcher for places that only have the already
# -rendered display string, not the raw code (e.g. the generic Reports
# export table, whose columns/rows come from report_registry.py as
# plain strings for many different report types). Ordered dict-like list:
# first match wins, so more specific phrases are listed before their
# substrings (e.g. "pending" phrases before a bare "in").
_TEXT_TONE_RULES = [
    ('critical', 'danger'), ('p1', 'danger'), ('breached', 'danger'),
    ('escalated', 'danger'), ('damaged', 'danger'), ('lost', 'danger'),
    ('stolen', 'danger'), ('overdue', 'danger'), ('rejected', 'danger'),
    ('high', 'warning'), ('p2', 'warning'), ('pending', 'warning'),
    ('waiting', 'warning'), ('maintenance', 'warning'), ('repair', 'warning'),
    ('checked out', 'warning'), ('fair', 'warning'), ('p3', 'neutral'),
    ('medium', 'neutral'), ('low', 'success'), ('p4', 'success'),
    ('resolved', 'success'), ('approved', 'success'), ('completed', 'success'),
    ('fulfilled', 'success'), ('available', 'success'), ('active', 'success'),
    ('excellent', 'success'), ('good', 'success'), ('received', 'success'),
    ('returned', 'success'), ('new', 'info'), ('open', 'info'),
    ('assigned', 'primary'), ('triaged', 'primary'), ('in progress', 'primary'),
    ('mobilized', 'accent'), ('in use', 'accent'),
    ('closed', 'neutral'), ('retired', 'neutral'), ('scrapped', 'neutral'),
    ('disposed', 'neutral'),
]


def _tone_from_text(label):
    text = (label or '').strip().lower()
    for phrase, tone in _TEXT_TONE_RULES:
        if phrase in text:
            return tone
    return 'neutral'


@register.inclusion_tag('components/status_badge.html')
def status_badge(kind, value, secondary=None, display_label=None):
    """Render a single badge (dot + label, no repeated caption).

    kind: 'ticket_status' | 'ticket_priority' | 'ticket_urgency' |
          'asset_status' | 'asset_condition' | 'text'
    value: the raw code (Ticket.Status/.Priority/.Urgency, Asset.Status/
           .Condition) for the typed kinds, or the already-rendered display
           string for kind='text' (used where only display text is
           available, e.g. the generic report export table).
    secondary: optional extra line shown under the badge instead of a
               repeated status word (e.g. "since 3 days ago").
    display_label: override the label text (defaults to the human label
                   for typed kinds, or `value` itself for kind='text').
    """
    from apps.tickets.models import Ticket, Asset

    label = display_label
    css_class = 'status-chip status-chip-neutral'

    if kind == 'ticket_status':
        label = label or dict(Ticket.Status.choices).get(value, value)
        # These CSS selectors key on the bare lowercased status code
        # (.status-chip.new, .status-chip.in_progress, ...) — see theme.css.
        css_class = 'status-chip ' + (value or '').lower()
    elif kind == 'ticket_priority':
        label = label or dict(Ticket.Priority.choices).get(value, value)
        css_class = 'priority-chip ' + TICKET_PRIORITY_LEVELS.get(value, 'medium')
    elif kind == 'ticket_urgency':
        label = label or dict(Ticket.Urgency.choices).get(value, value)
        css_class = 'priority-chip ' + TICKET_URGENCY_LEVELS.get(value, 'medium')
    elif kind == 'asset_status':
        colors = {
            'REQUESTED': 'info', 'APPROVED': 'info', 'ORDERED': 'info',
            'RECEIVED': 'success', 'IN_STORE': 'success', 'READY': 'success',
            'CHECKED_OUT': 'warning', 'IN_USE': 'accent', 'MOBILIZED': 'accent',
            'MAINTENANCE': 'warning', 'REPAIR': 'danger', 'RETURNED': 'success',
            'RETIRED': 'neutral', 'SCRAPPED': 'neutral', 'LOST': 'danger',
            'STOLEN': 'danger', 'DISPOSED': 'neutral',
        }
        label = label or dict(Asset.Status.choices).get(value, value)
        css_class = 'status-chip status-chip-' + colors.get(value, 'neutral')
    elif kind == 'asset_condition':
        label = label or dict(Asset.Condition.choices).get(value, value)
        css_class = 'status-chip status-chip-' + ASSET_CONDITION_LEVELS.get(value, 'neutral')
    else:  # kind == 'text' — best-effort match on already-rendered text
        label = label or value
        css_class = 'status-chip status-chip-' + _tone_from_text(value)

    return {
        'label': label,
        'css_class': css_class,
        'secondary': secondary,
    }


@register.filter
def is_secondary_report_column(col):
    """Lower-priority report columns that collapse behind a 'Show more
    columns' toggle on narrow viewports (Fix 4) — the primary columns
    (Number/Title/Status/Priority/etc.) always stay visible.
    """
    secondary = {
        'how discovered', 'location / hostname', 'requester department',
        'vessels', 'job number', 'dive systems', 'business impact',
        'purpose', 'receipt confirmed', 'receipt confirmed by',
        'is asset request', 'is mobilization request', 'fulfilled by',
        'manufacturer', 'low stock threshold', 'renewal interval (months)',
        'renewal cost', 'renewal vendor', 'renewal reference', 'auto-renews',
    }
    return (col or '').strip().lower() in secondary


@register.filter
def any_secondary_columns(columns):
    return any(is_secondary_report_column(c) for c in (columns or []))


def _parse_date_presets_list(spec):
    presets = []
    for chunk in (spec or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        days, _, label = chunk.partition(':')
        presets.append({'days': int(days.strip()), 'label': label.strip() or f'{days.strip()}d'})
    return presets


@register.filter
def parse_date_presets(spec):
    """Parses a compact 'days:Label,days:Label' string into a JSON array
    string ready to drop straight into an Alpine x-data expression, e.g.
    '7:Last 7 days,30:Last 30 days,90:Last 90 days' or
    '0:Today,7:7 Days,30:This Month,90:This Quarter'. Matches each page's
    existing preset semantics exactly (days-ago cutoffs, not real calendar
    months/quarters) — this only changes how they're built, not what they
    compute. Returns real JSON (not Python repr) so labels containing
    quotes/special characters can't break the surrounding JS.
    """
    return json.dumps(_parse_date_presets_list(spec))


@register.simple_tag
def matching_preset_days(start, end, presets):
    """Which preset (if any) the given start/end dates correspond to,
    using the same 'today minus N days' formula as dateRangeFilter's own
    applyPreset() in static/js/date_range_filter.js. Used so the segmented
    control's active highlight survives a full page reload under
    apply_mode="redirect" (Alpine state resets to nothing on navigation,
    so without this the currently-active preset would look unselected).
    Returns the JS literal 'null' when nothing matches (a custom range).
    """
    if not start or not end:
        return 'null'

    def to_date(v):
        if isinstance(v, str):
            return datetime.date.fromisoformat(v)
        return v

    start_d, end_d = to_date(start), to_date(end)
    today = timezone.localdate()
    if end_d != today:
        return 'null'
    for preset in _parse_date_presets_list(presets):
        days = preset['days']
        expected_start = today - datetime.timedelta(days=days)
        if start_d == expected_start:
            return str(days)
    return 'null'


@register.filter
def parse_export_formats(spec):
    """Parses a compact 'format:Label:icon,format:Label:icon' string into
    the list of dicts components/export_menu.html expects. Lets a page add
    a new export format with a one-line string edit at the call site,
    instead of a new button + new context variable from the view.
    """
    formats = []
    for chunk in (spec or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(':')
        fmt = parts[0].strip()
        label = parts[1].strip() if len(parts) > 1 else fmt.upper()
        icon = parts[2].strip() if len(parts) > 2 else 'file'
        formats.append({'format': fmt, 'label': label, 'icon': icon})
    return formats
