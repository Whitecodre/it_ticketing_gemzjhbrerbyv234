# apps/tickets/management/commands/check_sla_results.py

from django.core.management.base import BaseCommand
from apps.tickets.models import Ticket, TicketComment, TicketActivityLog

class Command(BaseCommand):
    help = 'Check results of SLA processing'

    def handle(self, *args, **options):
        self.stdout.write('📊 Checking SLA test results...')
        self.stdout.write('')
        
        # Check all test tickets
        for number in ['SLA-TEST-001', 'SLA-TEST-002', 'SLA-TEST-003']:
            try:
                ticket = Ticket.objects.get(number=number)
                self.stdout.write(f'📌 {number}:')
                self.stdout.write(f'   Status: {ticket.get_status_display()}')
                self.stdout.write(f'   Assigned: {ticket.assigned_to.get_full_name() if ticket.assigned_to else "Unassigned"}')
                
                # Check for escalation comments
                comments = TicketComment.objects.filter(ticket=ticket)
                escalation_comments = [c for c in comments if 'Auto-escalated' in c.body]
                
                if escalation_comments:
                    self.stdout.write(self.style.SUCCESS('   ✅ ESCALATED - SLA breach detected'))
                    for comment in escalation_comments:
                        self.stdout.write(f'      {comment.body[:80]}...')
                        self.stdout.write(f'      Author: {comment.author} at {comment.created_at.strftime("%H:%M:%S")}')
                else:
                    self.stdout.write(self.style.WARNING('   ⚠️ No escalation yet (SLA may not have breached)'))
                
                # Check activity logs
                logs = TicketActivityLog.objects.filter(ticket=ticket, action='escalated')
                if logs:
                    self.stdout.write(f'   📝 {logs.count()} escalation log entries')
                
                self.stdout.write('')
                
            except Ticket.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'⚠️ Ticket {number} not found'))
                self.stdout.write('')