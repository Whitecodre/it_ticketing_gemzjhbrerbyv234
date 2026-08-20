# apps/accounts/management/commands/fix_user_roles.py

from django.core.management.base import BaseCommand
from django.db.models import Q
from apps.accounts.models import User


class Command(BaseCommand):
    help = 'Fix users outside IT department who have IT-only roles (AGENT/ADMIN/SUPERADMIN)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        # TEAM_LEAD is intentionally excluded: it's the departmental approval
        # gate and is valid in any department, not just IT.
        it_only_roles = ['AGENT', 'ADMIN', 'SUPERADMIN']

        # Find affected users
        affected_users = User.objects.filter(
            ~Q(department='IT'),
            role__in=it_only_roles
        )

        count = affected_users.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('✅ No users found outside IT with IT-only roles.'))
            return

        self.stdout.write(self.style.WARNING(f'🔍 Found {count} users outside IT with IT-only roles:'))
        
        for user in affected_users:
            self.stdout.write(f'  - {user.email} ({user.get_full_name()}) - Dept: {user.department}, Role: {user.role}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'\n⚠️ DRY RUN: Would update {count} users to END_USER'))
            return
        
        # Perform the update
        updated_count = affected_users.update(role='END_USER')
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Updated {updated_count} users to END_USER'))
        
        # Verify
        remaining = User.objects.filter(
            ~Q(department='IT'),
            role__in=it_only_roles
        ).count()
        self.stdout.write(self.style.SUCCESS(f'✅ Remaining users outside IT with IT-only roles: {remaining}'))