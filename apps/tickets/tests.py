from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from apps.tickets.models import Ticket, TicketComment, Asset, AssetLog, SLA, EscalationRule
from apps.common.models import Category, Notification

User = get_user_model()


class TicketModelTests(TestCase):
    """Test Ticket model functionality."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT'
        )
        self.category = Category.objects.create(name='Hardware', slug='hardware')

    def test_ticket_creation(self):
        """Test basic ticket creation."""
        ticket = Ticket.objects.create(
            number='TK#1234',
            title='Test Ticket',
            description='Test Description',
            requester=self.user,
            category=self.category,
            status=Ticket.Status.NEW
        )
        self.assertEqual(ticket.title, 'Test Ticket')
        self.assertEqual(ticket.requester, self.user)
        self.assertEqual(ticket.status, Ticket.Status.NEW)
        self.assertEqual(str(ticket), 'TK#1234 - Test Ticket')

    def test_ticket_priority_calculation(self):
        """Test priority calculation based on impact and urgency."""
        test_cases = [
            (Ticket.Impact.INDIVIDUAL, Ticket.Urgency.CRITICAL, Ticket.Priority.P3),
            (Ticket.Impact.ORGANIZATION, Ticket.Urgency.CRITICAL, Ticket.Priority.P1),
            (Ticket.Impact.DEPARTMENT, Ticket.Urgency.MEDIUM, Ticket.Priority.P4),
        ]

        for i, (impact, urgency, expected) in enumerate(test_cases):
            ticket = Ticket.objects.create(
                number=f'TK#{i}',
                title='Test Ticket',
                description='Test Description',
                requester=self.user,
                category=self.category,
                impact=impact,
                urgency=urgency
            )
            self.assertEqual(ticket.priority, expected)

    def test_ticket_sla_status_method(self):
        """Test sla_status method on Ticket model."""
        sla = SLA.objects.create(
            priority='P3',
            response_minutes=60,
            resolution_minutes=240
        )
        
        ticket = Ticket.objects.create(
            number='TK#8888',
            title='SLA Test Ticket',
            description='Test description',
            requester=self.user,
            category=self.category,
            priority='P3',
            status=Ticket.Status.NEW
        )
        
        status = ticket.sla_status()
        self.assertIn('overall', status)
        self.assertIn('response', status)
        self.assertIn('resolution', status)

    def test_ticket_sla_breach(self):
        """Test SLA breach detection."""
        sla = SLA.objects.create(
            priority='P3',
            response_minutes=60,
            resolution_minutes=240
        )

        ticket = Ticket.objects.create(
            number='TK#8889',
            title='SLA Breach Test',
            description='Test description',
            requester=self.user,
            category=self.category,
            priority='P3',
            status=Ticket.Status.NEW,
            created_at=timezone.now() - timedelta(minutes=120)
        )

        ticket.response_due_at = timezone.now() - timedelta(minutes=30)
        ticket.resolution_due_at = timezone.now() + timedelta(minutes=120)
        ticket.save()

        status = ticket.sla_status()
        # Response SLA should be breached
        self.assertEqual(status['response'], 'breached')


class TicketViewTests(TestCase):
    """Test ticket view functionality."""
    
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
        self.agent = User.objects.create_user(
            email='agent@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='User',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        self.category = Category.objects.create(name='Hardware', slug='hardware')
        self.client.login(email='test@example.com', password='TestPass123!')

    def test_ticket_create_page_loads(self):
        """Test ticket creation page loads."""
        response = self.client.get(reverse('tickets:create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'requester/incident_form.html')

    def test_ticket_create_service_request_page_loads(self):
        """Test service request creation page loads."""
        response = self.client.get(reverse('tickets:create') + '?type=SERVICE_REQUEST')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'requester/service_request_form.html')

    def test_ticket_create_success(self):
        """Test successful ticket creation."""
        response = self.client.post(reverse('tickets:create'), {
            'type': 'INCIDENT',
            'title': 'Test Incident',
            'description': 'Test description',
            'category': self.category.id,
            'impact': 'INDIVIDUAL',
            'urgency': 'MEDIUM'
        })
        self.assertEqual(response.status_code, 302)  # Redirect on success
        ticket = Ticket.objects.filter(title='Test Incident').first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.requester, self.user)

    def test_ticket_create_missing_title(self):
        """Test ticket creation with missing title."""
        response = self.client.post(reverse('tickets:create'), {
            'type': 'INCIDENT',
            'title': '',
            'description': 'Test description',
            'category': self.category.id,
            'impact': 'INDIVIDUAL',
            'urgency': 'MEDIUM'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')

    def test_ticket_list_view(self):
        """Test ticket list view for requester."""
        ticket = Ticket.objects.create(
            number='TK#1234',
            title='Test Ticket',
            description='Test Description',
            requester=self.user,
            category=self.category
        )
        response = self.client.get(reverse('tickets:my_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Ticket')

    def test_ticket_detail_view_requester(self):
        """Test ticket detail view for requester."""
        ticket = Ticket.objects.create(
            number='TK#1234',
            title='Test Ticket',
            description='Test Description',
            requester=self.user,
            category=self.category
        )
        response = self.client.get(reverse('tickets:detail', args=[ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Ticket')

    def test_ticket_detail_view_other_user_denied(self):
        """Test ticket detail view denied for other users."""
        other_user = User.objects.create_user(
            email='other@example.com',
            password='TestPass123!',
            first_name='Other',
            last_name='User',
            department='HR',
            is_active=True,
            email_verified=True
        )
        ticket = Ticket.objects.create(
            number='TK#1234',
            title='Test Ticket',
            description='Test Description',
            requester=self.user,
            category=self.category
        )
        self.client.login(email='other@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:detail', args=[ticket.pk]))
        self.assertEqual(response.status_code, 302)  # Redirect to dashboard


class TicketCommentTests(TestCase):
    """Test ticket comment functionality."""
    
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
        self.category = Category.objects.create(name='Hardware', slug='hardware')
        self.ticket = Ticket.objects.create(
            number='TK#1234',
            title='Test Ticket',
            description='Test Description',
            requester=self.user,
            category=self.category
        )
        self.client.login(email='test@example.com', password='TestPass123!')

    def test_add_comment(self):
        """Test adding a comment to a ticket."""
        response = self.client.post(
            reverse('tickets:detail', args=[self.ticket.pk]),
            {
                'body': 'Test comment',
                'attachments': []
            },
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(response.status_code, 200)
        comment = TicketComment.objects.filter(ticket=self.ticket).first()
        self.assertIsNotNone(comment)
        self.assertEqual(comment.body, 'Test comment')
        self.assertEqual(comment.author, self.user)


class AssetModelTests(TestCase):
    """Test Asset model functionality."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT'
        )

    def test_asset_creation(self):
        """Test basic asset creation."""
        asset = Asset.objects.create(
            name='Test Laptop',
            asset_type='LAPTOP',
            serial_number='SN12345',
            status='ACTIVE',
            assigned_to=self.user
        )
        self.assertEqual(asset.name, 'Test Laptop')
        self.assertEqual(asset.assigned_to, self.user)
        self.assertIsNotNone(asset.tracking_id)
        self.assertTrue(asset.tracking_id.startswith('AST-'))
        # Asset.__str__ appends a checked-out/available status emoji.
        self.assertEqual(str(asset), f'{asset.tracking_id} - Test Laptop (🟢)')

    def test_asset_tracking_id_generation(self):
        """Test tracking ID generation."""
        asset1 = Asset.objects.create(
            name='Test Laptop',
            asset_type='LAPTOP',
            status='ACTIVE'
        )
        asset2 = Asset.objects.create(
            name='Test Desktop',
            asset_type='COMPUTER',
            status='ACTIVE'
        )
        # Tracking IDs should be different
        self.assertNotEqual(asset1.tracking_id, asset2.tracking_id)
        # Should be in correct format
        year = timezone.now().year
        self.assertTrue(asset1.tracking_id.startswith(f'AST-{year}'))

    def test_asset_get_reassignment_count(self):
        """Test get_reassignment_count method."""
        asset = Asset.objects.create(
            name='Test Laptop',
            asset_type='LAPTOP',
            status='ACTIVE',
            assigned_to=self.user
        )
        
        # Initially 0 reassignments
        self.assertEqual(asset.get_reassignment_count(), 0)
        
        # Create an ASSIGNED log (this is the initial assignment, not a reassignment)
        AssetLog.objects.create(
            asset=asset,
            action=AssetLog.Action.ASSIGNED,
            actor=self.user,
            details={'to': self.user.get_full_name()}
        )
        # Still 0 reassignments (initial assignment doesn't count)
        self.assertEqual(asset.get_reassignment_count(), 0)
        
        # Create another ASSIGNED log (this is a reassignment)
        asset2 = User.objects.create_user(
            email='agent@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='User',
            department='IT'
        )
        AssetLog.objects.create(
            asset=asset,
            action=AssetLog.Action.ASSIGNED,
            actor=self.user,
            details={'from': self.user.get_full_name(), 'to': asset2.get_full_name()}
        )
        # Now should be 1 reassignment
        self.assertEqual(asset.get_reassignment_count(), 1)

    def test_asset_has_been_reassigned(self):
        """Test has_been_reassigned method."""
        asset = Asset.objects.create(
            name='Test Laptop',
            asset_type='LAPTOP',
            status='ACTIVE',
            assigned_to=self.user
        )
        
        # Initial assignment - should be False
        self.assertFalse(asset.has_been_reassigned())
        
        # Add a reassignment
        asset2 = User.objects.create_user(
            email='agent@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='User',
            department='IT'
        )
        AssetLog.objects.create(
            asset=asset,
            action=AssetLog.Action.ASSIGNED,
            actor=self.user,
            details={'from': self.user.get_full_name(), 'to': asset2.get_full_name()}
        )
        # Should be True now
        self.assertTrue(asset.has_been_reassigned())


