from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common.models import Notification
from apps.maintenance.models import (
    MaintenanceSchedule, MaintenanceChecklistTemplate, MaintenanceActivityLog,
    MaintenanceAssetConfirmation, Vendor,
)
from apps.maintenance.views import can_change_maintenance_status
from apps.maintenance.management.commands.send_maintenance_reminders import auto_start_due_schedules
from apps.tickets.models import Asset, AssetCategory, AssetDepartment


def _department(code):
    """Test helper: resolve/create the AssetDepartment matching a legacy
    User.DEPARTMENT_CHOICES code, mirroring how the seeded data migration
    populates it in real environments."""
    dept, _ = AssetDepartment.objects.get_or_create(
        legacy_user_department_code=code, defaults={'name': code}
    )
    return dept
from django.core.management import call_command


def make_schedule(**kwargs):
    defaults = {
        'title': 'Server room check',
        'departments': [MaintenanceSchedule.Department.IT],
        'scheduled_date': timezone.now().date() + timedelta(days=1),
        'status': MaintenanceSchedule.Status.SCHEDULED,
    }
    defaults.update(kwargs)
    return MaintenanceSchedule.objects.create(**defaults)


class AdditionalAssigneesTests(TestCase):
    def setUp(self):
        self.primary = User.objects.create_user(
            email='primary@example.com', password='TestPass123!',
            first_name='Primary', last_name='Agent', department='IT', role=User.Role.AGENT,
        )
        self.helper = User.objects.create_user(
            email='helper@example.com', password='TestPass123!',
            first_name='Helper', last_name='Agent', department='IT', role=User.Role.AGENT,
        )
        self.outsider = User.objects.create_user(
            email='outsider@example.com', password='TestPass123!',
            first_name='Out', last_name='Sider', department='IT', role=User.Role.AGENT,
        )
        self.schedule = make_schedule(assigned_to=self.primary)
        self.schedule.additional_assignees.add(self.helper)
        self.client = Client()

    def test_is_assigned_to(self):
        self.assertTrue(self.schedule.is_assigned_to(self.primary))
        self.assertTrue(self.schedule.is_assigned_to(self.helper))
        self.assertFalse(self.schedule.is_assigned_to(self.outsider))

    def test_additional_assignee_can_update_status(self):
        self.client.login(email='helper@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('maintenance:update_status', kwargs={'pk': self.schedule.pk}),
            {'status': MaintenanceSchedule.Status.IN_PROGRESS, 'comment': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.status, MaintenanceSchedule.Status.IN_PROGRESS)

    def test_outsider_cannot_update_status(self):
        self.client.login(email='outsider@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('maintenance:update_status', kwargs={'pk': self.schedule.pk}),
            {'status': MaintenanceSchedule.Status.IN_PROGRESS, 'comment': ''},
        )
        self.assertEqual(response.status_code, 403)

    def test_mine_filter_includes_primary_and_additional(self):
        self.client.login(email='helper@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:list') + '?mine=1')
        self.assertContains(response, self.schedule.title)


class MaintenanceReminderTests(TestCase):
    def setUp(self):
        self.assignee = User.objects.create_user(
            email='assignee@example.com', password='TestPass123!',
            first_name='Assignee', last_name='One', department='IT', role=User.Role.AGENT,
        )

    def test_reminder_sent_once_per_threshold(self):
        due_soon = timezone.now() + timedelta(minutes=5)
        schedule = make_schedule(
            assigned_to=self.assignee,
            scheduled_date=due_soon.date(),
            start_time=due_soon.time(),
        )
        call_command('send_maintenance_reminders')
        schedule.refresh_from_db()
        self.assertTrue(schedule.reminder_24h_sent)
        self.assertTrue(schedule.reminder_1h_sent)
        self.assertTrue(schedule.reminder_10m_sent)
        self.assertEqual(Notification.objects.filter(recipient=self.assignee).count(), 3)

        # Running again shouldn't duplicate any reminder.
        call_command('send_maintenance_reminders')
        self.assertEqual(Notification.objects.filter(recipient=self.assignee).count(), 3)

    def test_no_reminder_for_far_future_schedule(self):
        far_future = timezone.now() + timedelta(days=10)
        schedule = make_schedule(
            assigned_to=self.assignee,
            scheduled_date=far_future.date(),
            start_time=far_future.time(),
        )
        call_command('send_maintenance_reminders')
        schedule.refresh_from_db()
        self.assertFalse(schedule.reminder_24h_sent)
        self.assertEqual(Notification.objects.filter(recipient=self.assignee).count(), 0)


