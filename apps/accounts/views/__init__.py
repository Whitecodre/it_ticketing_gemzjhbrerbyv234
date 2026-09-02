import logging
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.urls import reverse
from apps.common.utils import send_email_via_brevo
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.views import LoginView
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import strip_tags
from django.db.models import F, DurationField, ExpressionWrapper, Count, Q
from apps.common.permissions import effective_role_name
from django.core.cache import cache
from datetime import timedelta
from ..forms import ProfileForm, EmailAuthenticationForm, RegistrationStep1Form, RegistrationStep2Form, ChangePasswordForm, UserSettingsForm
from ..models import User, UserProfile, Role
from ..utils import validate_password_strength
from apps.tickets.models import Ticket, TicketActivityLog, SLA, BusinessCalendar, EscalationRule, RemoteConnector, TicketComment, RemoteSession
from apps.tickets.views import get_sidebar_template
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django_ratelimit.decorators import ratelimit

User = get_user_model()
logger = logging.getLogger(__name__)


def _ticket_status_counts(ticket_qs):
    """Return a dict of status -> count for the queryset, collapsing multiple
    count queries for dashboard KPI cards into a single aggregated fetch."""
    counts = dict(ticket_qs.values_list('status').annotate(total=Count('id')).values_list('status', 'total'))
    return {status: counts.get(status, 0) for status in dict(Ticket.Status.choices)}


@method_decorator(ratelimit(key='ip', rate='5/15m', method='POST', block=True), name='dispatch')
@method_decorator(csrf_protect, name='dispatch')
class CustomLoginView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = False  # ← This is the key change

    def form_valid(self, form):
        remember_me = self.request.POST.get('remember_me')
        if remember_me:
            self.request.session.set_expiry(30 * 24 * 60 * 60)
        else:
            self.request.session.set_expiry(0)

        user = form.get_user()
        
        # Check if user needs to change password
        if not user.password_changed:
            # Log the user in
            from django.contrib.auth import login
            login(self.request, user)
            # Redirect to force password change
            return redirect('accounts:force_password_change')
        
        # Clear sidebar state on fresh login - set session flag
        self.request.session['clear_sidebar'] = True
        
        # Normal flow - call parent
        return super().form_valid(form)

    def form_invalid(self, form):
        return self.render_to_response(
            self.get_context_data(
                form=form,
                username=form.data.get('username', '')
            )
        )
    
@method_decorator(ratelimit(key='ip', rate='5/15m', method='POST', block=True), name='dispatch')
class CustomPasswordResetView(PasswordResetView):
    """
    Custom password reset view that uses Brevo API instead of send_mail.
    """
    template_name = 'registration/password_reset.html'
    email_template_name = 'registration/password_reset_email.html'
    subject_template_name = 'registration/password_reset_subject.txt'
    success_url = '/accounts/password-reset/done/'
    token_generator = default_token_generator

    def form_valid(self, form):
        # PasswordResetForm.save() calls `self.send_mail(...)` where `self`
        # is the FORM instance, not this view — Django's PasswordResetForm
        # defines its own send_mail (which sends the rendered HTML template
        # as a *plain-text* body with no html_email_template_name set,
        # producing literal raw HTML in the inbox). Overriding send_mail
        # only on this view was silently never called. Binding it onto the
        # form instance here makes attribute lookup find ours first
        # (instance attributes shadow class methods in Python).
        form.send_mail = self.send_mail
        return super().form_valid(form)

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        """
        Override the default send_mail to use SMTP (see send_email_via_brevo).
        """
        # render_to_string() has no request here, so the client_settings
        # context processor never runs — the email templates need the
        # white-label company name/logo injected explicitly instead of
        # hardcoding a specific client's branding.
        from apps.accounts.models import ClientSettings
        client = ClientSettings.objects.first()
        logo_url = None
        if client and client.logo:
            # An email client has no browser location to resolve a relative
            # URL against, unlike Cloudinary's already-absolute production
            # URLs — local/dev media storage returns a relative path, so
            # prefix it with SITE_URL the same way notify_recipients_by_email
            # already does for notification links.
            logo_url = client.logo.url
            if logo_url.startswith('/'):
                logo_url = f'{settings.SITE_URL}{logo_url}'
        context = {
            **context,
            'client_settings': {
                'company_name': client.company_name if client else 'My Company',
                'logo_url': logo_url,
            },
        }

        subject = render_to_string(subject_template_name, context)
        # Email subject *must not* contain newlines
        subject = ''.join(subject.splitlines())

        body = render_to_string(email_template_name, context)
        
        # Send via Brevo API
        success, result = send_email_via_brevo(
            to_email=to_email,
            subject=subject,
            html_content=body,
            from_email=from_email
        )
        
        if not success:
            logger.error(f"Password reset email failed for {to_email}: {result}")
        
        return success


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    """
    Password reset confirm view that also marks the user as having
    changed their password, so accounts created via admin_user_create
    (which set an unusable password and send this same link) aren't
    routed into force_password_change right after setting one here.
    """
    template_name = 'registration/password_reset_confirm.html'
    success_url = '/accounts/password-reset-complete/'

    def form_valid(self, form):
        response = super().form_valid(form)
        self.user.password_changed = True
        self.user.save(update_fields=['password_changed'])
        return response


