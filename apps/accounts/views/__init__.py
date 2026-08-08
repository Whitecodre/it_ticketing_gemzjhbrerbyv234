import logging
from django.contrib import messages
from django.contrib.auth.views import PasswordResetView
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
from datetime import timedelta, date
from ..forms import ProfileForm, EmailAuthenticationForm, RegistrationStep1Form, RegistrationStep2Form, ChangePasswordForm, UserSettingsForm
from ..models import User, UserProfile, Role
from ..utils import validate_password_strength
from apps.tickets.models import Ticket, TicketActivityLog, SLA, BusinessCalendar, EscalationRule, Asset, RemoteConnector, TicketComment
from apps.tickets.views import get_sidebar_template
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect

User = get_user_model()
logger = logging.getLogger(__name__)

# @method_decorator(ratelimit(key='ip', rate='5/15m', method='POST', block=True), name='dispatch')
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
    
class CustomPasswordResetView(PasswordResetView):
    """
    Custom password reset view that uses Brevo API instead of send_mail.
    """
    template_name = 'registration/password_reset.html'
    email_template_name = 'registration/password_reset_email.html'
    subject_template_name = 'registration/password_reset_subject.txt'
    success_url = '/accounts/password-reset/done/'
    token_generator = default_token_generator
    
    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email, html_email_template_name=None):
        """
        Override the default send_mail to use Brevo API.
        """
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
            print(f"❌ Failed to send password reset email to {to_email}: {result}")
            # Log the error but don't fail silently
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Password reset email failed for {to_email}: {result}")
        
        return success


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

