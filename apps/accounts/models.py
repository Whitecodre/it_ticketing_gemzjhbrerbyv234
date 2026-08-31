from datetime import timedelta
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.auth import password_validation
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone


# ================================================================
# ROLE MODEL - MUST BE DEFINED BEFORE USER
# ================================================================
class Role(models.Model):
    """Role model for user roles - supports multiple roles per user."""
    name = models.CharField(max_length=20, unique=True)
    display_name = models.CharField(max_length=50)
    priority = models.PositiveSmallIntegerField(default=5)  # 1=highest (SUPERADMIN)
    
    class Meta:
        ordering = ['priority']
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'
    
    def __str__(self):
        return self.display_name


class UserManager(BaseUserManager):
    """Custom manager where email is the unique identifier instead of username."""

    def _create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        email = email.lower()
        user = self.model(email=email, **extra_fields)
        # Enforce AUTH_PASSWORD_VALIDATORS here rather than only in
        # registration forms, so it can't be bypassed by any other code path
        # (admin, management commands, scripts) that creates a user directly.
        password_validation.validate_password(password, user)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', User.Role.SUPERADMIN)

        if extra_fields.get('is_staff') is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get('is_superuser') is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


# ================================================================
# USER MODEL
# ================================================================

class User(AbstractUser):
    username = None

    email = models.EmailField(_('email address'), unique=True)

    # Optional alternate login identifier — set by the user themselves from
    # their profile. When present, it can be used interchangeably with email
    # to log in (see apps.accounts.backends.EmailBackend).
    username = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        help_text=_('Optional. Lets you log in with a username instead of your email.'),
    )

    # ================================================================
    # KEEP EXISTING ROLE SYSTEM (Backward Compatible)
    # ================================================================
    class Role(models.TextChoices):
        SUPERADMIN = 'SUPERADMIN', _('Super Admin')
        ADMIN = 'ADMIN', _('Admin')
        TEAM_LEAD = 'TEAM_LEAD', _('Team Lead')
        AGENT = 'AGENT', _('Support Team')
        END_USER = 'END_USER', _('User')

    # PRIMARY ROLE - Kept for backward compatibility
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.END_USER,
    )

    # ================================================================
    # NEW: Multiple Roles (Many-to-Many) - For Dual Roles
    # ================================================================
    roles = models.ManyToManyField('Role', related_name='users', blank=True)
    
    # ================================================================
    # NEW: Active Role - Which role the user is currently using
    # ================================================================
    active_role = models.ForeignKey(
        'Role',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='active_users'
    )

    DEPARTMENT_CHOICES = [
        ('MARINE', 'Marine'),
        ('IT', 'IT'),
        ('ACCOUNTING', 'Accounting'),
        ('LEGAL', 'Legal'),
        ('QHSE', 'QHSE'),
        ('OPERATIONS', 'Operations'),
        ('PROJECT', 'Project'),
        ('VESSEL_CATERING', 'Vessel Catering'),
        ('PURCHASE_PROTOCOL', 'Purchase/Protocol'),
        ('FREIGHT', 'Freight'),
        ('STORE', 'Store'),
        ('HR', 'HR'),
        ('ADMIN', 'Admin'),
        ('COMMERCIAL', 'Commercial'),
    ]
    department = models.CharField(
        max_length=30,
        choices=DEPARTMENT_CHOICES,
        blank=False,
    )

    # apps/accounts/models.py - Add to User class

    def is_it_staff(self):
        """Check if user is in IT department and has a support role.
        Active-role aware (mirrors apps.common.permissions.effective_role_name, inlined here to
        avoid a models -> views-layer circular import) so a role-switched user is judged by their
        current active role, not a possibly-stale legacy `role` field."""
        if self.department != 'IT':
            return False
        active_role = self.get_active_role()
        role_name = active_role.name if active_role else self.role
        return role_name in [self.Role.AGENT, self.Role.TEAM_LEAD, self.Role.ADMIN, self.Role.SUPERADMIN]

    ONLINE_THRESHOLD = timedelta(minutes=5)

    def is_online(self):
        """True if last_seen falls within ONLINE_THRESHOLD of now AND the
        user hasn't explicitly logged out since. `has_active_session` is
        cleared by the user_logged_out signal (apps/accounts/signals.py) so
        the badge disappears immediately on logout instead of lingering for
        up to ONLINE_THRESHOLD — a silent session expiry (browser closed,
        no explicit logout) still self-corrects once last_seen goes stale,
        since LastSeenMiddleware stops updating it either way."""
        if not self.has_active_session or not self.last_seen:
            return False
        return timezone.now() - self.last_seen <= self.ONLINE_THRESHOLD

    def can_work_on_tickets(self):
        """Check if user can work on tickets (IT department + support role)."""
        return self.is_it_staff()

    def can_manage_display_documents(self):
        """Admin role or superuser: only these may create/edit/delete display documents & categories.
        Active-role aware (mirrors apps.common.permissions.effective_role_name, inlined here to
        avoid a models -> views-layer circular import) so a role-switched user is judged by their
        current active role, not a possibly-stale legacy `role` field."""
        active_role = self.get_active_role()
        role_name = active_role.name if active_role else self.role
        return self.is_superuser or role_name == self.Role.ADMIN

    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    signature = models.ImageField(upload_to='signatures/', blank=True, null=True)
    email_verified = models.BooleanField(default=False)
    # Updated (throttled) by LastSeenMiddleware on every authenticated
    # request — cheap presence signal, no WebSocket/Channels plumbing
    # needed. "Online" is derived as "seen within the last few minutes",
    # not stored directly.
    last_seen = models.DateTimeField(null=True, blank=True)
    # Set True on login, False on logout (see apps/accounts/signals.py) — lets
    # is_online() distinguish "explicitly logged out" from "just went briefly
    # inactive", so the online badge clears immediately on logout instead of
    # lingering for up to ONLINE_THRESHOLD.
    has_active_session = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users'
    )
    password_changed = models.BooleanField(default=False, help_text="Whether user has changed their password after first login")

    position = models.CharField(max_length=100, blank=True, help_text="Job title or position (e.g., Senior Developer, HR Manager)")

    # ================================================================
    # ORGANOGRAM / REPORTING LINE
    # ================================================================
    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        help_text="This user's manager/reporting line"
    )

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'department']

    def __str__(self):
        return f"{self.get_full_name()} ({self.role_names})"

    def get_full_name_with_role(self):
        """Return the full name plus the active role label."""
        role_label = self.get_active_role_display() or self.get_role_display()
        return f"{self.get_full_name()} ({role_label})"

    @property
    def role_names(self):
        """Return comma-separated list of role display names."""
        if not self.pk:
            return self.get_role_display()
        if self.roles.exists():
            return ', '.join([r.display_name for r in self.roles.all().order_by('priority')])
        return self.get_role_display()

    # ================================================================
    # DUAL ROLE METHODS (Check BOTH systems)
    # ================================================================
    
    def has_role(self, role_name):
        """Check if user has a specific role (checks both systems)."""
        if self.roles.filter(name=role_name).exists():
            return True
        return self.role == role_name

    def has_any_role(self, role_names):
        for role_name in role_names:
            if self.has_role(role_name):
                return True
        return False

    def get_highest_role(self):
        if self.roles.exists():
            return self.roles.order_by('priority').first()
        return self._get_legacy_role_object()

    def _get_legacy_role_object(self):
        role_map = {
            'SUPERADMIN': ('SUPERADMIN', 'Super Admin', 1),
            'ADMIN': ('ADMIN', 'Admin', 2),
            'TEAM_LEAD': ('TEAM_LEAD', 'Team Lead', 3),
            'AGENT': ('AGENT', 'Support Team', 4),
            'END_USER': ('END_USER', 'User', 5),
        }
        if self.role in role_map:
            name, display, priority = role_map[self.role]
            role, _ = Role.objects.get_or_create(
                name=name,
                defaults={'display_name': display, 'priority': priority}
            )
            return role
        return None
    
    def get_active_role_display(self):
        if self.active_role and self.roles.filter(id=self.active_role.id).exists():
            return self.active_role.display_name
        highest = self.get_highest_role()
        return highest.display_name if highest else 'No role'
    
    def get_active_role_name(self):
        if self.active_role and self.roles.filter(id=self.active_role.id).exists():
            return self.active_role.name
        highest = self.get_highest_role()
        return highest.name if highest else None
    
    def set_active_role(self, role_name):
        if not self.pk:
            return False
        try:
            role = self.roles.get(name=role_name)
            self.active_role = role
            self.active_role_id = role.id
            self.role = role.name
            self.save(update_fields=['active_role', 'active_role_id', 'role'])
            self._active_role_cache = role
            return True
        except Role.DoesNotExist:
            return False

    def get_active_role(self):
        # Memoized per-instance: a fresh User instance is fetched once per
        # request (by the auth middleware), so this avoids re-querying the
        # role on every one of the several places per request that call it
        # (context processor + view code both need it).
        if hasattr(self, '_active_role_cache'):
            return self._active_role_cache

        role = None
        if self.active_role_id:
            try:
                role = self.roles.get(pk=self.active_role_id)
                self.active_role = role
            except Role.DoesNotExist:
                role = None
        if role is None:
            if self.active_role and self.roles.filter(id=self.active_role.id).exists():
                role = self.active_role
            else:
                role = self.get_highest_role()
        self._active_role_cache = role
        return role
    
    def sync_roles(self):
        if not self.pk:
            return

        role_map = {
            'SUPERADMIN': ('SUPERADMIN', 'Super Admin', 1),
            'ADMIN': ('ADMIN', 'Admin', 2),
            'TEAM_LEAD': ('TEAM_LEAD', 'Team Lead', 3),
            'AGENT': ('AGENT', 'Support Team', 4),
            'END_USER': ('END_USER', 'User', 5),
        }

        if self.role in role_map and not self.roles.filter(name=role_map[self.role][0]).exists():
            name, display, priority = role_map[self.role]
            role, _ = Role.objects.get_or_create(
                name=name,
                defaults={'display_name': display, 'priority': priority}
            )
            self.roles.add(role)

        if self.roles.exists():
            if not self.active_role_id:
                highest_role = self.get_highest_role()
                if highest_role:
                    self.active_role = highest_role
                    self.active_role_id = highest_role.id
                    User.objects.filter(pk=self.pk).update(active_role=highest_role)

    def save(self, *args, **kwargs):
        if self.pk:
            try:
                old = User.objects.get(pk=self.pk)
                if old.avatar and old.avatar != self.avatar:
                    old.avatar.delete(save=False)
                if old.signature and old.signature != self.signature:
                    old.signature.delete(save=False)
            except User.DoesNotExist:
                pass

        if self.manager_id and self.pk:
            if self.manager_id == self.pk:
                raise ValueError("A user cannot be their own manager.")
            seen = {self.pk}
            current = self.manager
            while current is not None:
                if current.pk in seen:
                    raise ValueError("This manager assignment would create a cycle in the reporting line.")
                seen.add(current.pk)
                current = current.manager

        self.sync_roles()

        if self.role in [self.Role.SUPERADMIN, self.Role.ADMIN, self.Role.TEAM_LEAD, self.Role.AGENT]:
            self.is_staff = True
        else:
            self.is_staff = False
        self.is_superuser = (self.role == self.Role.SUPERADMIN)

        super().save(*args, **kwargs)


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    timezone = models.CharField(max_length=50, default='UTC')

    LANGUAGE_CHOICES = [
        ('en', _('English')),
        ('fr', _('French')),
        ('es', _('Spanish')),
        ('de', _('German')),
    ]
    language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default='en')
    
    DEFAULT_VIEW_CHOICES = [
        ('list', _('List')),
        ('kanban', _('Kanban')),
    ]
    default_ticket_view = models.CharField(max_length=20, choices=DEFAULT_VIEW_CHOICES, default='list')

    DOCUMENT_VIEW_CHOICES = [
        ('grid', 'Grid'),
        ('list', 'List'),
    ]
    default_document_view = models.CharField(
        max_length=10,
        choices=DOCUMENT_VIEW_CHOICES,
        default='grid',
        help_text="Default view for document lists"
    )
    
    email_notifications = models.BooleanField(default=True, help_text=_('Receive email notifications for ticket updates'))
    in_app_notifications = models.BooleanField(default=True, help_text=_('Receive in-app notifications (bell icon)'))
    
    ticket_signature = models.TextField(blank=True, help_text=_('Default signature for ticket replies (plain text)'))

    def __str__(self):
        return self.user.email