class RecurringScheduleTests(TestCase):
    """MaintenanceSchedule.spawn_next_occurrence / the send_maintenance_reminders
    job's auto-create-on-due-date recurrence stopgap."""

    def setUp(self):
        self.assignee = User.objects.create_user(
            email='recurring-assignee@example.com', password='TestPass123!',
            first_name='Recurring', last_name='Assignee', department='IT', role=User.Role.AGENT,
        )

    def test_weekly_next_date(self):
        schedule = make_schedule(
            assigned_to=self.assignee, repeat_interval=MaintenanceSchedule.Recurrence.WEEKLY,
            scheduled_date=timezone.now().date(),
        )
        clone = schedule.spawn_next_occurrence()
        self.assertEqual(clone.scheduled_date, schedule.scheduled_date + timedelta(days=7))
        self.assertEqual(clone.repeat_interval, MaintenanceSchedule.Recurrence.WEEKLY)
        self.assertEqual(clone.title, schedule.title)
        self.assertEqual(clone.status, MaintenanceSchedule.Status.SCHEDULED)

    def test_monthly_next_date_clips_short_month(self):
        from datetime import date
        schedule = make_schedule(
            assigned_to=self.assignee, repeat_interval=MaintenanceSchedule.Recurrence.MONTHLY,
            scheduled_date=date(2026, 1, 31),
        )
        clone = schedule.spawn_next_occurrence()
        self.assertEqual(clone.scheduled_date, date(2026, 2, 28))

    def test_non_recurring_schedule_spawns_nothing(self):
        schedule = make_schedule(assigned_to=self.assignee)
        self.assertIsNone(schedule.spawn_next_occurrence())

    def test_spawn_marks_original_and_is_idempotent(self):
        schedule = make_schedule(
            assigned_to=self.assignee, repeat_interval=MaintenanceSchedule.Recurrence.WEEKLY,
            scheduled_date=timezone.now().date(),
        )
        schedule.spawn_next_occurrence()
        schedule.refresh_from_db()
        self.assertTrue(schedule.next_occurrence_created)

    def test_reminders_job_spawns_due_recurring_schedule(self):
        schedule = make_schedule(
            assigned_to=self.assignee, repeat_interval=MaintenanceSchedule.Recurrence.WEEKLY,
            scheduled_date=timezone.now().date() - timedelta(days=1),
        )
        call_command('send_maintenance_reminders')
        schedule.refresh_from_db()
        self.assertTrue(schedule.next_occurrence_created)
        self.assertEqual(
            MaintenanceSchedule.objects.filter(title=schedule.title).count(), 2,
        )

        # Running again shouldn't spawn a second clone.
        call_command('send_maintenance_reminders')
        self.assertEqual(
            MaintenanceSchedule.objects.filter(title=schedule.title).count(), 2,
        )

    def test_reminders_job_does_not_spawn_future_recurring_schedule(self):
        schedule = make_schedule(
            assigned_to=self.assignee, repeat_interval=MaintenanceSchedule.Recurrence.WEEKLY,
            scheduled_date=timezone.now().date() + timedelta(days=5),
        )
        call_command('send_maintenance_reminders')
        schedule.refresh_from_db()
        self.assertFalse(schedule.next_occurrence_created)
        self.assertEqual(MaintenanceSchedule.objects.filter(title=schedule.title).count(), 1)