@login_required
def dashboard(request):
    user = request.user
    
    # ================================================================
    # DUAL ROLES: Get active role
    # ================================================================
    active_role = user.get_active_role()
    
    # If no active role, use the highest priority role
    if not active_role:
        active_role = user.roles.order_by('priority').first()
        if active_role:
            user.active_role = active_role
            user.save(update_fields=['active_role'])
    
    # Determine template based on active role
    if active_role:
        role_name = active_role.name
        template_map = {
            'SUPERADMIN': 'dashboards/super_admin_dashboard.html',
            'ADMIN': 'dashboards/admin_dashboard.html',
            'TEAM_LEAD': 'dashboards/team_lead_dashboard.html',
            'AGENT': 'dashboards/agent_dashboard.html',
            'END_USER': 'dashboards/end_user_dashboard.html',
        }
        template = template_map.get(role_name, 'dashboards/end_user_dashboard.html')
    else:
        # Fallback for users with no roles
        template = 'dashboards/end_user_dashboard.html'
    
    # ================================================================
    # Build context based on active role
    # ================================================================
    context = {}
    
    if active_role and active_role.name == 'END_USER':
        context['open_tickets_count'] = Ticket.objects.filter(
            requester=request.user,
            status__in=['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']
        ).count()
        context['recent_tickets'] = Ticket.objects.filter(requester=request.user).order_by('-created_at')[:5]
        context['all_count'] = Ticket.objects.filter(requester=request.user).count()
        context['open_count'] = Ticket.objects.filter(requester=request.user, status='NEW').count()
        context['in_progress_count'] = Ticket.objects.filter(requester=request.user, status='IN_PROGRESS').count()
        context['resolved_count'] = Ticket.objects.filter(requester=request.user, status='RESOLVED').count()
        context['closed_count'] = Ticket.objects.filter(requester=request.user, status='CLOSED').count()
        
    elif active_role and active_role.name in ['AGENT', 'TEAM_LEAD', 'ADMIN', 'SUPERADMIN']:
        open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']
        
        resolved_tickets = Ticket.objects.filter(
            assigned_to=request.user,
            status__in=['RESOLVED', 'CLOSED']
        )
        total_resolved = resolved_tickets.count()
        
        # Average Resolution Time
        avg_resolution_time = None
        resolution_times = []
        for ticket in resolved_tickets:
            if ticket.resolved_at and ticket.assigned_to == request.user:
                assigned_log = TicketActivityLog.objects.filter(
                    ticket=ticket,
                    action='assigned',
                    details__to=request.user.get_full_name()
                ).order_by('created_at').first()
                
                if assigned_log:
                    assigned_at = assigned_log.created_at
                    resolution_time = (ticket.resolved_at - assigned_at).total_seconds() / 3600
                    resolution_times.append(resolution_time)
        
        if resolution_times:
            avg_resolution_time = round(sum(resolution_times) / len(resolution_times), 1)
        
        # Average Response Time
        avg_response_time = None
        response_times = []
        for ticket in resolved_tickets:
            if ticket.resolved_at and ticket.assigned_to == request.user:
                assigned_log = TicketActivityLog.objects.filter(
                    ticket=ticket,
                    action='assigned',
                    details__to=request.user.get_full_name()
                ).order_by('created_at').first()
                
                if assigned_log:
                    assigned_at = assigned_log.created_at
                    first_reply = TicketComment.objects.filter(
                        ticket=ticket,
                        author=request.user,
                        visibility='PUBLIC'
                    ).order_by('created_at').first()
                    
                    if first_reply:
                        response_time = (first_reply.created_at - assigned_at).total_seconds() / 60
                        response_times.append(response_time)
        
        if response_times:
            avg_response_time = round(sum(response_times) / len(response_times), 1)
        
        my_open_tickets = Ticket.objects.filter(
            assigned_to=request.user,
            status__in=open_statuses
        ).count()
        
        unassigned_count = Ticket.objects.filter(
            assigned_to__isnull=True
        ).exclude(status__in=[
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
            Ticket.Status.PENDING_APPROVAL,
            Ticket.Status.PENDING_MANAGER_REVIEW,
            Ticket.Status.PENDING_FULFILLMENT,
        ]).count()
        
        recent_unassigned = Ticket.objects.filter(
            assigned_to__isnull=True
        ).exclude(status__in=[
            Ticket.Status.RESOLVED,
            Ticket.Status.CLOSED,
            Ticket.Status.PENDING_APPROVAL,
            Ticket.Status.PENDING_MANAGER_REVIEW,
            Ticket.Status.PENDING_FULFILLMENT,
        ]).order_by('-created_at')[:5]
        
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
        context['total_tickets_month'] = Ticket.objects.filter(created_at__month=timezone.now().month).count()

        resolved_tickets = Ticket.objects.filter(status__in=['RESOLVED', 'CLOSED'], resolved_at__isnull=False)
        compliant = 0
        total = 0
        for ticket in resolved_tickets:
            try:
                sla = SLA.objects.get(priority=ticket.priority)
                resolution_time = ticket.resolved_at - ticket.created_at
                if resolution_time.total_seconds() / 60 <= sla.resolution_minutes:
                    compliant += 1
            except SLA.DoesNotExist:
                pass
            total += 1
        context['sla_compliance'] = round((compliant / total * 100), 1) if total > 0 else 100.0

        context['connectors'] = RemoteConnector.objects.all().order_by('name')
        context['active_connectors'] = RemoteConnector.objects.filter(is_active=True).count()
        context['slas'] = SLA.objects.all().order_by('priority')
        context['escalation_rules'] = EscalationRule.objects.all().order_by('priority', 'timer_type', 'threshold_percent')
        context['calendars'] = BusinessCalendar.objects.all()
        context['recent_audit_logs'] = TicketActivityLog.objects.select_related('ticket', 'actor').order_by('-created_at')[:5]
        context['role_choices'] = User.Role.choices

        pending_fulfillment_count = Ticket.objects.filter(status=Ticket.Status.PENDING_FULFILLMENT).count()
        pending_fulfillment_requests = Ticket.objects.filter(
            status=Ticket.Status.PENDING_FULFILLMENT
        ).select_related('requester', 'category').order_by('-created_at')[:10]
        
        total_assets = Asset.objects.count()
        active_assets = Asset.objects.filter(status='ACTIVE').count()
        in_store_assets = Asset.objects.filter(status='IN_STORE').count()
        maintenance_assets = Asset.objects.filter(status='MAINTENANCE').count()
        damaged_assets = Asset.objects.filter(status='DAMAGED').count()
        scrapped_assets = Asset.objects.filter(status='SCRAPPED').count()
        
        thirty_days_ago = timezone.now() - timedelta(days=30)
        recently_added = Asset.objects.filter(created_at__gte=thirty_days_ago).count()
        assigned_assets = Asset.objects.filter(assigned_to__isnull=False).count()
        unassigned_assets = total_assets - assigned_assets
        
        today = date.today()
        ninety_days_later = today + timedelta(days=90)
        expiring_warranty = Asset.objects.filter(
            warranty_expiry__gte=today,
            warranty_expiry__lte=ninety_days_later,
            status='ACTIVE'
        ).count()
        
        approved_requests = Ticket.objects.filter(
            type=Ticket.Type.SERVICE_REQUEST,
            status=Ticket.Status.APPROVED
        ).count()
        
        fulfilled_this_month = Ticket.objects.filter(
            type=Ticket.Type.SERVICE_REQUEST,
            is_asset_request=True,
            fulfilled_at__month=timezone.now().month
        ).count()
        
        context.update({
            'pending_fulfillment_count': pending_fulfillment_count,
            'pending_fulfillment_requests': pending_fulfillment_requests,
            'total_assets': total_assets,
            'active_assets': active_assets,
            'in_store_assets': in_store_assets,
            'maintenance_assets': maintenance_assets,
            'damaged_assets': damaged_assets,
            'scrapped_assets': scrapped_assets,
            'recently_added': recently_added,
            'assigned_assets': assigned_assets,
            'unassigned_assets': unassigned_assets,
            'expiring_warranty': expiring_warranty,
            'approved_requests': approved_requests,
            'fulfilled_this_month': fulfilled_this_month,
        })
    
    # Team Lead specific context
    if active_role and active_role.name == 'TEAM_LEAD':
        open_statuses = ['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_USER', 'PENDING_VENDOR']
        team_members = User.objects.filter(department=request.user.department, role='AGENT', is_active=True)
        
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
        
        context['sla_breaches'] = Ticket.objects.filter(
            assigned_to__in=team_members,
            status__in=['NEW', 'TRIAGED', 'ASSIGNED', 'IN_PROGRESS']
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
            
            compliance_rate = round((compliant / total_resolved * 100), 1) if total_resolved > 0 else 0
            
            avg_response_time = 0
            if total_resolved > 0:
                total_time = sum(
                    (t.resolved_at - t.created_at).total_seconds() / 3600 
                    for t in resolved 
                    if t.resolved_at and t.created_at
                )
                avg_response_time = round(total_time / total_resolved, 1) if total_resolved > 0 else 0
            
            agent_performance.append({
                'agent': agent,
                'total_resolved': total_resolved,
                'compliance_rate': compliance_rate,
                'avg_response_time': avg_response_time,
            })
        
        agent_performance.sort(key=lambda x: x['compliance_rate'], reverse=True)
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
                        print(f"❌ Failed to send verification email to {user.email}: {result}")
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

    if request.method == 'POST':
        if 'save_profile' in request.POST:
            form = ProfileForm(request.POST, request.FILES, instance=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully.')
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
    else:
        form = ProfileForm(instance=request.user)
        settings_form = UserSettingsForm(instance=request.user.profile)
        password_form = ChangePasswordForm(request.user)

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
    active_role_name = active_role.name if active_role else request.user.role

    available_roles = list(request.user.roles.all().order_by('priority'))
    if not available_roles and active_role:
        available_roles = [active_role]
    elif not available_roles:
        highest_role = request.user.get_highest_role()
        if highest_role:
            available_roles = [highest_role]

     # Debug: Print active role info
    print(f"Profile view - User: {request.user.email}")
    print(f"Profile view - Active role: {request.user.active_role}")
    print(f"Profile view - Active role name: {request.user.get_active_role_name()}")
    print(f"Profile view - All roles: {[r.name for r in request.user.roles.all()]}")

    sidebar_map = {
        'END_USER': 'partials/sidebar_end_user.html',
        'AGENT': 'partials/sidebar_agent.html',
        'TEAM_LEAD': 'partials/sidebar_team_lead.html',
        'ADMIN': 'partials/sidebar_admin.html',
        'SUPERADMIN': 'partials/sidebar_superadmin.html',
    }
    sidebar_template = sidebar_map.get(active_role_name, 'partials/sidebar_generic.html')

    return render(request, 'dashboards/profile.html', {
        'form': form,
        'settings_form': settings_form,
        'password_form': password_form,
        'sidebar_template': sidebar_template,
        'available_roles': available_roles,
        'active_role': active_role,
    })