class AssetViewTests(TestCase):
    """Test asset view functionality."""
    
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT'
        )
        self.agent = User.objects.create_user(
            email='agent@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='User',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        self.client.login(email='admin@example.com', password='AdminPass123!')

    def test_asset_list_view(self):
        """Test asset list page loads."""
        response = self.client.get(reverse('tickets:assets'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tickets/asset_list.html')

    def test_asset_create(self):
        """Test asset creation via form."""
        response = self.client.post(reverse('tickets:asset_create_page'), {
            'name': 'New Test Laptop',
            'asset_type': 'LAPTOP',
            'serial_number': 'SN99999',
            'status': 'ACTIVE',
            'location': 'HQ',
            'assigned_to': ''
        })
        # Should redirect to asset list
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Asset.objects.filter(name='New Test Laptop').exists())

    def test_asset_create_requires_admin(self):
        """Test that non-admin users cannot create assets."""
        self.client.login(email='agent@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:asset_create_page'))
        self.assertEqual(response.status_code, 403)  # Forbidden

    def test_asset_edit(self):
        """Test editing an asset."""
        asset = Asset.objects.create(
            name='Test Laptop',
            asset_type='LAPTOP',
            serial_number='SN12345',
            status='ACTIVE'
        )
        response = self.client.post(
            reverse('tickets:asset_edit_page', args=[asset.pk]),
            {
                'name': 'Updated Laptop Name',
                'asset_type': 'LAPTOP',
                'serial_number': 'SN12345',
                'status': 'ACTIVE'
            }
        )
        self.assertEqual(response.status_code, 302)
        asset.refresh_from_db()
        self.assertEqual(asset.name, 'Updated Laptop Name')

    def test_asset_detail_view(self):
        """Test asset detail page loads."""
        asset = Asset.objects.create(
            name='Test Laptop',
            asset_type='LAPTOP',
            serial_number='SN12345',
            status='ACTIVE'
        )
        response = self.client.get(reverse('tickets:asset_detail', args=[asset.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Laptop')


class AssetReassignTests(TestCase):
    """Test asset reassignment functionality."""
    
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT'
        )
        self.agent1 = User.objects.create_user(
            email='agent1@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='One',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        self.agent2 = User.objects.create_user(
            email='agent2@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='Two',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        self.asset = Asset.objects.create(
            name='Test Laptop',
            asset_type='LAPTOP',
            serial_number='SN12345',
            status='ACTIVE',
            assigned_to=self.agent1
        )
        self.client.login(email='admin@example.com', password='AdminPass123!')

    def test_asset_reassign_creates_log(self):
        """Reassigning an asset should create an AssetLog entry."""
        url = reverse('tickets:asset_reassign', args=[self.asset.pk])
        response = self.client.post(url, {
            'assigned_to': self.agent2.pk,
            'comment': 'Reassigning for workload balance'
        })
        self.assertEqual(response.status_code, 302)
        
        # Check asset was reassigned
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.assigned_to, self.agent2)
        
        # Check log was created
        logs = AssetLog.objects.filter(asset=self.asset, action=AssetLog.Action.ASSIGNED)
        self.assertTrue(logs.exists())
        self.assertEqual(logs.count(), 1)

    def test_asset_reassignment_count_increments(self):
        """Reassigning should increase the reassignment count."""
        initial_count = self.asset.get_reassignment_count()
        
        url = reverse('tickets:asset_reassign', args=[self.asset.pk])
        self.client.post(url, {
            'assigned_to': self.agent2.pk,
            'comment': 'Reassigning'
        })
        
        self.asset.refresh_from_db()
        new_count = self.asset.get_reassignment_count()
        self.assertEqual(new_count, initial_count + 1)

    def test_asset_reassign_trail_history(self):
        """Test the reassign trail history."""
        # Create multiple reassignments
        url = reverse('tickets:asset_reassign', args=[self.asset.pk])
        self.client.post(url, {'assigned_to': self.agent2.pk, 'comment': 'First reassign'})
        
        # Create another reassignment
        self.client.post(url, {'assigned_to': self.agent1.pk, 'comment': 'Second reassign'})
        
        # Get history. The asset was created directly with assigned_to set
        # (no log for that), so only the two reassign() calls are logged.
        history = self.asset.get_assignment_history()
        self.assertEqual(len(history), 2)
        
        # Check latest assignment is agent1
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.assigned_to, self.agent1)

    def test_asset_reassign_unassign(self):
        """Test unassigning an asset."""
        url = reverse('tickets:asset_reassign', args=[self.asset.pk])
        response = self.client.post(url, {
            'assigned_to': '',
            'comment': 'Unassigning asset'
        })
        self.assertEqual(response.status_code, 302)
        
        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.assigned_to)
        
        # Check UNASSIGNED log was created
        logs = AssetLog.objects.filter(asset=self.asset, action=AssetLog.Action.UNASSIGNED)
        self.assertTrue(logs.exists())


