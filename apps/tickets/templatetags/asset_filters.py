from django import template
from django.utils import timezone
from datetime import timedelta
import lucide

register = template.Library()

@register.filter
def format_assignment_history(asset):
    """Formats the assignment history as HTML for the tooltip."""
    history = asset.get_assignment_history()

    if not history:
        return '<div class="reassign-tooltip-content"><div class="text-xs text-text-secondary">No assignment history</div></div>'

    html = '<div class="reassign-tooltip-content">'
    html += '<div class="font-semibold text-xs mb-2 flex items-center gap-2" style="color: var(--color-text-primary);">'
    html += f'<span class="flex items-center gap-1">{lucide._render_icon("history", 14)} Reassign Trail</span>'
    html += f'<span class="text-[0.55rem] text-text-secondary font-normal">({len(history)} entries)</span>'
    html += '</div>'
    html += '<div class="space-y-1.5 max-h-48 overflow-y-auto pr-1">'
    
    for i, entry in enumerate(history):
        from_name = entry['from_user'] or 'Unassigned'
        to_name = entry['to_user'] or 'Unassigned'
        actor = entry['actor']
        time_ago = timezone.now() - entry['timestamp']
        
        if time_ago.days > 0:
            time_str = f"{time_ago.days}d ago"
        elif time_ago.seconds > 3600:
            time_str = f"{time_ago.seconds // 3600}h ago"
        elif time_ago.seconds > 60:
            time_str = f"{time_ago.seconds // 60}m ago"
        else:
            time_str = "Just now"
        
        # Highlight the latest assignment
        is_latest = i == len(history) - 1
        highlight_class = 'font-medium text-primary' if is_latest else ''
        
        html += f'''
        <div class="text-xs flex items-start gap-1.5 py-0.5" style="color: var(--color-text-secondary);">
            <span class="shrink-0 mt-0.5" style="color: var(--color-text-secondary);">{"●" if is_latest else "→"}</span>
            <span>
                <span style="color: var(--color-text-primary);">{from_name}</span>
                <span class="mx-0.5 text-text-secondary">→</span>
                <span class="{highlight_class}">{to_name}</span>
                <span class="text-[0.6rem] text-text-secondary ml-1">({actor}, {time_str})</span>
            </span>
        </div>
        '''
    
    html += '</div></div>'
    return html

@register.filter
def has_reassignment_indicator(asset):
    """Returns True if the asset should show the reassign indicator."""
    return asset.has_been_reassigned()

@register.filter
def reassign_count(asset):
    """Returns the number of reassignments."""
    return asset.get_reassignment_count()

@register.filter
def has_active_connector(connectors):
    """Returns True if any connector in the list is active."""
    if not connectors:
        return False
    return any(c.is_active for c in connectors)

@register.filter
def active_connector_name(connectors):
    """Returns the name of the first active connector."""
    for c in connectors:
        if c.is_active:
            return c.name
    return None