def validate_email_ajax(request):
    email = request.GET.get('email', '').strip()
    if not email:
        return render(request, 'partials/email_validation.html', {
            'valid': False,
            'message': 'Email is required.'
        })
    if User.objects.filter(email=email).exists():
        return render(request, 'partials/email_validation.html', {
            'valid': False,
            'message': 'This email is already registered.'
        })
    return render(request, 'partials/email_validation.html', {
        'valid': True,
        'message': 'Email is available.'
    })

def validate_password_ajax(request):
    password = request.GET.get('password') or request.GET.get('password1', '')
    if not password:
        return HttpResponse('')
    result = validate_password_strength(password)
    try:
        from django.contrib.auth.password_validation import validate_password
        validate_password(password)
        result['valid'] = True
    except Exception:
        result['valid'] = False
    return render(request, 'partials/password_strength.html', result)

@login_required
def validate_current_password_ajax(request):
    if request.method != 'POST':
        return HttpResponse('')
    old_password = request.POST.get('old_password', '')
    if not old_password:
        return render(request, 'partials/current_password_check.html', {
            'valid': False,
            'message': '',
        })
    valid = request.user.check_password(old_password)
    return render(request, 'partials/current_password_check.html', {
        'valid': valid,
        'message': '' if valid else 'Current password is incorrect.',
    })

@login_required
def force_password_change(request):
    """
    Forces user to change password on first login.
    """
    user = request.user
    
    # If user already changed password, redirect to dashboard
    if user.password_changed:
        return redirect('dashboard')
    
     # If user is not authenticated, redirect to login
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'skip':
            # Mark as changed so they don't see this page again
            user.password_changed = True
            user.save()
            messages.info(request, 'You can change your password later from your profile settings.')
            return redirect('dashboard')
        
        elif action == 'change':
            # Process password change
            password1 = request.POST.get('password1')
            password2 = request.POST.get('password2')
            
            if password1 != password2:
                messages.error(request, 'Passwords do not match.')
                return render(request, 'registration/force_password_change.html', {
                    'user': user,
                })
            
            if len(password1) < 8:
                messages.error(request, 'Password must be at least 8 characters.')
                return render(request, 'registration/force_password_change.html', {
                    'user': user,
                })
            
            # Set new password
            user.set_password(password1)
            user.password_changed = True
            user.save()
            
            # Update session hash to prevent logout
            update_session_auth_hash(request, user)
            
            messages.success(request, 'Password changed successfully.')
            return redirect('dashboard')
    
    return render(request, 'registration/force_password_change.html', {
        'user': user,
    })

DASHBOARD_ADMIN_KPI_CACHE_KEY = 'dashboard:admin_kpis'
DASHBOARD_ADMIN_KPI_CACHE_TTL = 60  # seconds — same for every Admin/Superadmin, org-wide, not per-user


