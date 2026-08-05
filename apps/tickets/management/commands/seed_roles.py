from django.core.management.base import BaseCommand
from apps.accounts.models import Role

class Command(BaseCommand):
    help = 'Seed default roles for the dual-role system'

    def handle(self, *args, **options):
        if Role.objects.exists():
            self.stdout.write(self.style.WARNING('⚠️ Roles already exist. Skipping seeding.'))
            return
        
        default_roles = [
            {'name': 'SUPERADMIN', 'display_name': 'Super Admin', 'priority': 1},
            {'name': 'ADMIN', 'display_name': 'Admin', 'priority': 2},
            {'name': 'TEAM_LEAD', 'display_name': 'Team Lead', 'priority': 3},
            {'name': 'AGENT', 'display_name': 'Support Team', 'priority': 4},
            {'name': 'END_USER', 'display_name': 'User', 'priority': 5},
        ]
        
        for role_data in default_roles:
            Role.objects.create(**role_data)
            self.stdout.write(self.style.SUCCESS(f'✅ Created role: {role_data["display_name"]}'))
        
        self.stdout.write(self.style.SUCCESS('🎉 All roles created successfully!'))