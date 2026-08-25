from datetime import timedelta

from django.test import TestCase, Client, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.urls import reverse
from django.utils import timezone
from django.core import mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str

from apps.accounts.admin import UserAdmin
from apps.accounts.models import ImpersonationToken, Role
from apps.common.context_processors import impersonation_context

User = get_user_model()


class UserModelTests(TestCase):
    """Test User model functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT',
            role=User.Role.END_USER
        )

    def test_user_creation(self):
        """Test basic user creation."""
        self.assertEqual(self.user.email, 'test@example.com')
        self.assertEqual(self.user.get_full_name(), 'Test User')
        self.assertTrue(self.user.check_password('TestPass123!'))
        self.assertEqual(self.user.role, User.Role.END_USER)

    def test_user_creation_with_email_normalization(self):
        """Test email is normalized (lowercased)."""
        user = User.objects.create_user(
            email='OTHER@EXAMPLE.COM',
            password='TestPass123!',
            first_name='Other',
            last_name='User',
            department='IT'
        )
        self.assertEqual(user.email, 'other@example.com')

    def test_user_get_full_name_with_role(self):
        """Test get_full_name_with_role method."""
        result = self.user.get_full_name_with_role()
        self.assertEqual(result, 'Test User (User)')

    def test_user_superuser_creation(self):
        """Test superuser creation."""
        admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT'
        )
        self.assertTrue(admin.is_superuser)
        self.assertTrue(admin.is_staff)
        self.assertEqual(admin.role, User.Role.SUPERADMIN)

    def test_user_role_auto_sets_staff(self):
        """Test that certain roles auto-set is_staff."""
        roles_with_staff = [
            User.Role.SUPERADMIN,
            User.Role.ADMIN,
            User.Role.TEAM_LEAD,
            User.Role.AGENT
        ]
        for role in roles_with_staff:
            user = User.objects.create_user(
                email=f'{role}@example.com',
                password='TestPass123!',
                first_name='Test',
                last_name='User',
                department='IT',
                role=role
            )
            self.assertTrue(user.is_staff)

    def test_user_end_user_not_staff(self):
        """Test that END_USER role does not set is_staff."""
        user = User.objects.create_user(
            email='enduser@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT',
            role=User.Role.END_USER
        )
        self.assertFalse(user.is_staff)


class AdminRoleAssignmentTests(TestCase):
    """Test that Django admin exposes the dual-role fields for user assignment."""

    def test_admin_form_exposes_roles_and_active_role_fields(self):
        admin = UserAdmin(User, AdminSite())
        form_class = admin.get_form(None)

        self.assertIn('roles', form_class.base_fields)
        self.assertIn('active_role', form_class.base_fields)


class TemplateRoleSwitchTests(TestCase):
    """Test that the profile UI supports switching the active role."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='template-role@example.com',
            password='TestPass123!',
            first_name='Template',
            last_name='User',
            department='IT',
            role=User.Role.END_USER,
        )
        self.client = Client()
        self.client.login(email='template-role@example.com', password='TestPass123!')

    def test_profile_page_shows_role_switch_controls_when_user_has_multiple_roles(self):
        agent_role = Role.objects.create(name='AGENT', display_name='Support Team', priority=4)
        team_lead_role = Role.objects.create(name='TEAM_LEAD', display_name='Team Lead', priority=3)
        self.user.roles.add(agent_role, team_lead_role)
        self.user.active_role = agent_role
        self.user.save(update_fields=['active_role'])

        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        # The role-switch form posts to the dedicated switch_role view
        # (not back to profile itself) using a 'role' radio input.
        self.assertContains(response, 'id="roleSwitchForm"')
        self.assertContains(response, 'name="role"')
        self.assertContains(response, 'Switch Role')
        self.assertContains(response, 'Support Team')
        self.assertContains(response, 'Team Lead')
        self.assertNotContains(response, 'name="manage_roles"')

    def test_profile_post_can_switch_active_role(self):
        agent_role = Role.objects.create(name='AGENT', display_name='Support Team', priority=4)
        team_lead_role = Role.objects.create(name='TEAM_LEAD', display_name='Team Lead', priority=3)
        self.user.roles.add(agent_role, team_lead_role)
        self.user.active_role = agent_role
        self.user.save(update_fields=['active_role'])

        response = self.client.post(reverse('accounts:profile'), {
            'switch_role': '1',
            'role': 'TEAM_LEAD',
        })

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_active_role().name, 'TEAM_LEAD')
        self.assertEqual(self.user.role, 'TEAM_LEAD')