def _get_admin_dashboard_kpis():
    """Org-wide ticket/asset KPI aggregates shown on the Admin/Superadmin
    dashboard. Identical for every admin viewing the page at a given moment,
    so it's cached rather than recomputed on every single request."""
    cached = cache.get(DASHBOARD_ADMIN_KPI_CACHE_KEY)
    if cached is not None:
        return cached

    total_tickets_month = Ticket.objects.filter(
        created_at__year=timezone.now().year, created_at__month=timezone.now().month
    ).count()

    sla_minutes_by_priority = dict(SLA.objects.values_list('priority', 'resolution_minutes'))
    compliant = 0
    total = 0
    for priority, created_at, resolved_at in Ticket.objects.filter(
        status__in=['RESOLVED', 'CLOSED'], resolved_at__isnull=False
    ).values_list('priority', 'created_at', 'resolved_at'):
        resolution_minutes = sla_minutes_by_priority.get(priority)
        if resolution_minutes is not None:
            resolution_time = resolved_at - created_at
            if resolution_time.total_seconds() / 60 <= resolution_minutes:
                compliant += 1
        total += 1
    sla_compliance = round((compliant / total * 100), 1) if total > 0 else 100.0

    pending_fulfillment_count = Ticket.objects.filter(status=Ticket.Status.PENDING_FULFILLMENT).count()

    # Shared with the asset inventory page's own KPI strip (see
    # apps.tickets.views.get_asset_kpis) so the two never drift apart.
    from apps.tickets.views import get_asset_kpis
    asset_kpis = get_asset_kpis()

    approved_requests = Ticket.objects.filter(
        type=Ticket.Type.SERVICE_REQUEST,
        status=Ticket.Status.APPROVED
    ).count()

    fulfilled_this_month = Ticket.objects.filter(
        type=Ticket.Type.SERVICE_REQUEST,
        is_asset_request=True,
        fulfilled_at__month=timezone.now().month
    ).count()

    kpis = {
        'total_tickets_month': total_tickets_month,
        'sla_compliance': sla_compliance,
        'connectors': list(RemoteConnector.objects.all().order_by('name')),
        'active_connectors': RemoteConnector.objects.filter(is_active=True).count(),
        'slas': list(SLA.objects.all().order_by('priority')),
        'escalation_rules': list(EscalationRule.objects.all().order_by('priority', 'timer_type', 'threshold_percent')),
        'calendars': list(BusinessCalendar.objects.all()),
        'recent_audit_logs': list(TicketActivityLog.objects.select_related('ticket', 'actor').order_by('-created_at')[:5]),
        'role_choices': User.Role.choices,
        'pending_fulfillment_count': pending_fulfillment_count,
        **asset_kpis,
        'approved_requests': approved_requests,
        'fulfilled_this_month': fulfilled_this_month,
    }
    cache.set(DASHBOARD_ADMIN_KPI_CACHE_KEY, kpis, DASHBOARD_ADMIN_KPI_CACHE_TTL)
    return kpis


