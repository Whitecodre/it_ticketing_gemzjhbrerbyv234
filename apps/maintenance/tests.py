from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.common.models import Notification
from apps.maintenance.models import MaintenanceSchedule
from django.core.management import call_command


def make_schedule(**kwargs):
    defaults = {
        'title': 'Server room check',
        'department': MaintenanceSchedule.Department.IT,
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


class MaintenanceConfirmNotificationTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            email='manager@example.com', password='TestPass123!',
            first_name='Manager', last_name='Lead', department='IT', role=User.Role.TEAM_LEAD,
        )
        self.assignee = User.objects.create_user(
            email='doer@example.com', password='TestPass123!',
            first_name='Doer', last_name='One', department='IT', role=User.Role.AGENT,
        )
        self.helper = User.objects.create_user(
            email='doer2@example.com', password='TestPass123!',
            first_name='Doer', last_name='Two', department='IT', role=User.Role.AGENT,
        )
        self.schedule = make_schedule(
            assigned_to=self.assignee, status=MaintenanceSchedule.Status.COMPLETED,
        )
        self.schedule.additional_assignees.add(self.helper)
        self.client = Client()

    def test_confirmation_notifies_all_assignees(self):
        self.client.login(email='manager@example.com', password='TestPass123!')
        self.client.post(
            reverse('maintenance:confirm', kwargs={'pk': self.schedule.pk}),
            {'comment': 'Looks good'},
        )
        self.schedule.refresh_from_db()
        self.assertIsNotNone(self.schedule.confirmed_by)
        self.assertTrue(Notification.objects.filter(recipient=self.assignee).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.helper).exists())