class DualRoleTests(TestCase):
    """Test dual-role switching and active role behavior."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='dual@example.com',
            password='TestPass123!',
            first_name='Dual',
            last_name='User',
            department='IT',
            role=User.Role.END_USER
        )
        self.client.login(email='dual@example.com', password='TestPass123!')

    def test_role_switch_updates_active_role(self):
        """Switching roles should update the active role used by the UI."""
        agent_role = Role.objects.create(name='AGENT', display_name='Support Team', priority=4)
        team_lead_role = Role.objects.create(name='TEAM_LEAD', display_name='Team Lead', priority=3)
        self.user.roles.add(agent_role, team_lead_role)
        self.user.active_role = agent_role
        self.user.save(update_fields=['active_role'])

        response = self.client.post(reverse('accounts:profile'), {
            'switch_role': '1',
            'role': 'TEAM_LEAD',
        })

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.get_active_role().name, 'TEAM_LEAD')
        self.assertEqual(self.user.get_active_role_display(), 'Team Lead')


class RegistrationTests(TestCase):
    """Self-registration is intentionally disabled (apps/accounts/urls.py
    routes 'accounts:register' to `registration_disabled`, a permanent
    404) - accounts are created by admins via admin_user_create instead.
    This just guards that the route stays turned off; it isn't testing a
    live signup flow."""

    def setUp(self):
        self.client = Client()
        self.register_url = reverse('accounts:register')

    def test_registration_is_disabled(self):
        response = self.client.get(self.register_url)
        self.assertEqual(response.status_code, 404)


class LoginTests(TestCase):
    """Test login functionality."""

    def setUp(self):
        self.client = Client()
        self.login_url = reverse('accounts:login')
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT',
            is_active=True,
            email_verified=True,
            password_changed=True,
        )

    def test_login_page_loads(self):
        """Test login page loads successfully."""
        response = self.client.get(self.login_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_login_success(self):
        """Test successful login."""
        response = self.client.post(self.login_url, {
            'username': 'test@example.com',
            'password': 'TestPass123!'
        })
        self.assertRedirects(response, reverse('dashboard'))

    def test_login_failure_wrong_password(self):
        """Test login with wrong password."""
        response = self.client.post(self.login_url, {
            'username': 'test@example.com',
            'password': 'WrongPass123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a correct email/username and password')

    def test_login_failure_nonexistent_user(self):
        """Test login with nonexistent user."""
        response = self.client.post(self.login_url, {
            'username': 'nonexistent@example.com',
            'password': 'TestPass123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please enter a correct email/username and password')

    def test_login_inactive_user(self):
        """Test login with inactive user."""
        self.user.is_active = False
        self.user.save()

        response = self.client.post(self.login_url, {
            'username': 'test@example.com',
            'password': 'TestPass123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'account has been deactivated')

    def test_login_unverified_email(self):
        """Test login with unverified email."""
        # Unverified users should be redirected to verification page
        self.user.email_verified = False
        self.user.save()

        response = self.client.post(self.login_url, {
            'username': 'test@example.com',
            'password': 'TestPass123!'
        })
        # Should redirect to verification page or show message
        self.assertNotEqual(response.status_code, 200)
        # It might redirect to login page with error or to verification page

    def test_login_remember_me(self):
        """Test remember me functionality."""
        response = self.client.post(self.login_url, {
            'username': 'test@example.com',
            'password': 'TestPass123!',
            'remember_me': 'on'
        })
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(self.client.session.get_expiry_age(), 30 * 24 * 60 * 60)

    def test_login_without_remember_me(self):
        """Test login without remember me."""
        response = self.client.post(self.login_url, {
            'username': 'test@example.com',
            'password': 'TestPass123!'
        })
        self.assertRedirects(response, reverse('dashboard'))
        # Session should expire on browser close (0) or default
        self.assertIn(self.client.session.get_expiry_age(), [0, 86400])

    def test_impersonation_context_is_populated_from_session(self):
        """Impersonation context should be available from the session so the banner can render."""
        request = RequestFactory().get('/')
        request.session = self.client.session
        request.session['impersonate'] = {
            'original_user_id': 1,
            'original_user_email': 'admin@example.com',
            'target_user_id': 2,
            'target_user_email': 'target@example.com',
            'reason': 'Support review',
            'starts_at': timezone.now().isoformat(),
            'expires_at': (timezone.now() + timedelta(hours=1)).isoformat(),
        }
        request.session.save()

        context = impersonation_context(request)

        self.assertTrue(context['is_impersonating'])
        self.assertEqual(context['impersonation_target'], 'target@example.com')
        self.assertEqual(context['impersonation_reason'], 'Support review')
        self.assertEqual(context['impersonation_original'], 'admin@example.com')

    def test_impersonation_token_login_redirects_to_dashboard(self):
        """Impersonation should log the target user in and redirect to the dashboard."""
        admin = User.objects.create_superuser(
            email='admin-impersonate@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT',
        )
        target = User.objects.create_user(
            email='target-user@example.com',
            password='TestPass123!',
            first_name='Target',
            last_name='User',
            department='IT',
            is_active=True,
            email_verified=True,
            role=User.Role.END_USER,
        )
        token = ImpersonationToken.objects.create(
            token='impersonation-test-token',
            admin=admin,
            target_user=target,
            reason='Support check',
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.get(
            reverse('accounts:impersonate_token', args=[token.token]),
            follow=True,
        )

        self.assertRedirects(response, reverse('dashboard'))
        self.assertTrue(response.wsgi_request.user.is_authenticated)
        self.assertEqual(response.wsgi_request.user.pk, target.pk)


class PasswordResetTests(TestCase):
    """Test password reset flow."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT',
            is_active=True,
            email_verified=True
        )
        self.reset_url = reverse('accounts:password_reset')

    def test_password_reset_page_loads(self):
        """Test password reset page loads."""
        response = self.client.get(self.reset_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/password_reset.html')

    def test_password_reset_request_valid_email(self):
        """Test password reset request with valid email."""
        response = self.client.post(self.reset_url, {'email': 'test@example.com'})
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('password reset', mail.outbox[0].subject.lower())

    def test_password_reset_request_invalid_email(self):
        """Test password reset request with invalid email."""
        response = self.client.post(self.reset_url, {'email': 'nonexistent@example.com'})
        self.assertRedirects(response, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_confirm_valid(self):
        """Test password reset confirmation with valid token."""
        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        # Django's PasswordResetConfirmView 302s the one-time token URL to a
        # session-backed '.../set-password/' URL before rendering the form,
        # so it can't leak the token via the Referer header - follow that.
        response = self.client.get(
            reverse('accounts:password_reset_confirm', args=[uid, token]),
            follow=True,
        )
        # Should show the reset form
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/password_reset_confirm.html')

    def test_password_reset_confirm_invalid_token(self):
        """Test password reset confirmation with invalid token."""
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(
            reverse('accounts:password_reset_confirm', args=[uid, 'invalid-token'])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'invalid or has expired')

    def test_password_reset_complete(self):
        """Test password reset complete flow."""
        token = default_token_generator.make_token(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        # First hit the one-time token URL so Django validates it and swaps
        # in the session-backed 'set-password' URL - the form must be
        # posted there, not back to the (now-consumed) token URL.
        get_response = self.client.get(
            reverse('accounts:password_reset_confirm', args=[uid, token]),
            follow=True,
        )
        set_password_url = get_response.redirect_chain[-1][0]

        response = self.client.post(
            set_password_url,
            {
                'new_password1': 'NewStrongPass123!',
                'new_password2': 'NewStrongPass123!'
            }
        )
        # Should redirect to complete page
        self.assertRedirects(response, reverse('accounts:password_reset_complete'))

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPass123!'))


class ProfileTests(TestCase):
    """Test user profile functionality."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT',
            is_active=True,
            email_verified=True
        )
        self.client.login(email='test@example.com', password='TestPass123!')
        self.profile_url = reverse('accounts:profile')

    def test_profile_page_loads(self):
        """Test profile page loads for authenticated user."""
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboards/profile.html')

    def test_profile_update(self):
        """Test updating profile information."""
        response = self.client.post(self.profile_url, {
            'save_profile': '1',
            'first_name': 'Updated',
            'last_name': 'Name',
            'department': 'IT'
        })
        self.assertRedirects(response, self.profile_url)

        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Updated')
        self.assertEqual(self.user.last_name, 'Name')

    def test_profile_signature_upload(self):
        """Signature upload mirrors the avatar pattern — used on report
        sign-off lines when present (see apps.tickets.report_registry)."""
        import base64
        from django.core.files.uploadedfile import SimpleUploadedFile

        png_bytes = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        )
        response = self.client.post(self.profile_url, {
            'save_profile': '1',
            'first_name': 'Test',
            'last_name': 'User',
            'signature': SimpleUploadedFile('sig.png', png_bytes, content_type='image/png'),
        })
        self.assertRedirects(response, self.profile_url)

        self.user.refresh_from_db()
        self.assertTrue(bool(self.user.signature))

    def test_password_change_valid(self):
        """Test changing password with valid data."""
        response = self.client.post(self.profile_url, {
            'change_password': '1',
            'old_password': 'TestPass123!',
            'new_password1': 'NewStrongPass123!',
            'new_password2': 'NewStrongPass123!'
        })
        self.assertRedirects(response, self.profile_url)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewStrongPass123!'))

    def test_password_change_invalid_old(self):
        """Test changing password with invalid old password."""
        response = self.client.post(self.profile_url, {
            'change_password': '1',
            'old_password': 'WrongPass123!',
            'new_password1': 'NewStrongPass123!',
            'new_password2': 'NewStrongPass123!'
        })
        # Form errors, stays on page
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'was entered incorrectly')

    def test_password_change_mismatch(self):
        """Test changing password with mismatched new passwords."""
        response = self.client.post(self.profile_url, {
            'change_password': '1',
            'old_password': 'TestPass123!',
            'new_password1': 'NewStrongPass123!',
            'new_password2': 'DifferentPass123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'two password fields')


class AdminUserManagementTests(TestCase):
    """Test admin user management functionality."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT'
        )
        self.client.login(email='admin@example.com', password='AdminPass123!')
        self.admin_users_url = reverse('accounts:admin_users')

    def test_admin_users_page_loads(self):
        """Test admin user management page loads."""
        response = self.client.get(self.admin_users_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'admin/user_management.html')

    def test_admin_create_user(self):
        """Test admin creating a new user."""
        response = self.client.post(
            reverse('accounts:admin_user_create'),
            {
                'email': 'newuser@example.com',
                'password': 'NewUser123!',
                'first_name': 'New',
                'last_name': 'User',
                'role': 'AGENT',
                'department': 'IT'
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(email='newuser@example.com').exists())

    def test_admin_create_user_duplicate_email(self):
        """Test admin creating user with duplicate email."""
        User.objects.create_user(
            email='existing@example.com',
            password='TestPass123!',
            first_name='Existing',
            last_name='User',
            department='IT'
        )
        response = self.client.post(
            reverse('accounts:admin_user_create'),
            {
                'email': 'existing@example.com',
                'password': 'NewUser123!',
                'first_name': 'New',
                'last_name': 'User',
                'role': 'AGENT',
                'department': 'IT'
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_edit_user(self):
        """Test admin editing a user."""
        user = User.objects.create_user(
            email='edit@example.com',
            password='TestPass123!',
            first_name='Old',
            last_name='Name',
            department='IT'
        )
        response = self.client.post(
            reverse('accounts:admin_user_edit', args=[user.pk]),
            {
                'first_name': 'New',
                'last_name': 'Name',
                'role': 'AGENT',
                'department': 'IT',
                'is_active': 'true'
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'New')

    def test_admin_edit_user_assigns_multiple_roles(self):
        """Test admin editing a user with multiple assigned roles."""
        agent_role = Role.objects.create(name='AGENT', display_name='Support Team', priority=4)
        team_lead_role = Role.objects.create(name='TEAM_LEAD', display_name='Team Lead', priority=3)
        user = User.objects.create_user(
            email='multi@example.com',
            password='TestPass123!',
            first_name='Multi',
            last_name='Role',
            department='IT'
        )
        response = self.client.post(
            reverse('accounts:admin_user_edit', args=[user.pk]),
            {
                'first_name': 'Multi',
                'last_name': 'Role',
                'role': 'AGENT',
                'department': 'IT',
                'is_active': 'true',
                'selected_roles': ['AGENT', 'TEAM_LEAD'],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.roles.filter(name='AGENT').exists())
        self.assertTrue(user.roles.filter(name='TEAM_LEAD').exists())
        # The primary 'role' dropdown value is what becomes active - there's
        # no UI/backend support for picking a different one of the assigned
        # roles as active at assignment time (see admin_user_edit).
        self.assertEqual(user.get_active_role().name, 'AGENT')

    def test_admin_toggle_user_active(self):
        """Test admin toggling user active status."""
        user = User.objects.create_user(
            email='toggle@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT'
        )
        response = self.client.post(
            reverse('accounts:admin_user_toggle_active', args=[user.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_admin_cannot_deactivate_self(self):
        """Test admin cannot deactivate their own account."""
        response = self.client.post(
            reverse('accounts:admin_user_toggle_active', args=[self.admin.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_change_password(self):
        """Test admin changing user password."""
        user = User.objects.create_user(
            email='passchange@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT'
        )
        response = self.client.post(
            reverse('accounts:admin_user_change_password', args=[user.pk]),
            {'password': 'NewStrongPass123!'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewStrongPass123!'))

    def test_admin_user_create_keeps_role_and_active_role_in_sync(self):
        """admin_user_create sets `role` and `active_role` together
        explicitly (matching the self-service switcher's invariant), and
        User.save()'s sync_roles() self-heals the Role/roles M2M on every
        save regardless — confirm both end up consistent for a freshly
        admin-created user even when no Role row existed beforehand."""
        Role.objects.filter(name='TEAM_LEAD').delete()
        response = self.client.post(reverse('accounts:admin_user_create'), {
            'email': 'syncedrole@example.com',
            'first_name': 'Synced',
            'last_name': 'Role',
            'department': 'IT',
            'role': 'TEAM_LEAD',
        })
        self.assertEqual(response.status_code, 200)
        created = User.objects.get(email='syncedrole@example.com')
        self.assertEqual(created.role, 'TEAM_LEAD')
        self.assertIsNotNone(created.active_role)
        self.assertEqual(created.active_role.name, created.role)

    def test_admin_user_edit_keeps_role_and_active_role_in_sync(self):
        user = User.objects.create_user(
            email='editme@example.com', password='TestPass123!',
            first_name='Edit', last_name='Me', department='IT',
            role=User.Role.END_USER, is_active=True,
        )
        response = self.client.post(reverse('accounts:admin_user_edit', args=[user.pk]), {
            'first_name': 'Edit', 'last_name': 'Me', 'department': 'IT',
            'is_active': 'true', 'role': 'AGENT',
        })
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.role, 'AGENT')
        self.assertIsNotNone(user.active_role)
        self.assertEqual(user.active_role.name, user.role)


class TeamLeadAnyDepartmentTests(TestCase):
    """TEAM_LEAD is a departmental approval gate and must be assignable in
    any department, while AGENT/ADMIN/SUPERADMIN stay IT-only."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            email='superadmin@example.com',
            password='AdminPass123!',
            first_name='Super',
            last_name='Admin',
            department='IT'
        )
        self.client.login(email='superadmin@example.com', password='AdminPass123!')

    def test_create_team_lead_outside_it_succeeds(self):
        response = self.client.post(
            reverse('accounts:admin_user_create'),
            {
                'email': 'marinelead@example.com',
                'first_name': 'Marine',
                'last_name': 'Lead',
                'role': 'TEAM_LEAD',
                'department': 'MARINE',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='marinelead@example.com')
        self.assertEqual(user.role, 'TEAM_LEAD')
        self.assertEqual(user.department, 'MARINE')

    def test_create_agent_outside_it_fails(self):
        response = self.client.post(
            reverse('accounts:admin_user_create'),
            {
                'email': 'marineagent@example.com',
                'first_name': 'Marine',
                'last_name': 'Agent',
                'role': 'AGENT',
                'department': 'MARINE',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='marineagent@example.com').exists())

    def test_create_admin_outside_it_fails(self):
        response = self.client.post(
            reverse('accounts:admin_user_create'),
            {
                'email': 'marineadmin@example.com',
                'first_name': 'Marine',
                'last_name': 'Admin',
                'role': 'ADMIN',
                'department': 'MARINE',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='marineadmin@example.com').exists())

    def test_edit_team_lead_outside_it_succeeds(self):
        user = User.objects.create_user(
            email='accountsuser@example.com', password='TestPass123!',
            first_name='Accounts', last_name='User', department='ACCOUNTING',
        )
        response = self.client.post(
            reverse('accounts:admin_user_edit', args=[user.pk]),
            {
                'first_name': 'Accounts', 'last_name': 'User',
                'role': 'TEAM_LEAD', 'department': 'ACCOUNTING', 'is_active': 'true',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.role, 'TEAM_LEAD')

    def test_selected_roles_agent_outside_it_fails(self):
        Role.objects.get_or_create(name='AGENT', defaults={'display_name': 'Support Team', 'priority': 4})
        response = self.client.post(
            reverse('accounts:admin_user_create'),
            {
                'email': 'marinemulti@example.com',
                'first_name': 'Marine',
                'last_name': 'Multi',
                'role': 'TEAM_LEAD',
                'department': 'MARINE',
                'selected_roles': ['TEAM_LEAD', 'AGENT'],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email='marinemulti@example.com').exists())


class SuperadminHiddenTests(TestCase):
    """SUPERADMIN is a vendor/support-only role and must stay invisible to
    and ungrantable by ordinary tenant Admins."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            email='plainadmin@example.com',
            password='AdminPass123!',
            first_name='Plain',
            last_name='Admin',
            department='IT',
            role=User.Role.ADMIN,
            is_active=True,
            email_verified=True,
        )
        self.client.login(email='plainadmin@example.com', password='AdminPass123!')

    def test_non_superadmin_cannot_grant_superadmin_via_selected_roles(self):
        Role.objects.get_or_create(name='SUPERADMIN', defaults={'display_name': 'Super Admin', 'priority': 1})
        target = User.objects.create_user(
            email='target@example.com', password='TestPass123!',
            first_name='Target', last_name='User', department='IT',
        )
        response = self.client.post(
            reverse('accounts:admin_user_edit', args=[target.pk]),
            {
                'first_name': 'Target', 'last_name': 'User',
                'role': 'AGENT', 'department': 'IT', 'is_active': 'true',
                'selected_roles': ['AGENT', 'SUPERADMIN'],
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertFalse(target.roles.filter(name='SUPERADMIN').exists())

    def test_admin_user_list_hides_superadmin_from_non_superadmin(self):
        User.objects.create_superuser(
            email='vendor@example.com', password='VendorPass123!',
            first_name='Vendor', last_name='Support', department='IT',
        )
        response = self.client.get(reverse('accounts:admin_users'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('SUPERADMIN', response.content.decode())
        self.assertNotIn('Super Admin', response.content.decode())

    def test_django_admin_queryset_excludes_superadmin_for_non_superadmin(self):
        User.objects.create_superuser(
            email='vendor2@example.com', password='VendorPass123!',
            first_name='Vendor', last_name='Two', department='IT',
        )
        request = RequestFactory().get('/admin/accounts/user/')
        request.user = self.admin
        admin = UserAdmin(User, AdminSite())
        qs = admin.get_queryset(request)
        self.assertFalse(qs.filter(role=User.Role.SUPERADMIN).exists())

    def test_django_admin_form_strips_superadmin_choice_for_non_superadmin(self):
        request = RequestFactory().get('/admin/accounts/user/add/')
        request.user = self.admin
        admin = UserAdmin(User, AdminSite())
        form_class = admin.get_form(request)
        role_values = [choice[0] for choice in form_class.base_fields['role'].choices]
        self.assertNotIn('SUPERADMIN', role_values)


class DashboardRemoteSessionBannerRoleScopingTests(TestCase):
    """The dashboard's remote-session 'action needed' banner should only
    show the pending item matching the currently active role — a dual-role
    account (Agent + End User) with one pending item on each side shouldn't
    see both prompts regardless of which hat is on."""

    def setUp(self):
        from apps.tickets.models import Ticket, RemoteSession, RemoteConnector
        from apps.common.models import Category

        self.RemoteSession = RemoteSession

        self.user = User.objects.create_user(
            email='dashbanner@example.com', password='TestPass123!',
            first_name='Dash', last_name='Banner', department='IT',
            role=User.Role.END_USER, is_active=True, email_verified=True,
        )
        agent_role, _ = Role.objects.get_or_create(
            name='AGENT', defaults={'display_name': 'Support Team', 'priority': 4}
        )
        end_user_role, _ = Role.objects.get_or_create(
            name='END_USER', defaults={'display_name': 'User', 'priority': 5}
        )
        self.user.roles.add(agent_role, end_user_role)

        self.other_agent = User.objects.create_user(
            email='otheragent-db@example.com', password='TestPass123!',
            first_name='Other', last_name='Agent', department='IT',
            role=User.Role.AGENT, is_active=True, email_verified=True,
        )
        self.other_requester = User.objects.create_user(
            email='otherreq-db@example.com', password='TestPass123!',
            first_name='Other', last_name='Requester', department='IT',
            is_active=True, email_verified=True,
        )
        category = Category.objects.create(name='Hardware', slug='dashboard-banner-hw')
        connector = RemoteConnector.objects.create(name='Quick Assist DB', is_active=True)

        ticket_a = Ticket.objects.create(
            number='TK#DB1', title='Requester side', description='d',
            requester=self.user, category=category, status=Ticket.Status.NEW,
        )
        self.requester_side_session = RemoteSession.objects.create(
            ticket=ticket_a, requester=self.user, agent=self.other_agent,
            connector=connector, status=RemoteSession.Status.REQUESTED,
        )

        ticket_b = Ticket.objects.create(
            number='TK#DB2', title='Agent side', description='d',
            requester=self.other_requester, category=category, status=Ticket.Status.NEW,
        )
        self.agent_side_session = RemoteSession.objects.create(
            ticket=ticket_b, requester=self.other_requester, agent=self.user,
            connector=connector, status=RemoteSession.Status.ACCEPTED,
        )

        self.client = Client()
        self.client.login(email='dashbanner@example.com', password='TestPass123!')

    def test_banner_shows_only_requester_prompt_while_active_as_end_user(self):
        self.user.set_active_role('END_USER')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'A remote session was requested')
        self.assertNotContains(response, 'accepted your remote session request')

    def test_banner_shows_only_agent_prompt_while_active_as_agent(self):
        self.user.set_active_role('AGENT')
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'accepted your remote session request')