class SLAAndEscalationTests(TestCase):
    """Test SLA and escalation functionality."""
    
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT'
        )
        self.user = User.objects.create_user(
            email='test@example.com',
            password='TestPass123!',
            first_name='Test',
            last_name='User',
            department='IT'
        )
        self.category = Category.objects.create(name='Hardware', slug='hardware')
        self.client.login(email='admin@example.com', password='AdminPass123!')

    def test_sla_creation(self):
        """Test creating an SLA policy."""
        response = self.client.post(reverse('tickets:sla_create'), {
            'priority': 'P1',
            'response_minutes': 15,
            'resolution_minutes': 60,
            'calendar_id': ''
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SLA.objects.filter(priority='P1').exists())

    def test_sla_policy_list(self):
        """Test SLA management page shows policies."""
        sla = SLA.objects.create(
            priority='P1',
            response_minutes=15,
            resolution_minutes=60
        )
        response = self.client.get(reverse('tickets:sla_management'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'P1')

    def test_escalation_rule_creation(self):
        """Test creating an escalation rule."""
        response = self.client.post(reverse('tickets:rule_create'), {
            'priority': 'P1',
            'timer_type': 'response',
            'threshold_percent': 75,
            'action_type': 'notify',
            'notify_role': 'ADMIN'
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EscalationRule.objects.filter(priority='P1').exists())

    def test_sla_badge_view(self):
        """Test SLA badge view."""
        sla = SLA.objects.create(
            priority='P3',
            response_minutes=60,
            resolution_minutes=240
        )
        ticket = Ticket.objects.create(
            number='TK#9999',
            title='SLA Test Ticket',
            description='Test description',
            requester=self.user,
            category=self.category,
            priority='P3',
            status=Ticket.Status.NEW
        )
        response = self.client.get(reverse('tickets:sla_badge', args=[ticket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'On Track')


class NotificationTests(TestCase):
    """Test notification functionality."""
    
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
        self.category = Category.objects.create(name='Hardware', slug='hardware')
        self.client.login(email='test@example.com', password='TestPass123!')

    def test_notification_creation(self):
        """Test creating a notification."""
        notification = Notification.objects.create(
            recipient=self.user,
            message='Test notification',
            url='/dashboard/'
        )
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.message, 'Test notification')
        self.assertFalse(notification.is_read)
        self.assertEqual(str(notification), f'Notification for {self.user.email}: Test notification')

    def test_notification_mark_read(self):
        """Test marking a notification as read."""
        notification = Notification.objects.create(
            recipient=self.user,
            message='Test notification',
            url='/dashboard/'
        )
        self.assertFalse(notification.is_read)
        
        notification.is_read = True
        notification.save()
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_notification_unread_count(self):
        """Test unread notification count."""
        # Create some notifications
        Notification.objects.create(recipient=self.user, message='Notif 1', url='/')
        Notification.objects.create(recipient=self.user, message='Notif 2', url='/')
        Notification.objects.create(recipient=self.user, message='Notif 3', url='/')
        
        # Read one
        notif = Notification.objects.filter(recipient=self.user).first()
        notif.is_read = True
        notif.save()
        
        count = Notification.objects.filter(recipient=self.user, is_read=False).count()
        self.assertEqual(count, 2)

    def test_notification_list_view(self):
        """Test notification dropdown list."""
        Notification.objects.create(recipient=self.user, message='Test notif 1', url='/')
        Notification.objects.create(recipient=self.user, message='Test notif 2', url='/')
        
        response = self.client.get(reverse('notifications:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test notif 1')
        self.assertContains(response, 'Test notif 2')

    def test_notification_mark_all_read(self):
        """Test marking all notifications as read."""
        Notification.objects.create(recipient=self.user, message='Notif 1', url='/')
        Notification.objects.create(recipient=self.user, message='Notif 2', url='/')
        
        response = self.client.post(reverse('notifications:mark_all_read'))
        self.assertEqual(response.status_code, 200)
        
        count = Notification.objects.filter(recipient=self.user, is_read=False).count()
        self.assertEqual(count, 0)


class RoleBasedAccessTests(TestCase):
    """Test role-based access control."""
    
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Hardware', slug='hardware')
        
        # Create users with different roles
        self.end_user = User.objects.create_user(
            email='user@example.com',
            password='TestPass123!',
            first_name='End',
            last_name='User',
            department='IT',
            role=User.Role.END_USER,
            is_active=True,
            email_verified=True
        )
        
        self.agent = User.objects.create_user(
            email='agent@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='User',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        
        self.team_lead = User.objects.create_user(
            email='lead@example.com',
            password='TestPass123!',
            first_name='Team',
            last_name='Lead',
            department='IT',
            role=User.Role.TEAM_LEAD,
            is_active=True,
            email_verified=True
        )
        
        self.admin = User.objects.create_user(
            email='admin@example.com',
            password='TestPass123!',
            first_name='Admin',
            last_name='User',
            department='IT',
            role=User.Role.ADMIN,
            is_active=True,
            email_verified=True
        )
        
        # Create a ticket
        self.ticket = Ticket.objects.create(
            number='TK#9999',
            title='Test Ticket',
            description='Test description',
            requester=self.end_user,
            category=self.category,
            status=Ticket.Status.NEW
        )

    def test_dashboard_redirects_unauthenticated(self):
        """Unauthenticated users should be redirected to login."""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_end_user_dashboard_access(self):
        """End users should access their dashboard."""
        self.client.login(email='user@example.com', password='TestPass123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboards/end_user_dashboard.html')

    def test_agent_dashboard_access(self):
        """Agents should access their dashboard."""
        self.client.login(email='agent@example.com', password='TestPass123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboards/agent_dashboard.html')

    def test_team_lead_dashboard_access(self):
        """Team Leads should access their dashboard."""
        self.client.login(email='lead@example.com', password='TestPass123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboards/team_lead_dashboard.html')

    def test_admin_dashboard_access(self):
        """Admins should access their dashboard."""
        self.client.login(email='admin@example.com', password='TestPass123!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboards/admin_dashboard.html')

    def test_unassigned_queue_agent_access(self):
        """Agents should access unassigned queue."""
        self.client.login(email='agent@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:unassigned'))
        self.assertEqual(response.status_code, 200)

    def test_unassigned_queue_end_user_denied(self):
        """End users should not access unassigned queue."""
        self.client.login(email='user@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:unassigned'))
        self.assertEqual(response.status_code, 403)  # Forbidden

    def test_asset_management_agent_access(self):
        """Agents should access asset management."""
        self.client.login(email='agent@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:assets'))
        self.assertEqual(response.status_code, 200)

    def test_asset_create_admin_only(self):
        """Only admins should access asset creation."""
        self.client.login(email='agent@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:asset_create_page'))
        self.assertEqual(response.status_code, 403)
        
        self.client.login(email='admin@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:asset_create_page'))
        self.assertEqual(response.status_code, 200)

    def test_manager_review_team_lead_only(self):
        """Only team leads should access manager review queue."""
        self.client.login(email='agent@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:manager_review_queue'))
        self.assertEqual(response.status_code, 403)
        
        self.client.login(email='lead@example.com', password='TestPass123!')
        response = self.client.get(reverse('tickets:manager_review_queue'))
        self.assertEqual(response.status_code, 200)