class AssetOwnerConfirmationTests(TestCase):
    """The asset OWNER confirms/disputes completion — not the technician who
    did the work — per-asset via MaintenanceAssetConfirmation."""

    def setUp(self):
        self.owner = User.objects.create_user(
            email='owner@example.com', password='TestPass123!',
            first_name='Asset', last_name='Owner', department='IT', role=User.Role.END_USER,
        )
        self.assignee = User.objects.create_user(
            email='doer@example.com', password='TestPass123!',
            first_name='Doer', last_name='One', department='IT', role=User.Role.AGENT,
        )
        self.helper = User.objects.create_user(
            email='doer2@example.com', password='TestPass123!',
            first_name='Doer', last_name='Two', department='IT', role=User.Role.AGENT,
        )
        category = AssetCategory.objects.create(name='Laptops')
        self.asset = Asset.objects.create(name='Owner Laptop', category=category, department=_department('IT'), assigned_to=self.owner)
        self.schedule = make_schedule(
            assigned_to=self.assignee, status=MaintenanceSchedule.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.schedule.additional_assignees.add(self.helper)
        self.schedule.target_assets.add(self.asset)
        self.row = MaintenanceAssetConfirmation.objects.create(
            schedule=self.schedule, asset=self.asset, technician_completed_at=self.schedule.completed_at,
        )
        self.client = Client()

    def test_technician_cannot_confirm_own_work(self):
        self.client.login(email='doer@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'PENDING')

    def test_owner_confirmation_notifies_all_assignees(self):
        self.client.login(email='owner@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': 'Looks good'},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'CONFIRMED')
        self.assertEqual(self.row.confirmed_by, self.owner)
        self.assertTrue(Notification.objects.filter(recipient=self.assignee).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.helper).exists())

    def test_owner_dispute_requires_reason(self):
        self.client.login(email='owner@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'DISPUTED', 'notes': '', 'dispute_reason': ''},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'PENDING')
        self.assertContains(response, 'explain')

    def test_owner_dispute_with_reason_succeeds(self):
        self.client.login(email='owner@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'DISPUTED', 'notes': '', 'dispute_reason': 'Still broken'},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'DISPUTED')
        self.assertEqual(self.row.dispute_reason, 'Still broken')
        self.assertEqual(self.schedule.confirmation_state(), 'HAS_DISPUTE')

    def test_admin_cannot_confirm_asset_that_has_an_owner(self):
        """Admin is never eligible while a real confirmer (the owner) exists
        — not on a PENDING row, and not to reopen an already-resolved one.
        The whole point of the independent confirmation step is that the
        party accountable for scheduling the work doesn't get final say."""
        admin = User.objects.create_user(
            email='override-admin@example.com', password='TestPass123!',
            first_name='Override', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        self.client.login(email='override-admin@example.com', password='TestPass123!')

        # PENDING row: Admin still can't jump in ahead of the owner.
        response = self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': ''},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'PENDING')

        # Owner confirms for real...
        self.row.status = 'CONFIRMED'
        self.row.confirmed_by = self.owner
        self.row.confirmed_at = timezone.now()
        self.row.save()

        # ...and Admin can no longer reopen/overwrite it either.
        response = self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'DISPUTED', 'notes': '', 'dispute_reason': 'Found an issue on recheck'},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'CONFIRMED')
        self.assertEqual(self.row.confirmed_by, self.owner)

    def test_other_user_cannot_confirm(self):
        outsider = User.objects.create_user(
            email='outsider-confirm@example.com', password='TestPass123!',
            first_name='Out', last_name='Sider', department='HR', role=User.Role.END_USER,
        )
        self.client.login(email='outsider-confirm@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'PENDING')


class OwnerlessAssetFallbackConfirmationTests(TestCase):
    """When an ownerless asset has no owner, the IT Team Lead confirms it.
    Admin/Superadmin are only eligible when no IT Team Lead exists at all —
    not merely because the asset itself has no owner."""

    def setUp(self):
        self.assignee = User.objects.create_user(
            email='fallback-doer@example.com', password='TestPass123!',
            first_name='Doer', last_name='Fallback', department='IT', role=User.Role.AGENT,
        )
        self.it_team_lead = User.objects.create_user(
            email='fallback-lead@example.com', password='TestPass123!',
            first_name='IT', last_name='Lead', department='IT', role=User.Role.TEAM_LEAD,
        )
        self.hr_team_lead = User.objects.create_user(
            email='fallback-hr-lead@example.com', password='TestPass123!',
            first_name='HR', last_name='Lead', department='HR', role=User.Role.TEAM_LEAD,
        )
        category = AssetCategory.objects.create(name='Servers')
        self.asset = Asset.objects.create(name='Ownerless Server', category=category, department=_department('IT'))
        self.schedule = make_schedule(
            assigned_to=self.assignee, status=MaintenanceSchedule.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.schedule.target_assets.add(self.asset)
        self.row = MaintenanceAssetConfirmation.objects.create(
            schedule=self.schedule, asset=self.asset, technician_completed_at=self.schedule.completed_at,
        )
        self.client = Client()

    def test_same_department_team_lead_can_confirm(self):
        self.client.login(email='fallback-lead@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': ''},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'CONFIRMED')

    def test_other_department_team_lead_cannot_confirm(self):
        self.client.login(email='fallback-hr-lead@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': ''},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'PENDING')

    def test_admin_cannot_confirm_ownerless_asset_while_it_team_lead_exists(self):
        admin = User.objects.create_user(
            email='fallback-admin@example.com', password='TestPass123!',
            first_name='Fallback', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        self.client.login(email='fallback-admin@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': ''},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'PENDING')


class AdminLastResortFallbackConfirmationTests(TestCase):
    """Admin/Superadmin may confirm an ownerless asset ONLY when there is
    truly no one else who ever could — no owner, and no IT Team Lead
    anywhere in the system. Even then, once resolved, it's final: not even
    another Admin can reopen it."""

    def setUp(self):
        self.assignee = User.objects.create_user(
            email='orphan-doer@example.com', password='TestPass123!',
            first_name='Doer', last_name='Orphan', department='IT', role=User.Role.AGENT,
        )
        self.admin = User.objects.create_user(
            email='orphan-admin@example.com', password='TestPass123!',
            first_name='Orphan', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        category = AssetCategory.objects.create(name='Routers')
        self.asset = Asset.objects.create(name='Orphan Router', category=category, department=_department('IT'))
        self.schedule = make_schedule(
            assigned_to=self.assignee, status=MaintenanceSchedule.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.schedule.target_assets.add(self.asset)
        self.row = MaintenanceAssetConfirmation.objects.create(
            schedule=self.schedule, asset=self.asset, technician_completed_at=self.schedule.completed_at,
        )
        self.client = Client()
        # No IT Team Lead exists anywhere in this TestCase's data — genuine
        # orphan case.

    def test_admin_can_confirm_when_no_owner_and_no_it_team_lead_exists(self):
        self.client.login(email='orphan-admin@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'CONFIRMED', 'notes': ''},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'CONFIRMED')
        self.assertEqual(self.row.confirmed_by, self.admin)

    def test_admin_cannot_reopen_its_own_last_resort_confirmation(self):
        self.row.status = 'CONFIRMED'
        self.row.confirmed_by = self.admin
        self.row.confirmed_at = timezone.now()
        self.row.save()

        self.client.login(email='orphan-admin@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:asset_confirm', kwargs={'pk': self.schedule.pk, 'asset_pk': self.asset.pk}),
            {'decision': 'DISPUTED', 'notes': '', 'dispute_reason': 'Changed my mind'},
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, 'CONFIRMED')


class StatusChangePermissionTests(TestCase):
    """Only assigned officers or the target department's own Team Lead may
    change a schedule's status — Admin/Superadmin can view but not act."""

    def setUp(self):
        self.assignee = User.objects.create_user(
            email='it-agent@example.com', password='TestPass123!',
            first_name='IT', last_name='Agent', department='IT', role=User.Role.AGENT,
        )
        self.it_team_lead = User.objects.create_user(
            email='it-lead@example.com', password='TestPass123!',
            first_name='IT', last_name='Lead', department='IT', role=User.Role.TEAM_LEAD,
        )
        self.other_dept_team_lead = User.objects.create_user(
            email='hr-lead@example.com', password='TestPass123!',
            first_name='HR', last_name='Lead', department='HR', role=User.Role.TEAM_LEAD,
        )
        self.admin = User.objects.create_user(
            email='admin@example.com', password='TestPass123!',
            first_name='Admin', last_name='User', department='IT', role=User.Role.ADMIN,
        )
        self.schedule = make_schedule(assigned_to=self.assignee, departments=[MaintenanceSchedule.Department.IT])
        self.client = Client()

    def test_assigned_officer_can_change_status(self):
        self.assertTrue(can_change_maintenance_status(self.assignee, self.schedule))

    def test_target_department_team_lead_can_change_status(self):
        self.assertTrue(can_change_maintenance_status(self.it_team_lead, self.schedule))

    def test_other_department_team_lead_cannot_change_status(self):
        self.assertFalse(can_change_maintenance_status(self.other_dept_team_lead, self.schedule))

    def test_admin_cannot_change_status(self):
        self.assertFalse(can_change_maintenance_status(self.admin, self.schedule))

    def test_admin_post_to_update_status_is_forbidden(self):
        self.client.login(email='admin@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('maintenance:update_status', kwargs={'pk': self.schedule.pk}),
            {'status': MaintenanceSchedule.Status.IN_PROGRESS, 'comment': ''},
        )
        self.assertEqual(response.status_code, 403)

    def test_status_change_notifies_admin_and_department_team_lead_excluding_actor(self):
        self.client.login(email='it-agent@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:update_status', kwargs={'pk': self.schedule.pk}),
            {'status': MaintenanceSchedule.Status.IN_PROGRESS, 'comment': ''},
        )
        self.assertTrue(Notification.objects.filter(recipient=self.admin).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.it_team_lead).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.assignee).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.other_dept_team_lead).exists())


