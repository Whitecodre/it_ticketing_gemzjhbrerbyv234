# apps/tickets/management/commands/test_sla.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from apps.tickets.models import Ticket, SLA
from apps.accounts.models import User
from apps.tickets.views import apply_sla

class Command(BaseCommand):
    help = 'Create test tickets for SLA testing'

    def handle(self, *args, **options):
        self.stdout.write('🔧 Creating SLA test tickets...')
        
        # Get or create a test user
        user, _ = User.objects.get_or_create(
            email='test@ticketswipe.local',
            defaults={
                'first_name': 'Test',
                'last_name': 'User',
                'role': User.Role.END_USER,
                'department': 'IT',
                'is_active': True,
            }
        )
        
        # Check SLA policies exist
        if not SLA.objects.exists():
            self.stdout.write(self.style.WARNING('⚠️ No SLA policies found. Creating default policies...'))
            SLA.objects.create(priority='P1', response_minutes=15, resolution_minutes=60)
            SLA.objects.create(priority='P2', response_minutes=30, resolution_minutes=120)
            SLA.objects.create(priority='P3', response_minutes=60, resolution_minutes=240)
            SLA.objects.create(priority='P4', response_minutes=120, resolution_minutes=480)
        
        # Create test tickets
        test_cases = [
            {
                'number': 'SLA-TEST-001',
                'title': 'SLA Test - Response Breach (P1)',
                'priority': 'P1',
                'minutes_ago': 30,
                'expected_breach': True,
            },
            {
                'number': 'SLA-TEST-002',
                'title': 'SLA Test - No Breach Yet (P2)',
                'priority': 'P2',
                'minutes_ago': 10,
                'expected_breach': False,
            },
            {
                'number': 'SLA-TEST-003',
                'title': 'SLA Test - Resolution Breach (P3)',
                'priority': 'P3',
                'minutes_ago': 300,
                'expected_breach': True,
            },
        ]
        
        for case in test_cases:
            # Delete existing test tickets
            Ticket.objects.filter(number=case['number']).delete()
            
            # Calculate created_at time
            created_at = timezone.now() - timedelta(minutes=case['minutes_ago'])
            
            # Create ticket with the correct created_at
            ticket = Ticket.objects.create(
                number=case['number'],
                title=case['title'],
                description=f'Test ticket for SLA processing. Created {case["minutes_ago"]} minutes ago.',
                requester=user,
                priority=case['priority'],
                status='NEW',
                created_at=created_at,  # Set this directly
            )
            
            # Apply SLA to set due dates - this uses the created_at we just set
            apply_sla(ticket)
            
            # Refresh from DB
            ticket.refresh_from_db()
            
            self.stdout.write(f"📝 Created {case['number']}: {case['title']}")
            self.stdout.write(f"   Priority: {case['priority']}, Created: {case['minutes_ago']} minutes ago")
            self.stdout.write(f"   Created at: {ticket.created_at.strftime('%H:%M:%S')}")
            self.stdout.write(f"   Response due: {ticket.response_due_at.strftime('%H:%M:%S') if ticket.response_due_at else 'N/A'}")
            self.stdout.write(f"   Resolution due: {ticket.resolution_due_at.strftime('%H:%M:%S') if ticket.resolution_due_at else 'N/A'}")
            self.stdout.write(f"   Expected breach: {'✅ YES' if case['expected_breach'] else '❌ NO'}")
            self.stdout.write('')
        
        self.stdout.write(self.style.SUCCESS('✅ Test tickets created!'))
        self.stdout.write('')
        self.stdout.write('🔄 Run SLA processing: python manage.py run_periodic_tasks --once')
        self.stdout.write('📊 Check results: python manage.py check_sla_results')