class ImpersonationLog(models.Model):
    """Audit log for impersonation events."""
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='impersonations_initiated')
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='impersonations_received')
    reason = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-started_at']
    
    def __str__(self):
        return f"{self.admin.email} → {self.target_user.email} at {self.started_at}"


class ImpersonationToken(models.Model):
    """One-time token for impersonation."""
    token = models.CharField(max_length=64, unique=True)
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='impersonation_tokens')
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='impersonation_tokens_received')
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.admin.email} → {self.target_user.email} ({self.token[:8]}...)"
    
    def is_valid(self):
        """Check if token is still valid."""
        if self.used_at:
            return False
        if timezone.now() > self.expires_at:
            return False
        return True
    
    def use(self):
        """Mark token as used."""
        self.used_at = timezone.now()
        self.save()


class LoginHistory(models.Model):
    """One row per successful login, recorded via the user_logged_in signal
    (apps/accounts/signals.py). Only starts accumulating from when this was
    added — there is no way to backfill logins that happened before it
    existed. Feeds the login-history table on the User Management detail
    page (apps.accounts.views.admin_users.admin_user_detail)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='login_history')
    logged_in_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    # Set once, at creation time, by the user_logged_in signal — True only
    # for a user's very first-ever login row (which, since an admin-created
    # account has no password until then, is effectively that user's
    # sign-up). Persisted rather than computed at render time so it stays
    # correct/cheap under pagination — the earliest row isn't always on the
    # page being displayed.
    is_first_login = models.BooleanField(default=False)

    class Meta:
        ordering = ['-logged_in_at']

    def __str__(self):
        return f'{self.user.email} at {self.logged_in_at}'

    @property
    def action_display(self):
        return 'Signed up' if self.is_first_login else 'Signed in'

    @property
    def friendly_device(self):
        """Collapses the raw User-Agent string into a 'Browser on OS' label
        (e.g. 'Chrome on Windows') for the login-history table — the raw
        string is long, unreadable to a non-technical admin, and was
        overflowing the table. Order matters: Edge/Opera UAs also contain
        'Chrome', and Chrome's UA also contains 'Safari', so the more
        specific checks must run first."""
        ua = (self.user_agent or '').lower()
        if not ua:
            return 'Unknown device'

        if 'edg/' in ua:
            browser = 'Edge'
        elif 'opr/' in ua or 'opera' in ua:
            browser = 'Opera'
        elif 'chrome' in ua or 'crios' in ua:
            browser = 'Chrome'
        elif 'firefox' in ua:
            browser = 'Firefox'
        elif 'safari' in ua:
            browser = 'Safari'
        else:
            browser = 'Unknown browser'

        if 'windows' in ua:
            os_name = 'Windows'
        elif 'iphone' in ua or 'ipad' in ua:
            # Must run before the macOS check — an iPhone/iPad UA string
            # also contains "like Mac OS X".
            os_name = 'iOS'
        elif 'mac os x' in ua or 'macintosh' in ua:
            os_name = 'macOS'
        elif 'android' in ua:
            os_name = 'Android'
        elif 'linux' in ua:
            os_name = 'Linux'
        else:
            os_name = 'Unknown OS'

        return f'{browser} on {os_name}'


class ClientSettings(models.Model):
    """Client company settings - logo, name, etc."""
    company_name = models.CharField(max_length=200, default='My Company')
    logo = models.ImageField(upload_to='client_logos/', blank=True, null=True)
    # Per-client org prefix used when auto-generating new Asset tracking_id
    # tags (e.g. "HD" -> "HD GF ACC MNT 008") — see Asset.save(). Blank means
    # the tag generator falls back to the old AST-{year}-{seq} scheme, so
    # this stays optional rather than forcing every client to set it.
    asset_tag_prefix = models.CharField(max_length=10, blank=True, default='')
    # The company's own initials (e.g. "HDG" for Hydrodive Group) —
    # deliberately separate from asset_tag_prefix (a different, shorter code
    # used only in asset tags, "HD" in Hydrodive's case). Prefixes every
    # exported report/document filename (see report_exporters._filename).
    # Blank means exported filenames simply have no prefix.
    company_initials = models.CharField(max_length=10, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name_plural = 'Client Settings'

    def __str__(self):
        return f"Client Settings - {self.company_name}"

    def save(self, *args, **kwargs):
        # Single-tenant today: every call site already reads/writes this via
        # id=1 (get_or_create(id=1) or .first()), so pin the pk to match —
        # closes off the one path (a stray .create() bypassing that
        # convention) that could silently spawn a second row and make
        # .first() start returning the wrong one. Revisit if/when this model
        # gains a real per-tenant scope for multi-tenancy.
        self.pk = 1
        super().save(*args, **kwargs)