class MultiDepartmentTests(TestCase):
    """A schedule can target multiple departments at once — both target
    departments' Team Leads (and only them) can see/act on it, and it's
    excluded from a third, unrelated department's Team Lead view."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='multi-admin@example.com', password='TestPass123!',
            first_name='Multi', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        self.it_lead = User.objects.create_user(
            email='multi-it-lead@example.com', password='TestPass123!',
            first_name='Multi', last_name='ITLead', department='IT', role=User.Role.TEAM_LEAD,
        )
        self.ops_lead = User.objects.create_user(
            email='multi-ops-lead@example.com', password='TestPass123!',
            first_name='Multi', last_name='OpsLead', department='OPERATIONS', role=User.Role.TEAM_LEAD,
        )
        self.hr_lead = User.objects.create_user(
            email='multi-hr-lead@example.com', password='TestPass123!',
            first_name='Multi', last_name='HRLead', department='HR', role=User.Role.TEAM_LEAD,
        )
        self.assignee = User.objects.create_user(
            email='multi-assignee@example.com', password='TestPass123!',
            first_name='Multi', last_name='Assignee', department='IT', role=User.Role.AGENT,
        )
        self.schedule = make_schedule(
            assigned_to=self.assignee,
            departments=[MaintenanceSchedule.Department.IT, MaintenanceSchedule.Department.OPERATIONS],
        )
        self.client = Client()

    def test_departments_display_joins_labels(self):
        self.assertIn('IT', self.schedule.departments_display)
        self.assertIn('Operations', self.schedule.departments_display)

    def test_both_target_department_leads_can_change_status(self):
        self.assertTrue(can_change_maintenance_status(self.it_lead, self.schedule))
        self.assertTrue(can_change_maintenance_status(self.ops_lead, self.schedule))

    def test_unrelated_department_lead_cannot_change_status(self):
        self.assertFalse(can_change_maintenance_status(self.hr_lead, self.schedule))

    def test_schedule_list_department_filter_matches_either_department(self):
        self.client.login(email='multi-admin@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:list'), {'department': 'OPERATIONS'})
        self.assertContains(response, self.schedule.title)

    def test_team_lead_scoped_list_includes_multi_department_schedule(self):
        self.client.login(email='multi-ops-lead@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:list'))
        self.assertContains(response, self.schedule.title)

    def test_unrelated_team_lead_scoped_list_excludes_schedule(self):
        self.client.login(email='multi-hr-lead@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:list'))
        self.assertNotContains(response, self.schedule.title)

    def test_create_schedule_with_multiple_departments(self):
        self.client.login(email='multi-admin@example.com', password='TestPass123!')
        payload = {
            'title': 'Two-department schedule',
            'departments': [MaintenanceSchedule.Department.IT, MaintenanceSchedule.Department.HR],
            'scheduled_date': (timezone.now().date() + timedelta(days=3)).isoformat(),
            'start_time': '', 'end_time': '', 'description': '', 'facility_location': '',
            'checklist_items': [],
        }
        self.client.post(reverse('maintenance:create'), payload)
        schedule = MaintenanceSchedule.objects.get(title='Two-department schedule')
        self.assertEqual(set(schedule.departments), {'IT', 'HR'})


class VendorTests(TestCase):
    """Vendors are pure record-keeping — attaching one has no effect on who
    can change a schedule's status."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='vendor-admin@example.com', password='TestPass123!',
            first_name='Vendor', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        self.assignee = User.objects.create_user(
            email='vendor-assignee@example.com', password='TestPass123!',
            first_name='Vendor', last_name='Assignee', department='IT', role=User.Role.AGENT,
        )
        self.vendor = Vendor.objects.create(
            name='Acme HVAC Services', contact_person='Jane Doe', phone='555-0100',
        )
        self.client = Client()

    def test_create_schedule_with_vendor(self):
        self.client.login(email='vendor-admin@example.com', password='TestPass123!')
        payload = {
            'title': 'Vendor-assisted schedule',
            'departments': [MaintenanceSchedule.Department.IT],
            'scheduled_date': (timezone.now().date() + timedelta(days=2)).isoformat(),
            'start_time': '', 'end_time': '', 'description': '', 'facility_location': '',
            'checklist_items': [],
            'vendors': [self.vendor.pk],
            'assigned_to': self.assignee.pk,
        }
        self.client.post(reverse('maintenance:create'), payload)
        schedule = MaintenanceSchedule.objects.get(title='Vendor-assisted schedule')
        self.assertIn(self.vendor, schedule.vendors.all())

    def test_vendor_does_not_grant_status_change_permission(self):
        schedule = make_schedule(assigned_to=self.assignee)
        schedule.vendors.add(self.vendor)
        # The vendor itself has no User account and can't be checked via
        # can_change_maintenance_status — confirm the schedule's real
        # assignee is unaffected by the vendor attachment either way.
        self.assertTrue(can_change_maintenance_status(self.assignee, schedule))
        self.assertFalse(can_change_maintenance_status(self.admin, schedule))

    def test_inactive_vendor_not_offered_in_picker(self):
        Vendor.objects.create(name='Retired Vendor', is_active=False)
        self.client.login(email='vendor-admin@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:create'))
        self.assertContains(response, 'Acme HVAC Services')
        self.assertNotContains(response, 'Retired Vendor')

    def test_vendor_categories_display(self):
        self.assertEqual(self.vendor.categories_display, '—')
        laptop = AssetCategory.objects.create(name='Laptop')
        server = AssetCategory.objects.create(name='Server')
        self.vendor.categories.add(laptop, server)
        self.assertEqual(self.vendor.categories_display, 'Laptop, Server')


