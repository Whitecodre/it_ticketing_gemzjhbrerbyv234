from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from .views import build_role_tiers, TIER_ROLES

User = get_user_model()


class BuildRoleTiersTests(TestCase):
    """build_role_tiers groups users into the fixed System Organogram tiers."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Ada', last_name='Min', department='IT', role='ADMIN',
        )
        self.team_lead = User.objects.create_user(
            email='lead@example.com', password='TestPass123!',
            first_name='Terry', last_name='Lead', department='IT', role='TEAM_LEAD',
        )
        self.agent = User.objects.create_user(
            email='agent@example.com', password='TestPass123!',
            first_name='Aggie', last_name='Ent', department='IT', role='AGENT',
        )
        self.end_user = User.objects.create_user(
            email='user@example.com', password='TestPass123!',
            first_name='Uma', last_name='Ser', department='MARINE', role='END_USER',
        )
        self.superadmin = User.objects.create_user(
            email='super@example.com', password='TestPass123!',
            first_name='Sam', last_name='Super', department='IT', role='SUPERADMIN',
        )

    def test_tier_keys_match_declared_order(self):
        tiers = build_role_tiers(User.objects.all())
        self.assertEqual([t['key'] for t in tiers], [key for key, _ in TIER_ROLES])

    def test_users_land_in_the_tier_matching_their_role(self):
        tiers = build_role_tiers(User.objects.all())
        by_key = {t['key']: t for t in tiers}
        self.assertIn(self.admin, by_key['ADMIN']['users'])
        self.assertIn(self.team_lead, by_key['TEAM_LEAD']['users'])
        self.assertIn(self.agent, by_key['AGENT']['users'])
        self.assertIn(self.end_user, by_key['END_USER']['users'])

    def test_superadmin_is_excluded_from_every_tier(self):
        """SUPERADMIN is a technical account, not an org-chart position."""
        tiers = build_role_tiers(User.objects.all())
        for tier in tiers:
            self.assertNotIn(self.superadmin, tier['users'])

    def test_dual_role_user_appears_in_every_tier_they_hold(self):
        """A user with both TEAM_LEAD and AGENT roles (via the M2M) should
        show up in both tiers, regardless of which role is currently active."""
        team_lead_role, _ = Role.objects.get_or_create(name='TEAM_LEAD', defaults={'display_name': 'Team Lead', 'priority': 2})
        agent_role, _ = Role.objects.get_or_create(name='AGENT', defaults={'display_name': 'Agent', 'priority': 3})
        self.team_lead.roles.add(team_lead_role, agent_role)

        tiers = build_role_tiers(User.objects.all())
        by_key = {t['key']: t for t in tiers}
        self.assertIn(self.team_lead, by_key['TEAM_LEAD']['users'])
        self.assertIn(self.team_lead, by_key['AGENT']['users'])

    def test_tier_counts_and_display_limit_are_consistent(self):
        tiers = build_role_tiers(User.objects.all())
        for tier in tiers:
            self.assertEqual(tier['count'], len(tier['users']))
            self.assertLessEqual(len(tier['display_users']), tier['count'])

    def test_empty_queryset_produces_all_tiers_with_zero_counts(self):
        tiers = build_role_tiers(User.objects.none())
        self.assertEqual(len(tiers), len(TIER_ROLES))
        for tier in tiers:
            self.assertEqual(tier['count'], 0)
            self.assertEqual(tier['users'], [])


class SystemOrgViewTests(TestCase):
    """Smoke tests for the System Organogram view: auth gating and rendering."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Ada', last_name='Min', department='IT', role='ADMIN',
        )
        self.end_user = User.objects.create_user(
            email='user@example.com', password='TestPass123!',
            first_name='Uma', last_name='Ser', department='MARINE', role='END_USER',
        )

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse('organogram:system'))
        self.assertEqual(response.status_code, 302)

    def test_end_user_is_forbidden(self):
        self.client.force_login(self.end_user)
        response = self.client.get(reverse('organogram:system'))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_view_system_org(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('organogram:system'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('tiers', response.context)
        self.assertTrue(response.context['has_results'])

    def test_department_filter_narrows_results(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('organogram:system'), {'department': 'MARINE'})
        self.assertEqual(response.status_code, 200)
        by_key = {t['key']: t for t in response.context['tiers']}
        self.assertIn(self.end_user, by_key['END_USER']['users'])
        self.assertNotIn(self.admin, by_key['ADMIN']['users'])

    def test_print_view_mirrors_the_same_filters(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('organogram:system_print'), {'department': 'IT'})
        self.assertEqual(response.status_code, 200)
        by_key = {t['key']: t for t in response.context['tiers']}
        self.assertIn(self.admin, by_key['ADMIN']['users'])