@login_required
def dashboard(request):
    user = request.user
    
    # ================================================================
    # DUAL ROLES: Get active role
    # ================================================================
    active_role = user.get_active_role()
    
    # If no active role, use the highest priority role. Save `role` (legacy
    # field) alongside `active_role` in the same call — several templates
    # and views still gate on the legacy field directly, so leaving it
    # stale here was the root cause of the role-visibility desync bug.
    if not active_role:
        active_role = user.roles.order_by('priority').first()
        if active_role:
            user.active_role = active_role
            user.role = active_role.name
            user.save(update_fields=['active_role', 'role'])
    
    # Determine template based on active role. A Team Lead outside IT is
    # scoped solely to the service-request approval flow for now, so they
    # get the same dashboard an End User sees (no IT-operational stats)
    # rather than the IT Team Lead one.
    is_it_team_lead = active_role and active_role.name == 'TEAM_LEAD' and user.department == 'IT'
    if active_role:
        role_name = active_role.name
        template_map = {
            'SUPERADMIN': 'dashboards/super_admin_dashboard.html',
            'ADMIN': 'dashboards/admin_dashboard.html',
            'TEAM_LEAD': 'dashboards/team_lead_dashboard.html',
            'AGENT': 'dashboards/agent_dashboard.html',
            'END_USER': 'dashboards/end_user_dashboard.html',
        }
        if role_name == 'TEAM_LEAD' and not is_it_team_lead:
            template = 'dashboards/end_user_dashboard.html'
        else:
            template = template_map.get(role_name, 'dashboards/end_user_dashboard.html')
    else:
        # Fallback for users with no roles
        template = 'dashboards/end_user_dashboard.html'
    
    # ================================================================
    # Build context based on active role
    # ================================================================
    context = {}

    # Time-of-day greeting for the welcome banner, shared across every
    # role's dashboard template since they all render through this view.
    local_hour = timezone.localtime().hour
    if local_hour < 12:
        context['greeting'] = 'Good morning'
    elif local_hour < 17:
        context['greeting'] = 'Good afternoon'
    else:
        context['greeting'] = 'Good evening'

    # Remote sessions needing this user's action right now — surfaced as a
    # banner at the top of the dashboard so Accept/Reject/Start aren't only
    # reachable via a notification/email link. Scoped to whichever role is
    # currently active: the requester-side "needs accept/reject" prompt only
    # while active as End User, the agent-side "needs start" prompt only
    # while active in a staff role — a dual-role account (e.g. Agent + End
    # User) shouldn't see both prompts at once regardless of which hat is on
    # (previously this queried both sides unconditionally).
    _active_role_name = active_role.name if active_role else None
    if _active_role_name == 'END_USER' or (_active_role_name == 'TEAM_LEAD' and not is_it_team_lead):
        _pending_q = Q(requester=request.user, status=RemoteSession.Status.REQUESTED)
    elif _active_role_name in ('AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'):
        _pending_q = Q(agent=request.user, status=RemoteSession.Status.ACCEPTED)
    else:
        _pending_q = None

    context['pending_remote_sessions'] = list(
        RemoteSession.objects.filter(_pending_q)
        .select_related('ticket', 'requester', 'agent').order_by('-created_at')
    ) if _pending_q is not None else []

    if active_role and (active_role.name == 'END_USER' or (active_role.name == 'TEAM_LEAD' and not is_it_team_lead)):
        # Must match my_ticket_list's OPEN bucket (apps/tickets/views.py) so
        # the "Open" KPI card's count agrees with what clicking through to
        # ?status=OPEN actually shows.
        open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR', 'APPROVED']
        requester_qs = Ticket.objects.filter(requester=request.user)
        status_counts = _ticket_status_counts(requester_qs)

        context['open_tickets_count'] = sum(status_counts[status] for status in open_statuses)
        context['recent_tickets'] = requester_qs.order_by('-created_at')[:5]
        context['all_count'] = requester_qs.count()
        context['open_count'] = sum(status_counts[status] for status in open_statuses)
        context['in_progress_count'] = status_counts.get('IN_PROGRESS', 0)
        context['resolved_count'] = status_counts.get('RESOLVED', 0)
        context['closed_count'] = status_counts.get('CLOSED', 0)

    elif active_role and active_role.name in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN'] and (active_role.name != 'TEAM_LEAD' or is_it_team_lead):
        open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']
        
        resolved_tickets = list(Ticket.objects.filter(
            assigned_to=request.user,
            status__in=['RESOLVED', 'CLOSED'],
            resolved_at__isnull=False,
        ).only('id', 'resolved_at', 'assigned_to'))
        total_resolved = len(resolved_tickets)

        resolved_ticket_ids = [t.id for t in resolved_tickets]

        # Earliest "assigned to me" activity log per ticket, in one query
        # instead of one query per ticket (was run twice — once for
        # resolution time, once for response time — hence the merge below).
        assigned_at_by_ticket = {}
        for log in TicketActivityLog.objects.filter(
            ticket_id__in=resolved_ticket_ids,
            action='assigned',
            details__to=request.user.get_full_name()
        ).order_by('ticket_id', 'created_at'):
            assigned_at_by_ticket.setdefault(log.ticket_id, log.created_at)

        # Earliest public reply by this agent per ticket, in one query.
        first_reply_at_by_ticket = {}
        for comment in TicketComment.objects.filter(
            ticket_id__in=resolved_ticket_ids,
            author=request.user,
            visibility='PUBLIC'
        ).order_by('ticket_id', 'created_at'):
            first_reply_at_by_ticket.setdefault(comment.ticket_id, comment.created_at)

        resolution_times = []
        response_times = []
        for ticket in resolved_tickets:
            assigned_at = assigned_at_by_ticket.get(ticket.id)
            if not assigned_at:
                continue
            resolution_times.append((ticket.resolved_at - assigned_at).total_seconds() / 3600)
            first_reply_at = first_reply_at_by_ticket.get(ticket.id)
            if first_reply_at:
                response_times.append((first_reply_at - assigned_at).total_seconds() / 60)

        avg_resolution_time = round(sum(resolution_times) / len(resolution_times), 1) if resolution_times else None
        avg_response_time = round(sum(response_times) / len(response_times), 1) if response_times else None
        
        my_open_tickets = Ticket.objects.filter(
            assigned_to=request.user,
            status__in=open_statuses
        ).count()

        unassigned_qs = Ticket.objects.filter(
            assigned_to__isnull=True
        ).exclude(status__in=[
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
            Ticket.Status.PENDING_APPROVAL,
            Ticket.Status.PENDING_MANAGER_REVIEW,
            Ticket.Status.PENDING_FULFILLMENT,
        ])

        unassigned_count = unassigned_qs.count()

        recent_unassigned = unassigned_qs.order_by('-created_at')[:5]

        assigned_to_me_tickets = Ticket.objects.filter(
            assigned_to=request.user
        ).exclude(status__in=['RESOLVED', 'CLOSED']).order_by('-created_at')[:5]
        
        context['total_resolved'] = total_resolved
        context['avg_resolution_time'] = avg_resolution_time
        context['avg_response_time'] = avg_response_time
        context['my_open_tickets'] = my_open_tickets
        context['unassigned_count'] = unassigned_count
        context['recent_unassigned'] = recent_unassigned
        context['assigned_to_me_tickets'] = assigned_to_me_tickets
    
    # Admin specific context
    if active_role and active_role.name in ['ADMIN', 'SUPERADMIN']:
        context.update(_get_admin_dashboard_kpis())
    
    # Team Lead specific context
    if active_role and active_role.name == 'TEAM_LEAD':
        open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']
        # Drift-safe: role can be assigned via the legacy `role` field or the
        # newer M2M `roles` — checking only `role` silently drops an IT agent
        # from every metric on this dashboard if their role was reassigned
        # through the M2M system without the legacy field kept in sync.
        team_member_candidates = User.objects.filter(
            Q(role='AGENT') | Q(roles__name='AGENT'), department='IT', is_active=True,
        ).distinct()
        team_members = [u for u in team_member_candidates if effective_role_name(u) == 'AGENT']
        
        context['team_open_tickets'] = Ticket.objects.filter(
            status__in=open_statuses,
            assigned_to__in=team_members
        ).count()
        
        context['pending_reviews'] = Ticket.objects.filter(
            status=Ticket.Status.PENDING_MANAGER_REVIEW,
            requester__department=request.user.department
        ).count()
        
        context['unassigned_count'] = Ticket.objects.filter(
            assigned_to__isnull=True
        ).exclude(status__in=[
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
            Ticket.Status.PENDING_APPROVAL,
            Ticket.Status.PENDING_MANAGER_REVIEW,
            Ticket.Status.PENDING_FULFILLMENT,
        ]).count()
        
        # Includes unassigned tickets, not just ones already assigned to the
        # team — a breach sitting in the unassigned queue is still very much
        # "requires attention," and excluding it previously made this KPI
        # blind to breaches piling up in exactly the place they're most
        # likely to occur (tickets that haven't been picked up yet).
        context['sla_breaches'] = Ticket.objects.filter(
            Q(assigned_to__in=team_members) | Q(assigned_to__isnull=True),
            status__in=['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS'],
        ).filter(
            Q(response_due_at__lt=timezone.now()) | Q(resolution_due_at__lt=timezone.now())
        ).count()
        
        context['team_members'] = team_members
        
        # Workload distribution
        agent_workload = []
        for agent in team_members:
            open_count = Ticket.objects.filter(
                assigned_to=agent,
                status__in=open_statuses
            ).count()
            
            seven_days_ago = timezone.now() - timedelta(days=7)
            recent_resolved = Ticket.objects.filter(
                assigned_to=agent,
                status__in=['RESOLVED', 'CLOSED'],
                resolved_at__gte=seven_days_ago
            ).count()
            
            agent_workload.append({
                'agent': agent,
                'open_count': open_count,
                'recent_resolved': recent_resolved,
                'avatar': agent.avatar,
            })
        
        agent_workload.sort(key=lambda x: x['open_count'], reverse=True)
        context['agent_workload'] = agent_workload
        
        # Agent performance
        agent_performance = []
        for agent in team_members:
            resolved = Ticket.objects.filter(
                assigned_to=agent,
                status__in=['RESOLVED', 'CLOSED']
            )
            total_resolved = resolved.count()
            
            compliant = 0
            for ticket in resolved:
                if ticket.resolved_at and ticket.created_at:
                    try:
                        sla = SLA.objects.get(priority=ticket.priority)
                        resolution_time = (ticket.resolved_at - ticket.created_at).total_seconds() / 60
                        if resolution_time <= sla.resolution_minutes:
                            compliant += 1
                    except SLA.DoesNotExist:
                        compliant += 1
            
            # None (not 0) when there's nothing resolved yet — 0% reads as
            # "failing," which is indistinguishable from an agent who's
            # actually resolving tickets late. The template renders None as
            # a neutral "No data" instead of a red grade.
            compliance_rate = round((compliant / total_resolved * 100), 1) if total_resolved > 0 else None

            avg_resolution_time = None
            if total_resolved > 0:
                total_time = sum(
                    (t.resolved_at - t.created_at).total_seconds() / 3600
                    for t in resolved
                    if t.resolved_at and t.created_at
                )
                avg_resolution_time = round(total_time / total_resolved, 1)
            
            agent_performance.append({
                'agent': agent,
                'total_resolved': total_resolved,
                'compliance_rate': compliance_rate,
                'avg_resolution_time': avg_resolution_time,
            })

        # Agents with no resolved tickets (compliance_rate is None) sort to
        # the bottom rather than the top, which reverse=True on a bare None
        # comparison would otherwise raise/misorder.
        agent_performance.sort(key=lambda x: (x['compliance_rate'] is not None, x['compliance_rate'] or 0), reverse=True)
        context['agent_performance'] = agent_performance
        
        context['recent_team_tickets'] = Ticket.objects.filter(
            assigned_to__in=team_members
        ).exclude(status__in=['RESOLVED', 'CLOSED']).order_by('-created_at')[:5]
        
        context['recent_unassigned'] = Ticket.objects.filter(
            assigned_to__isnull=True
        ).exclude(status__in=[
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
            Ticket.Status.PENDING_APPROVAL,
            Ticket.Status.PENDING_MANAGER_REVIEW,
            Ticket.Status.PENDING_FULFILLMENT,
        ]).order_by('-created_at')[:5]
    
    # Add active role to context for sidebar
    context['active_role'] = active_role
    context['available_roles'] = user.roles.all().order_by('priority')
    context['sidebar_template'] = get_sidebar_template(user)
    
    return render(request, template, context)