class ChecklistTemplateTests(TestCase):
    """Custom checklist items typed on the schedule form should be saved as
    reusable, per-department templates with case-insensitive dedupe."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='admin2@example.com', password='TestPass123!',
            first_name='Admin', last_name='Two', department='IT', role=User.Role.ADMIN,
        )
        self.client = Client()
        self.client.login(email='admin2@example.com', password='TestPass123!')

    def _base_payload(self):
        return {
            'title': 'Quarterly check',
            'departments': [MaintenanceSchedule.Department.IT],
            'scheduled_date': (timezone.now().date() + timedelta(days=2)).isoformat(),
            'start_time': '',
            'end_time': '',
            'description': '',
            'facility_location': '',
        }

    def test_custom_checklist_item_is_saved_as_template(self):
        payload = self._base_payload()
        payload['checklist_items'] = ['Check UPS battery']
        self.client.post(reverse('maintenance:create'), payload)
        self.assertTrue(
            MaintenanceChecklistTemplate.objects.filter(
                department=MaintenanceSchedule.Department.IT, text='Check UPS battery'
            ).exists()
        )

    def test_case_insensitive_reuse_does_not_duplicate(self):
        MaintenanceChecklistTemplate.objects.create(
            department=MaintenanceSchedule.Department.IT, text='Check UPS battery'
        )
        payload = self._base_payload()
        payload['checklist_items'] = ['check ups battery']
        self.client.post(reverse('maintenance:create'), payload)
        self.assertEqual(
            MaintenanceChecklistTemplate.objects.filter(department=MaintenanceSchedule.Department.IT).count(),
            1,
        )


class AutoStartTests(TestCase):
    """Schedules auto-start when their scheduled time arrives; Start is no
    longer a manual action."""

    def setUp(self):
        self.assignee = User.objects.create_user(
            email='auto-assignee@example.com', password='TestPass123!',
            first_name='Auto', last_name='Assignee', department='IT', role=User.Role.AGENT,
        )
        self.admin = User.objects.create_user(
            email='auto-admin@example.com', password='TestPass123!',
            first_name='Auto', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        self.it_team_lead = User.objects.create_user(
            email='auto-lead@example.com', password='TestPass123!',
            first_name='Auto', last_name='Lead', department='IT', role=User.Role.TEAM_LEAD,
        )

    def test_due_schedule_auto_starts(self):
        past = timezone.now() - timedelta(minutes=5)
        schedule = make_schedule(
            assigned_to=self.assignee, scheduled_date=past.date(), start_time=past.time(),
        )
        started = auto_start_due_schedules()
        schedule.refresh_from_db()
        self.assertEqual(started, 1)
        self.assertEqual(schedule.status, MaintenanceSchedule.Status.IN_PROGRESS)
        self.assertTrue(
            MaintenanceActivityLog.objects.filter(
                schedule=schedule, action=MaintenanceActivityLog.Action.STATUS_CHANGED, actor__isnull=True,
            ).exists()
        )
        self.assertTrue(Notification.objects.filter(recipient=self.assignee).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.admin).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.it_team_lead).exists())

    def test_future_schedule_does_not_auto_start(self):
        future = timezone.now() + timedelta(days=1)
        schedule = make_schedule(
            assigned_to=self.assignee, scheduled_date=future.date(), start_time=future.time(),
        )
        started = auto_start_due_schedules()
        schedule.refresh_from_db()
        self.assertEqual(started, 0)
        self.assertEqual(schedule.status, MaintenanceSchedule.Status.SCHEDULED)

    def test_start_maintenance_button_removed_from_detail_page(self):
        past = timezone.now() - timedelta(minutes=5)
        schedule = make_schedule(
            assigned_to=self.assignee, scheduled_date=past.date(), start_time=past.time(),
        )
        client = Client()
        client.login(email='auto-assignee@example.com', password='TestPass123!')
        response = client.get(reverse('maintenance:detail', kwargs={'pk': schedule.pk}))
        self.assertNotContains(response, 'Start Maintenance')


class ChecklistCompletionOnFinishTests(TestCase):
    """Completing a schedule marks its checklist 100% — there's no per-item
    toggle UI, so completed_checklist must be filled in when status becomes
    COMPLETED, not left stuck at 0%."""

    def setUp(self):
        self.assignee = User.objects.create_user(
            email='checklist-assignee@example.com', password='TestPass123!',
            first_name='Checklist', last_name='Assignee', department='IT', role=User.Role.AGENT,
        )
        self.schedule = make_schedule(
            assigned_to=self.assignee,
            checklist_items=['Check UPS battery', 'Test generator'],
            completed_checklist=[],
        )
        self.client = Client()
        self.client.login(email='checklist-assignee@example.com', password='TestPass123!')

    def test_completing_schedule_marks_all_checklist_items_done(self):
        self.client.post(
            reverse('maintenance:update_status', kwargs={'pk': self.schedule.pk}),
            {'status': MaintenanceSchedule.Status.COMPLETED, 'comment': ''},
        )
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.completed_checklist, self.schedule.checklist_items)
        self.assertEqual(self.schedule.get_progress_percentage(), 100)


class ConfirmationVisibilityTests(TestCase):
    """The per-asset Confirm/Dispute affordance is only shown to whoever
    can_confirm_asset_maintenance allows for that asset. An owner (an End
    User) confirms from My Assets, not the IT-internal schedule detail page
    — that page is gated to AGENT/TEAM_LEAD/ADMIN/SUPERADMIN only, since it
    also exposes personnel/activity-log info that isn't the owner's
    business (see _asset_review_url)."""

    def setUp(self):
        self.assignee = User.objects.create_user(
            email='confirm-assignee@example.com', password='TestPass123!',
            first_name='Confirm', last_name='Assignee', department='IT', role=User.Role.AGENT,
        )
        self.owner = User.objects.create_user(
            email='confirm-owner@example.com', password='TestPass123!',
            first_name='Confirm', last_name='Owner', department='IT', role=User.Role.END_USER,
        )
        category = AssetCategory.objects.create(name='Desktops')
        self.asset = Asset.objects.create(name='Confirm Desktop', category=category, department=_department('IT'), assigned_to=self.owner)
        self.schedule = make_schedule(
            assigned_to=self.assignee, status=MaintenanceSchedule.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        self.schedule.target_assets.add(self.asset)
        self.row = MaintenanceAssetConfirmation.objects.create(
            schedule=self.schedule, asset=self.asset, technician_completed_at=self.schedule.completed_at,
        )
        self.client = Client()

    def test_assignee_does_not_see_confirm_button(self):
        self.client.login(email='confirm-assignee@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:detail', kwargs={'pk': self.schedule.pk}))
        self.assertNotContains(response, 'Confirm / Dispute')

    def test_owner_sees_confirm_button(self):
        self.client.login(email='confirm-owner@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:my_assets'))
        self.assertContains(response, 'Review &amp; Confirm')

    def test_owner_cannot_access_schedule_detail(self):
        """Owners confirm from My Assets — the schedule detail page itself
        is IT-internal (personnel, activity log) and off-limits to them."""
        self.client.login(email='confirm-owner@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:detail', kwargs={'pk': self.schedule.pk}))
        self.assertEqual(response.status_code, 403)

    def test_assignee_sees_confirmed_status_after_confirmation(self):
        self.row.status = 'CONFIRMED'
        self.row.confirmed_by = self.owner
        self.row.confirmed_at = timezone.now()
        self.row.save()
        self.client.login(email='confirm-assignee@example.com', password='TestPass123!')
        response = self.client.get(reverse('maintenance:detail', kwargs={'pk': self.schedule.pk}))
        self.assertContains(response, 'Confirmed')


class TargetAssetDepartmentScopingTests(TestCase):
    """Target assets are narrowed to the schedule's department, both in the
    HTMX picker partial and as a real form-validation boundary."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email='asset-admin@example.com', password='TestPass123!',
            first_name='Asset', last_name='Admin', department='IT', role=User.Role.ADMIN,
        )
        category = AssetCategory.objects.create(name='Laptops')
        self.it_asset = Asset.objects.create(name='IT Laptop', category=category, department=_department('IT'))
        self.hr_asset = Asset.objects.create(name='HR Printer', category=category, department=_department('HR'))
        self.client = Client()
        self.client.login(email='asset-admin@example.com', password='TestPass123!')

    def test_partial_only_shows_assets_in_selected_department(self):
        response = self.client.get(reverse('maintenance:target_assets_partial'), {'departments': ['IT']})
        self.assertContains(response, 'IT Laptop')
        self.assertNotContains(response, 'HR Printer')

    def test_out_of_department_asset_is_rejected_on_submit(self):
        payload = {
            'title': 'Dept scoped schedule',
            'departments': [MaintenanceSchedule.Department.IT],
            'scheduled_date': (timezone.now().date() + timedelta(days=2)).isoformat(),
            'start_time': '', 'end_time': '', 'description': '', 'facility_location': '',
            'checklist_items': [],
            'target_assets': [self.hr_asset.pk],
        }
        self.client.post(reverse('maintenance:create'), payload)
        self.assertFalse(MaintenanceSchedule.objects.filter(title='Dept scoped schedule').exists())

    def test_in_department_asset_is_accepted_on_submit(self):
        payload = {
            'title': 'Dept scoped schedule 2',
            'departments': [MaintenanceSchedule.Department.IT],
            'scheduled_date': (timezone.now().date() + timedelta(days=2)).isoformat(),
            'start_time': '', 'end_time': '', 'description': '', 'facility_location': '',
            'checklist_items': [],
            'target_assets': [self.it_asset.pk],
        }
        self.client.post(reverse('maintenance:create'), payload)
        schedule = MaintenanceSchedule.objects.get(title='Dept scoped schedule 2')
        self.assertIn(self.it_asset, schedule.target_assets.all())
