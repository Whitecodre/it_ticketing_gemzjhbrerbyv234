# apps/tickets/management/commands/process_remote_session_expiry.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse
from datetime import timedelta
from apps.tickets.models import RemoteSession, TicketComment, TicketActivityLog
from apps.common.models import Notification
from apps.common.utils import role_of

User = get_user_model()

EXPIRY_WINDOW = timedelta(hours=2)


class Command(BaseCommand):
    help = 'Expire remote session requests that have sat unanswered/unstarted for too long'

    def handle(self, *args, **options):
        # Guard every stdout.write behind verbosity (Windows' cp1252 console
        # codec can't encode the status emoji used here and in process_sla.py
        # — call_command('...', verbosity=0), as run_periodic_tasks uses,
        # avoids ever hitting that write at all).
        self.verbosity = options.get('verbosity', 1)
        now = timezone.now()
        cutoff = now - EXPIRY_WINDOW

        # Reuse the same system account process_sla.py uses for automated
        # actions, so every automated actor in this app is attributed
        # consistently rather than each command inventing its own.
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
            if self.verbosity > 0:
                self.stdout.write(self.style.SUCCESS('Created system user for automated actions'))

        # REQUESTED (never accepted/rejected) or ACCEPTED (accepted but the
        # agent never started it) for longer than the expiry window — either
        # way, nobody's acted on it and it's blocking a fresh request for the
        # same ticket (request_remote_session refuses a new one while any
        # REQUESTED/ACCEPTED/STARTED session exists).
        stale_sessions = RemoteSession.objects.filter(
            status__in=[RemoteSession.Status.REQUESTED, RemoteSession.Status.ACCEPTED],
            created_at__lt=cutoff,
        ).select_related('ticket', 'requester', 'agent')

        if self.verbosity > 0:
            self.stdout.write(f'Found {stale_sessions.count()} stale remote session(s)')

        for session in stale_sessions:
            self.expire_session(session, now, system_user)

    def expire_session(self, session, now, system_user):
        old_status = session.status
        session.status = RemoteSession.Status.EXPIRED
        session.save()

        ticket = session.ticket

        TicketComment.objects.create(
            ticket=ticket,
            author=system_user,
            body=f"Remote session request expired after {int(EXPIRY_WINDOW.total_seconds() // 3600)} hours without a response.",
            visibility='PUBLIC',
            is_system_generated=True,
            system_icon='monitor',
        )

        TicketActivityLog.objects.create(
            ticket=ticket,
            action='remote_session_status_change',
            actor=system_user,
            details={'from': old_status, 'to': RemoteSession.Status.EXPIRED, 'session_id': session.pk},
        )

        # Prompt the agent to send a new request — the old one no longer
        # blocks request_remote_session now that it's EXPIRED, not REQUESTED/
        # ACCEPTED/STARTED.
        # tickets:conversation (agent_ticket_conversation) is staff-only —
        # the requester needs the requester-facing tickets:detail view instead,
        # same split every other remote-session notification in views.py
        # already respects via remote_session_detail's own role branching.
        Notification.objects.create(
            recipient=session.agent,
            role=role_of(session.agent),
            message=f"Your remote session request for ticket {ticket.number} expired without a response. Send a new request?",
            url=reverse('tickets:conversation', args=[ticket.pk]),
            type=Notification.Type.REMOTE_SESSION,
        )
        Notification.objects.create(
            recipient=session.requester,
            role=role_of(session.requester),
            message=f"The remote session request for ticket {ticket.number} expired.",
            url=reverse('tickets:detail', args=[ticket.pk]),
            type=Notification.Type.REMOTE_SESSION,
        )

        if self.verbosity > 0:
            self.stdout.write(f'   Expired session {session.pk} for ticket {ticket.number}')