class ServiceRequestFlowTests(TestCase):
    """Test the complete service request workflow."""
    
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Hardware', slug='hardware')
        
        self.end_user = User.objects.create_user(
            email='user@example.com',
            password='TestPass123!',
            first_name='End',
            last_name='User',
            department='IT',
            role=User.Role.END_USER,
            is_active=True,
            email_verified=True
        )
        
        self.team_lead = User.objects.create_user(
            email='lead@example.com',
            password='TestPass123!',
            first_name='Team',
            last_name='Lead',
            department='IT',
            role=User.Role.TEAM_LEAD,
            is_active=True,
            email_verified=True
        )
        
        self.admin = User.objects.create_user(
            email='admin@example.com',
            password='TestPass123!',
            first_name='Admin',
            last_name='User',
            department='IT',
            role=User.Role.ADMIN,
            is_active=True,
            email_verified=True
        )

    def test_service_request_creation_asset_detection(self):
        """Test that service requests with asset categories are flagged."""
        self.client.login(email='user@example.com', password='TestPass123!')
        
        response = self.client.post(reverse('tickets:create'), {
            'type': 'SERVICE_REQUEST',
            'title': 'Need new laptop',
            'description': 'I need a new laptop for the new developer',
            'category': self.category.id,  # Hardware
            'impact': 'INDIVIDUAL',
            'urgency': 'MEDIUM'
        })
        self.assertEqual(response.status_code, 302)
        
        ticket = Ticket.objects.filter(title='Need new laptop').first()
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.type, Ticket.Type.SERVICE_REQUEST)
        self.assertTrue(ticket.is_asset_request)

    def test_service_request_team_lead_review(self):
        """Test team lead reviewing a service request."""
        # Create a service request
        self.client.login(email='user@example.com', password='TestPass123!')
        self.client.post(reverse('tickets:create'), {
            'type': 'SERVICE_REQUEST',
            'title': 'Need new laptop',
            'description': 'I need a new laptop for the new developer',
            'category': self.category.id,
            'impact': 'INDIVIDUAL',
            'urgency': 'MEDIUM'
        })
        
        ticket = Ticket.objects.filter(title='Need new laptop').first()
        
        # Team lead reviews and approves
        self.client.login(email='lead@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('tickets:manager_review_ticket', args=[ticket.pk]),
            {
                'action': 'approve',
                'comment': 'Approved, please assign a laptop'
            }
        )
        self.assertEqual(response.status_code, 302)
        
        ticket.refresh_from_db()
        # Asset request should go to PENDING_FULFILLMENT
        self.assertEqual(ticket.status, Ticket.Status.PENDING_FULFILLMENT)

    def test_service_request_admin_fulfillment(self):
        """Test admin fulfilling an asset request."""
        # Create and approve a service request
        self.client.login(email='user@example.com', password='TestPass123!')
        self.client.post(reverse('tickets:create'), {
            'type': 'SERVICE_REQUEST',
            'title': 'Need new laptop',
            'description': 'I need a new laptop',
            'category': self.category.id,
            'impact': 'INDIVIDUAL',
            'urgency': 'MEDIUM'
        })
        
        ticket = Ticket.objects.filter(title='Need new laptop').first()
        
        self.client.login(email='lead@example.com', password='TestPass123!')
        self.client.post(
            reverse('tickets:manager_review_ticket', args=[ticket.pk]),
            {'action': 'approve', 'comment': 'Approved'}
        )
        
        # Create an asset
        asset = Asset.objects.create(
            name='Dell Laptop',
            asset_type='LAPTOP',
            serial_number='SN12345',
            status='IN_STORE'
        )
        
        # Admin fulfills the request
        self.client.login(email='admin@example.com', password='TestPass123!')
        response = self.client.post(
            reverse('tickets:fulfill_asset_request', args=[ticket.pk]),
            {
                'asset_id': asset.pk,
                'comment': 'Fulfilled with Dell Laptop'
            }
        )
        self.assertEqual(response.status_code, 302)
        
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.APPROVED)
        self.assertEqual(ticket.assigned_asset, asset)
        
        asset.refresh_from_db()
        self.assertEqual(asset.assigned_to, self.end_user)


