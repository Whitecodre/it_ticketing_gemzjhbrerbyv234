# apps/tickets/management/commands/process_sla.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.tickets.models import Ticket, TicketComment, TicketActivityLog, EscalationRule, SLA
from apps.common.models import Notification
from apps.common.utils import role_of
from apps.common.permissions import effective_role_name
from django.db.models import Q

User = get_user_model()

OPEN_STATUSES = [
    Ticket.Status.NEW,
    Ticket.Status.TRIAGED,
    Ticket.Status.ASSIGNED,
    Ticket.Status.IN_PROGRESS,
    Ticket.Status.PENDING_USER,
    Ticket.Status.PENDING_VENDOR,
]


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

        # Every open ticket that has at least one SLA timer running — not
        # just ones that have already breached, since threshold rules
        # (75%/90%) need to fire *before* the 100% breach, not alongside it.
        tickets = Ticket.objects.filter(
            status__in=OPEN_STATUSES
        ).filter(
            Q(response_due_at__isnull=False) | Q(resolution_due_at__isnull=False)
        )

        self.stdout.write(f'🔍 Evaluating {tickets.count()} open ticket(s) with SLA timers')

        for ticket in tickets:
            self.process_ticket(ticket, now, system_user)

    def process_ticket(self, ticket, now, system_user):
        """Evaluate both SLA timers on a ticket against their escalation
        rules' thresholds (percent of the timer's window elapsed), firing
        each rule at most once, then handle a full (100%) breach separately
        once per timer type."""

        for timer_type, due_at in (
            ('response', ticket.response_due_at),
            ('resolution', ticket.resolution_due_at),
        ):
            if not due_at or not ticket.created_at:
                continue

            window_seconds = (due_at - ticket.created_at).total_seconds()
            if window_seconds <= 0:
                continue

            elapsed_percent = (now - ticket.created_at).total_seconds() / window_seconds * 100

            self.fire_threshold_rules(ticket, timer_type, elapsed_percent, system_user)

            if elapsed_percent >= 100:
                self.handle_full_breach(ticket, timer_type, now, system_user)

    def fire_threshold_rules(self, ticket, timer_type, elapsed_percent, system_user):
        """Run every EscalationRule for this priority/timer whose threshold
        has been reached, skipping ones already fired for this ticket."""
        rules = EscalationRule.objects.filter(
            priority=ticket.priority,
            timer_type=timer_type,
        ).order_by('threshold_percent')

        if not rules.exists() and timer_type == 'response':
            self.stdout.write(f'   ⚠️ No response escalation rules for {ticket.priority}, creating defaults...')
            self.create_default_escalation_rules(ticket.priority)
            rules = EscalationRule.objects.filter(priority=ticket.priority, timer_type=timer_type)

        for rule in rules:
            if elapsed_percent < rule.threshold_percent:
                continue
            if self.rule_already_fired(ticket, rule):
                continue

            self.execute_escalation(ticket, rule, system_user)
            TicketActivityLog.objects.create(
                ticket=ticket,
                action='escalation_rule_fired',
                actor=system_user,
                details={
                    'rule_id': rule.pk,
                    'timer_type': timer_type,
                    'threshold_percent': rule.threshold_percent,
                    'elapsed_percent': round(elapsed_percent, 1),
                }
            )
            self.stdout.write(
                f'   ⏰ Ticket {ticket.number}: fired {rule.action_type} rule '
                f'at {rule.threshold_percent}% of {timer_type} ({elapsed_percent:.0f}% elapsed)'
            )

    def rule_already_fired(self, ticket, rule):
        return TicketActivityLog.objects.filter(
            ticket=ticket,
            action='escalation_rule_fired',
            details__rule_id=rule.pk,
        ).exists()

    def handle_full_breach(self, ticket, timer_type, now, system_user):
        """Once a timer fully breaches (100%): post a comment and, for the
        response timer on an unassigned ticket, auto-assign or escalate.
        Runs once per ticket per timer_type, regardless of how many
        threshold rules also fired above."""
        already_breached = TicketActivityLog.objects.filter(
            ticket=ticket,
            action='breached',
            details__timer_type=timer_type,
        ).exists()
        if already_breached:
            return

        self.stdout.write(f'⏰ Ticket {ticket.number} breached its {timer_type} SLA!')

        comment_body = f"**Auto-escalated** due to SLA breach ({timer_type} timer exceeded)."
        TicketComment.objects.create(
            ticket=ticket,
            author=system_user,
            body=comment_body,
            visibility=TicketComment.Visibility.PUBLIC
        )

        TicketActivityLog.objects.create(
            ticket=ticket,
            action='breached',
            actor=system_user,
            details={
                'timer_type': timer_type,
                'response_due': str(ticket.response_due_at),
                'resolution_due': str(ticket.resolution_due_at),
                'now': str(now),
            }
        )

        if timer_type == 'response' and not ticket.assigned_to:
            agent = self.find_available_agent()
            if agent:
                ticket.assigned_to = agent
                ticket.status = Ticket.Status.ASSIGNED
                ticket.save()
                self.stdout.write(f'   ✅ Assigned to {agent.get_full_name()}')

                Notification.objects.create(
                    recipient=agent,
                    role=role_of(agent),
                    message=f"⚠️ Ticket {ticket.number} has been auto-assigned to you due to SLA breach.",
                    url=f'/tickets/{ticket.pk}/',
                    type=Notification.Type.TICKET
                )
            else:
                ticket.status = Ticket.Status.ESCALATED
                ticket.save()
                self.stdout.write(f'   ⚠️ No agent available, ticket escalated')

    def create_default_escalation_rules(self, priority):
        """Create default response-timer escalation rules for a priority."""
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

        agents = [
            u for u in User.objects.filter(is_active=True)
            if effective_role_name(u) in ('AGENT', 'TEAM_LEAD')
        ]
        if not agents:
            return None
        agents_qs = User.objects.filter(pk__in=[u.pk for u in agents]).annotate(
            open_tickets=Count('assigned_tickets', filter=~Q(assigned_tickets__status__in=['RESOLVED', 'CLOSED']))
        ).order_by('open_tickets')

        return agents_qs.first()

    def execute_escalation(self, ticket, rule, system_user):
        """Execute an escalation action."""
        action_type = rule.action_type

        if action_type == 'notify':
            if rule.notify_role:
                users = [
                    u for u in User.objects.filter(is_active=True)
                    if effective_role_name(u) == rule.notify_role
                ]
                for user in users:
                    Notification.objects.create(
                        recipient=user,
                        role=role_of(user),
                        message=f"⚠️ Ticket {ticket.number} has been escalated. Please review.",
                        url=f'/tickets/{ticket.pk}/',
                        type=Notification.Type.TICKET
                    )
                self.stdout.write(f'   📧 Notified {len(users)} {rule.notify_role}(s)')

        elif action_type == 'reassign':
            if rule.reassign_to_role:
                users = [
                    u for u in User.objects.filter(is_active=True)
                    if effective_role_name(u) == rule.reassign_to_role
                ]
                if users:
                    new_assignee = users[0]
                    ticket.assigned_to = new_assignee
                    ticket.save()

                    Notification.objects.create(
                        recipient=new_assignee,
                        role=role_of(new_assignee),
                        message=f"🔄 Ticket {ticket.number} has been auto-reassigned to you due to SLA breach.",
                        url=f'/tickets/{ticket.pk}/',
                        type=Notification.Type.TICKET
                    )
                    self.stdout.write(f'   🔄 Reassigned to {new_assignee.get_full_name()}')