def register(request):
    step = request.GET.get('step', '1')
    
    if request.method == 'POST':
        if step == '1':
            form = RegistrationStep1Form(request.POST)
            if form.is_valid():
                # Explicitly lowercase email
                email = form.cleaned_data['email'].lower()
                request.session['registration_data'] = {
                    'first_name': form.cleaned_data['first_name'],
                    'last_name': form.cleaned_data['last_name'],
                    'email': form.cleaned_data['email'],
                    'department': form.cleaned_data['department'],
                }
                return redirect(reverse('accounts:register') + '?step=2')
            else:
                return render(request, 'registration/register_step1.html', {'form': form})
        else:
            data = request.session.get('registration_data')
            if not data:
                return redirect('accounts:register')
            form = RegistrationStep2Form(request.POST)
            if form.is_valid():
                email = data.get('email', '').lower()   # extra safety
                user = User.objects.create_user(
                    email=email,
                    password=form.cleaned_data['password1'],
                    first_name=data.get('first_name'),
                    last_name=data.get('last_name'),
                    department=data.get('department'),
                    is_active=False,
                    email_verified=False
                )
                # Send verification email
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                verification_link = request.build_absolute_uri(
                    f'/accounts/verify/{uid}/{token}/'
                )
                subject = "Verify your email address"
                html_message = render_to_string('registration/verification_email.html', {
                    'user': user,
                    'link': verification_link,
                })
                plain_message = strip_tags(html_message)
                email_error = False
                try:
                    # ================================================================
                    # FIX: Use correct Brevo API signature
                    # ================================================================
                    success, result = send_email_via_brevo(
                        to_email=user.email,
                        subject=subject,
                        html_content=html_message,
                        from_email=settings.DEFAULT_FROM_EMAIL
                    )
                    if not success:
                        email_error = True
                        logger.error(f"Failed to send verification email to {user.email}: {result}")
                except Exception as e:
                    logger.error(f"Failed to send verification email to {user.email}: {str(e)}")
                    email_error = True

                request.session.pop('registration_data', None)
                return render(request, 'registration/register_done.html', {
                    'email_error': email_error,
                    'user_email': user.email,
                    'user_id': user.pk,
                    'verification_link': verification_link,
                    'show_dev_link': settings.DEBUG,
                })
            else:
                return render(request, 'registration/register_step2.html', {'form': form})
    
    # GET request – show current step
    if step == '1':
        # Pre‑fill with session data if it exists
        initial = request.session.get('registration_data', {})
        form = RegistrationStep1Form(initial=initial)
        return render(request, 'registration/register_step1.html', {'form': form})
    else:
        if not request.session.get('registration_data'):
            return redirect('accounts:register')
        return render(request, 'registration/register_step2.html', {'form': RegistrationStep2Form()})


