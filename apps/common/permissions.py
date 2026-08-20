# apps/common/permissions.py
"""
Centralized role-check helpers for the dual-role system.

Every helper here resolves the user's *currently active* role via
`user.get_active_role()` and only falls back to the legacy `User.role`
CharField when no active role can be resolved at all (e.g. a user with no
Role rows assigned yet). This mirrors the pattern `apps.maintenance.views
.can_manage_maintenance()` already used correctly, and avoids the
role-desync bug where several call sites checked the legacy `role` field
directly — which can go stale relative to `active_role` after a role
switch or admin-side role reassignment.

Previously, near-identical `is_admin()`/`get_sidebar_template()`-style
helpers were duplicated (and sometimes legacy-only) across
apps/tickets/views.py (x2), apps/organogram/views.py,
apps/organogram/api_views.py, apps/accounts/views/admin_users.py, and
apps/tickets/views_settings.py's `_is_admin`. Those now import from here.
"""

SIDEBAR_TEMPLATE_MAP = {
    'END_USER': 'partials/sidebar_end_user.html',
    'AGENT': 'partials/sidebar_agent.html',
    'TEAM_LEAD': 'partials/sidebar_team_lead.html',
    'ADMIN': 'partials/sidebar_admin.html',
    'SUPERADMIN': 'partials/sidebar_superadmin.html',
}


def effective_role_name(user):
    """The name of the user's currently active role, falling back to the
    legacy `role` field only when no active role can be resolved."""
    active_role = user.get_active_role()
    return active_role.name if active_role else user.role


def get_sidebar_template(user):
    """Returns the correct sidebar partial template for the user's active role.

    A Team Lead outside IT was created solely for the departmental service-
    request approval flow — they get a separate, minimal sidebar (approvals
    + the same public-facing items an End User sees) instead of the
    IT-operational one (ticket queues, assets, reports, admin tools)."""
    role_name = effective_role_name(user)
    if role_name == 'TEAM_LEAD' and user.department != 'IT':
        return 'partials/sidebar_team_lead_approver.html'
    return SIDEBAR_TEMPLATE_MAP.get(role_name, 'partials/sidebar_end_user.html')


def is_admin(user):
    """ADMIN or SUPERADMIN, based on the user's active role."""
    return effective_role_name(user) in ('ADMIN', 'SUPERADMIN')


def is_superadmin(user):
    return effective_role_name(user) == 'SUPERADMIN'


def can_edit_org(user):
    role_name = effective_role_name(user)
    if role_name == 'TEAM_LEAD':
        return user.department == 'IT'
    return role_name in ('ADMIN', 'SUPERADMIN')


def is_support_staff(user):
    """IT department plus a staff-level active role (Agent/Team Lead/Admin/Superadmin)."""
    return user.department == 'IT' and effective_role_name(user) in (
        'AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'
    )