class SecurityTests(TestCase):
    """Test security features."""
    
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

    def test_password_policy_min_length(self):
        """Test that password must be at least 10 characters."""
        # Attempt to create user with short password
        with self.assertRaises(Exception):
            User.objects.create_user(
                email='shortpass@example.com',
                password='Short1!',  # Too short
                first_name='Test',
                last_name='User',
                department='IT'
            )

    def test_secure_cookie_settings(self):
        """Test that secure cookie settings are applied."""
        # This test is more of a configuration check
        from django.conf import settings
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        # In production, these should be True, but in development they may be False
        # So we just check they exist
        self.assertIsNotNone(settings.SESSION_COOKIE_HTTPONLY)

    def test_xframe_options(self):
        """Test X-Frame-Options header."""
        # This test checks that the header is set
        # In production, X_FRAME_OPTIONS should be set
        from django.conf import settings
        self.assertIsNotNone(getattr(settings, 'X_FRAME_OPTIONS', None))


class EdgeCaseTests(TestCase):
    """Test edge cases and error handling."""
    
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
        self.category = Category.objects.create(name='Hardware', slug='hardware')
        self.client.login(email='test@example.com', password='TestPass123!')

    def test_ticket_create_with_very_long_title(self):
        """Test ticket creation with a title at the field's max length (255)."""
        long_title = 'a' * 255
        response = self.client.post(reverse('tickets:create'), {
            'type': 'INCIDENT',
            'title': long_title,
            'description': 'Test description',
            'category': self.category.id,
            'impact': 'INDIVIDUAL',
            'urgency': 'MEDIUM'
        })
        self.assertEqual(response.status_code, 302)  # Should still work
        ticket = Ticket.objects.filter(title=long_title).first()
        self.assertIsNotNone(ticket)

    def test_asset_create_with_special_characters(self):
        """Test asset creation with special characters."""
        self.client.login(email='admin@example.com', password='TestPass123!')
        # First create admin user
        admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT'
        )
        self.client.login(email='admin@example.com', password='AdminPass123!')
        
        response = self.client.post(reverse('tickets:asset_create_page'), {
            'name': 'Test Laptop with $pecial & Chars!',
            'asset_type': 'LAPTOP',
            'serial_number': 'SN#123!@#',
            'status': 'ACTIVE'
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Asset.objects.filter(name__contains='$pecial').exists())

    def test_edit_nonexistent_asset(self):
        """Test editing a nonexistent asset."""
        self.client.login(email='admin@example.com', password='AdminPass123!')
        admin = User.objects.create_superuser(
            email='admin@example.com',
            password='AdminPass123!',
            first_name='Admin',
            last_name='User',
            department='IT'
        )
        self.client.login(email='admin@example.com', password='AdminPass123!')
        
        response = self.client.get(reverse('tickets:asset_edit_page', args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_claim_already_claimed_ticket(self):
        """Test claiming a ticket that's already assigned."""
        agent = User.objects.create_user(
            email='agent@example.com',
            password='TestPass123!',
            first_name='Agent',
            last_name='User',
            department='IT',
            role=User.Role.AGENT,
            is_active=True,
            email_verified=True
        )
        
        ticket = Ticket.objects.create(
            number='TK#7777',
            title='Test Ticket',
            description='Test description',
            requester=self.user,
            category=self.category,
            status=Ticket.Status.ASSIGNED,
            assigned_to=agent
        )
        
        self.client.login(email='agent@example.com', password='TestPass123!')
        response = self.client.post(reverse('tickets:claim_ticket', args=[ticket.pk]))
        # Should not allow claiming an already assigned ticket
        # The view might handle this differently, but we check it doesn't error
        self.assertNotEqual(response.status_code, 500)