def verify_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        # ================================================================
        # FIX: Only activate if user was not deactivated by admin
        # If admin deactivated the account, require admin to reactivate
        # ================================================================
        if user.is_active:
            # User is already active - just verify email
            user.email_verified = True
            user.save()
            return render(request, 'registration/verify_email_done.html')
        elif not user.is_active and not user.email_verified:
            # New user who hasn't verified email yet - activate
            user.is_active = True
            user.email_verified = True
            user.save()
            return render(request, 'registration/verify_email_done.html')
        else:
            # User was deactivated by admin - cannot self-activate
            return render(request, 'registration/verify_email_failed.html', {
                'error': 'This account has been deactivated by an administrator. Please contact support.'
            })
    else:
        return render(request, 'registration/verify_email_failed.html')


def resend_verification(request):
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        if not email:
            message = "Please enter your email address."
            success = False
            return render(request, 'registration/resend_verification_done.html', {
                'message': message,
                'success': success,
            })
        try:
            user = User.objects.get(email__iexact=email, is_active=False)
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            verification_link = request.build_absolute_uri(
                f'/accounts/verify/{uid}/{token}/'
            )
            subject = "Verify your email address"
            html_message = render_to_string('registration/verification_email.html', {
                'user': user,
                'link': verification_link,
            })
            plain_message = strip_tags(html_message)
            
            # ================================================================
            # FIX: Use correct Brevo API signature
            # ================================================================
            success, result = send_email_via_brevo(
                to_email=user.email,
                subject=subject,
                html_content=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL
            )
            if success:
                message = "Verification email sent. Please check your inbox."
                success = True
            else:
                message = f"Failed to send email: {result}"
                success = False
        except User.DoesNotExist:
            message = "No inactive user found with that email."
            success = False
        except Exception as e:
            logger.error(f"Resend verification error: {str(e)}")
            message = f"Failed to send email: {str(e)}"
            success = False
        return render(request, 'registration/resend_verification_done.html', {
            'message': message,
            'success': success,
        })
    return render(request, 'registration/resend_verification.html')

