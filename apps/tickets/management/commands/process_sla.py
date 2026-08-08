# apps/tickets/management/commands/process_sla.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.tickets.models import Ticket, TicketComment, TicketActivityLog, EscalationRule, SLA
from apps.common.models import Notification
from django.db.models import Q

User = get_user_model()

class Command(BaseCommand):
    help = 'Process SLA breaches and escalate tickets'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Get or create a system user
        system_user, created = User.objects.get_or_create(
            email='system@ticketswipe.local',
            defaults={
                'first_name': 'System',
                'last_name': 'Bot',
                'role': User.Role.AGENT,
                'department': 'IT',
                'is_active': True,
                'is_staff': False,
            }
        )
        if created:
            system_user.set_password(User.objects.make_random_password())
            system_user.save()
            self.stdout.write(self.style.SUCCESS('✅ Created system user for automated actions'))
        
        # Find all open tickets with SLA breaches
        # Include tickets where:
        # - Status is open
        # - Has a response_due_at or resolution_due_at
        # - The due date has passed
        tickets = Ticket.objects.filter(
            status__in=[
                Ticket.Status.NEW,
                Ticket.Status.TRIAGED,
                Ticket.Status.ASSIGNED,
                Ticket.Status.IN_PROGRESS,
                Ticket.Status.PENDING_USER,
                Ticket.Status.PENDING_VENDOR,
            ]
        ).filter(
            Q(response_due_at__lt=now) | Q(resolution_due_at__lt=now)
        )
        
        self.stdout.write(f'🔍 Found {tickets.count()} tickets with SLA breaches')
        
        for ticket in tickets:
            self.process_ticket(ticket, now, system_user)
    
    def process_ticket(self, ticket, now, system_user):
        """Process a single ticket for SLA breaches."""
        
        # Check if already escalated
        escalated_logs = TicketActivityLog.objects.filter(
            ticket=ticket,
            action='escalated'
        )
        if escalated_logs.exists():
            # Already escalated, skip
            return
        
        self.stdout.write(f'⏰ Ticket {ticket.number} has SLA breach!')
        
        # Find the breach type
        breach_types = []
        if ticket.response_due_at and now > ticket.response_due_at:
            breach_types.append('response')
        if ticket.resolution_due_at and now > ticket.resolution_due_at:
            breach_types.append('resolution')
        
        # Get escalation rules for this priority
        rules = EscalationRule.objects.filter(
            priority=ticket.priority,
        ).order_by('threshold_percent')
        
        # If no escalation rules exist, create default ones
        if not rules.exists():
            self.stdout.write(f'   ⚠️ No escalation rules found for {ticket.priority}, creating defaults...')
            self.create_default_escalation_rules(ticket.priority)
            rules = EscalationRule.objects.filter(priority=ticket.priority)
        
        # Apply escalation rules
        for rule in rules:
            self.execute_escalation(ticket, rule, system_user)
        
        # Create escalation comment
        breach_type = " and ".join(breach_types)
        comment_body = f"**Auto-escalated** due to SLA breach ({breach_type} timer exceeded)."
        TicketComment.objects.create(
            ticket=ticket,
            author=system_user,
            body=comment_body,
            visibility=TicketComment.Visibility.PUBLIC
        )
        
        # Log the activity
        TicketActivityLog.objects.create(
            ticket=ticket,
            action='escalated',
            actor=system_user,
            details={
                'breach_types': breach_types,
                'response_due': str(ticket.response_due_at),
                'resolution_due': str(ticket.resolution_due_at),
                'now': str(now),
            }
        )
        
        # Find or assign an agent
        if not ticket.assigned_to:
            agent = self.find_available_agent()
            if agent:
                ticket.assigned_to = agent
                ticket.status = Ticket.Status.ASSIGNED
                ticket.save()
                self.stdout.write(f'   ✅ Assigned to {agent.get_full_name()}')
                
                Notification.objects.create(
                    recipient=agent,
                    message=f"⚠️ Ticket {ticket.number} has been auto-assigned to you due to SLA breach.",
                    url=f'/tickets/{ticket.pk}/',
                    type=Notification.Type.TICKET
                )
            else:
                ticket.status = Ticket.Status.ESCALATED
                ticket.save()
                self.stdout.write(f'   ⚠️ No agent available, ticket escalated')
        
        self.stdout.write(f'   ✅ Escalated ticket {ticket.number}')
    
    def create_default_escalation_rules(self, priority):
        """Create default escalation rules for a priority."""
        rules = [
            {'threshold_percent': 75, 'action_type': 'notify', 'notify_role': 'TEAM_LEAD'},
            {'threshold_percent': 90, 'action_type': 'notify', 'notify_role': 'ADMIN'},
            {'threshold_percent': 100, 'action_type': 'reassign', 'reassign_to_role': 'TEAM_LEAD'},
        ]
        
        for rule_data in rules:
            EscalationRule.objects.create(
                priority=priority,
                timer_type='response',
                threshold_percent=rule_data['threshold_percent'],
                action_type=rule_data['action_type'],
                notify_role=rule_data.get('notify_role'),
                reassign_to_role=rule_data.get('reassign_to_role'),
            )
        self.stdout.write(f'   ✅ Created {len(rules)} default escalation rules for {priority}')
    
    def find_available_agent(self):
        """Find an available agent with the fewest open tickets."""
        from django.db.models import Count
        
        agents = User.objects.filter(
            role__in=[User.Role.AGENT, User.Role.TEAM_LEAD],
            is_active=True
        ).annotate(
            open_tickets=Count('assigned_tickets', filter=~Q(assigned_tickets__status__in=['RESOLVED', 'CLOSED']))
        ).order_by('open_tickets')
        
        return agents.first()
    
    def execute_escalation(self, ticket, rule, system_user):
        """Execute an escalation action."""
        action_type = rule.action_type
        
        if action_type == 'notify':
            if rule.notify_role:
                users = User.objects.filter(role=rule.notify_role, is_active=True)
                for user in users:
                    Notification.objects.create(
                        recipient=user,
                        message=f"⚠️ Ticket {ticket.number} has been escalated. Please review.",
                        url=f'/tickets/{ticket.pk}/',
                        type=Notification.Type.TICKET
                    )
                self.stdout.write(f'   📧 Notified {users.count()} {rule.notify_role}(s)')
        
        elif action_type == 'reassign':
            if rule.reassign_to_role:
                users = User.objects.filter(role=rule.reassign_to_role, is_active=True)
                if users.exists():
                    new_assignee = users.first()
                    ticket.assigned_to = new_assignee
                    ticket.save()
                    
                    Notification.objects.create(
                        recipient=new_assignee,
                        message=f"🔄 Ticket {ticket.number} has been auto-reassigned to you due to SLA breach.",
                        url=f'/tickets/{ticket.pk}/',
                        type=Notification.Type.TICKET
                    )
                    self.stdout.write(f'   🔄 Reassigned to {new_assignee.get_full_name()}')