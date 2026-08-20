from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from apps.common.models import Category, Tag, Notification, PushSubscription

User = get_user_model()


class CategoryModelTests(TestCase):
    """Test Category model."""

    def test_category_creation(self):
        category = Category.objects.create(
            name='Test Category',
            slug='test-category',
            description='Test description'
        )
        self.assertEqual(category.name, 'Test Category')
        self.assertEqual(category.slug, 'test-category')
        self.assertEqual(str(category), 'Test Category')

    def test_category_parent_relationship(self):
        parent = Category.objects.create(name='Parent', slug='parent')
        child = Category.objects.create(
            name='Child',
            slug='child',
            parent=parent
        )
        self.assertEqual(child.parent, parent)
        self.assertIn(child, parent.children.all())


class TagModelTests(TestCase):
    """Test Tag model."""

    def test_tag_creation(self):
        tag = Tag.objects.create(name='test-tag')
        self.assertEqual(tag.name, 'test-tag')
        self.assertEqual(str(tag), 'test-tag')


class PushSubscriptionModelTests(TestCase):
    """Test PushSubscription model."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT'
        )

    def test_push_subscription_creation(self):
        sub = PushSubscription.objects.create(
            user=self.user,
            endpoint='https://example.com/endpoint',
            auth_key='auth123',
            p256dh_key='p256dh123'
        )
        self.assertEqual(sub.user, self.user)
        self.assertEqual(sub.endpoint, 'https://example.com/endpoint')
        self.assertEqual(str(sub), f'PushSubscription for {self.user.email}')


class NotificationModelTests(TestCase):
    """Test Notification model."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT'
        )

    def test_notification_creation(self):
        notification = Notification.objects.create(
            recipient=self.user,
            message='Test notification',
            url='/dashboard/',
            type=Notification.Type.GENERAL
        )
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.message, 'Test notification')
        self.assertFalse(notification.is_read)
        self.assertEqual(notification.type, Notification.Type.GENERAL)
        self.assertEqual(str(notification), f'Notification for {self.user.email}: Test notification')

    def test_notification_mark_read(self):
        notification = Notification.objects.create(
            recipient=self.user,
            message='Test notification',
            url='/dashboard/'
        )
        self.assertFalse(notification.is_read)
        notification.is_read = True
        notification.save()
        self.assertTrue(notification.is_read)

    def test_notification_unread_count(self):
        """Test unread notification count."""
        Notification.objects.create(recipient=self.user, message='Notif 1', url='/')
        Notification.objects.create(recipient=self.user, message='Notif 2', url='/')
        Notification.objects.create(recipient=self.user, message='Notif 3', url='/')

        notif = Notification.objects.filter(recipient=self.user).first()
        notif.is_read = True
        notif.save()


class NotificationRoleScopingTests(TestCase):
    """A dual-role account should only see notifications tagged for whichever
    role is currently active, plus role-agnostic (untagged) ones — covers the
    bug where switching roles had no effect on visible notifications at all,
    since the model previously had no role concept."""

    def setUp(self):
        from django.test import Client
        from apps.accounts.models import Role

        self.client = Client()
        self.user = User.objects.create_user(
            email='dualrole@example.com', password='TestPass123!',
            first_name='Dual', last_name='Role', department='IT',
            role=User.Role.END_USER, is_active=True, email_verified=True,
        )
        self.agent_role, _ = Role.objects.get_or_create(
            name='AGENT', defaults={'display_name': 'Support Team', 'priority': 4}
        )
        self.end_user_role, _ = Role.objects.get_or_create(
            name='END_USER', defaults={'display_name': 'User', 'priority': 5}
        )
        self.user.roles.add(self.agent_role, self.end_user_role)

        self.agent_notif = Notification.objects.create(
            recipient=self.user, role='AGENT', message='Ticket assigned to you', url='/'
        )
        self.end_user_notif = Notification.objects.create(
            recipient=self.user, role='END_USER', message='Your ticket was updated', url='/'
        )
        self.untagged_notif = Notification.objects.create(
            recipient=self.user, role=None, message='System maintenance notice', url='/'
        )

        self.client.login(email='dualrole@example.com', password='TestPass123!')

    def test_bell_dropdown_shows_only_matching_role_plus_untagged(self):
        self.user.set_active_role('END_USER')
        response = self.client.get(reverse('notifications:list'))
        self.assertContains(response, 'Your ticket was updated')
        self.assertContains(response, 'System maintenance notice')
        self.assertNotContains(response, 'Ticket assigned to you')

    def test_switching_role_changes_visible_notifications(self):
        self.user.set_active_role('AGENT')
        response = self.client.get(reverse('notifications:list'))
        self.assertContains(response, 'Ticket assigned to you')
        self.assertContains(response, 'System maintenance notice')
        self.assertNotContains(response, 'Your ticket was updated')

    def test_notifications_page_scoped_by_active_role(self):
        self.user.set_active_role('END_USER')
        response = self.client.get(reverse('notifications:page'))
        self.assertContains(response, 'Your ticket was updated')
        self.assertNotContains(response, 'Ticket assigned to you')

    def test_unread_count_scoped_by_active_role(self):
        self.user.set_active_role('END_USER')
        response = self.client.get(reverse('notifications:unread_count'))
        # Only end-user + untagged are visible/counted while active as End User
        self.assertContains(response, '2')

    def test_mark_all_read_only_affects_active_role_scoped_notifications(self):
        self.user.set_active_role('END_USER')
        self.client.post(reverse('notifications:mark_all_read'))

        self.agent_notif.refresh_from_db()
        self.end_user_notif.refresh_from_db()
        self.untagged_notif.refresh_from_db()

        self.assertFalse(self.agent_notif.is_read, "agent-tagged notification shouldn't be marked read while active as End User")
        self.assertTrue(self.end_user_notif.is_read)
        self.assertTrue(self.untagged_notif.is_read)

        count = Notification.objects.filter(recipient=self.user, is_read=False).count()
        self.assertEqual(count, 1)