@login_required
def profile(request):
    # Ensure profile exists
    if not hasattr(request.user, 'profile'):
        UserProfile.objects.create(user=request.user)

    # Handle role switching from profile
    if request.method == 'POST' and 'switch_role' in request.POST:
        role_name = request.POST.get('role')
        if role_name:
            success = request.user.set_active_role(role_name)
            if success:
                messages.success(request, f'Switched to {request.user.get_active_role_display()} view.')
            else:
                messages.error(request, f'You do not have the {role_name} role.')
        return redirect('accounts:profile')

    # Always build unbound forms first so a failed validation on one of
    # them below (which re-renders this same view) never leaves the other
    # two - or itself, for save_settings/change_password - undefined.
    form = ProfileForm(instance=request.user)
    settings_form = UserSettingsForm(instance=request.user.profile)
    password_form = ChangePasswordForm(request.user)

    if request.method == 'POST':
        if 'save_profile' in request.POST:
            form = ProfileForm(request.POST, request.FILES, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('accounts:profile')
        elif 'delete_signature' in request.POST:
            if request.user.signature:
                request.user.signature.delete(save=False)
                request.user.signature = None
                request.user.save(update_fields=['signature'])
                messages.success(request, 'Signature removed.')
            return redirect('accounts:profile')
        elif 'save_settings' in request.POST:
            settings_form = UserSettingsForm(request.POST, instance=request.user.profile)
            if settings_form.is_valid():
                settings_form.save()
                messages.success(request, 'Settings updated successfully.')
                return redirect('accounts:profile')
        elif 'change_password' in request.POST:
            password_form = ChangePasswordForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Password changed successfully.')
                return redirect('accounts:profile')

    if not Role.objects.exists():
        default_roles = [
            ('SUPERADMIN', 'Super Admin', 1),
            ('ADMIN', 'Admin', 2),
            ('TEAM_LEAD', 'Team Lead', 3),
            ('AGENT', 'Support Team', 4),
            ('END_USER', 'User', 5),
        ]
        for name, display_name, priority in default_roles:
            Role.objects.get_or_create(name=name, defaults={'display_name': display_name, 'priority': priority})

    all_roles = Role.objects.all().order_by('priority')
    assigned_role_names = list(request.user.roles.values_list('name', flat=True))

    active_role = request.user.get_active_role()

    available_roles = list(request.user.roles.all().order_by('priority'))
    if not available_roles and active_role:
        available_roles = [active_role]
    elif not available_roles:
        highest_role = request.user.get_highest_role()
        if highest_role:
            available_roles = [highest_role]

    sidebar_template = get_sidebar_template(request.user)

    return render(request, 'dashboards/profile.html', {
        'form': form,
        'settings_form': settings_form,
        'password_form': password_form,
        'sidebar_template': sidebar_template,
        'available_roles': available_roles,
        'active_role': active_role,
    })


@login_required
def department_users_partial(request):
    """Return <option> tags for active users in the requested department.

    Used to drive a department-first "assign to a user" picker via HTMX:
    the caller re-renders this into an existing <select>'s innerHTML each
    time the paired department <select> changes.
    """
    # The paired department <select>'s field name varies by form
    # (`department` collides with real model fields on some forms, so
    # those use `assignee_department`/`recipient_department` instead) —
    # accept whichever one hx-include actually sent.
    department = (
        request.GET.get('department')
        or request.GET.get('assignee_department')
        or request.GET.get('recipient_department')
        or ''
    ).strip()
    exclude = request.GET.get('exclude', '').strip()

    if department:
        users = User.objects.filter(department=department, is_active=True).order_by('first_name', 'last_name')
        if exclude:
            exclude_ids = [pk for pk in exclude.split(',') if pk.isdigit()]
            if exclude_ids:
                users = users.exclude(pk__in=exclude_ids)
    else:
        users = User.objects.none()

    return render(request, 'accounts/partials/department_user_options.html', {'users': users})
