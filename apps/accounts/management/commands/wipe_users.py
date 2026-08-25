# apps/accounts/management/commands/wipe_users.py

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import connection
from apps.common.models import Notification
from apps.tickets.models import (
    Ticket, TicketComment, Attachment, TicketActivityLog,
    AssetCheckoutHistory, AssetLog, AssetMaintenanceLog, Asset, AssetCategory
)
from apps.knowledge_base.models import Article, ArticleVersion, ArticleFeedback
from apps.maintenance.models import MaintenanceSchedule, MaintenanceActivityLog
from apps.accounts.models import ImpersonationLog, ImpersonationToken, ClientSettings

User = get_user_model()


class Command(BaseCommand):
    help = 'Wipe all users and related data from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--keep-superuser',
            action='store_true',
            help='Keep the first superuser found',
        )
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Skip confirmation prompt',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        keep_superuser = options.get('keep_superuser', False)
        skip_confirmation = options.get('yes', False)

        # Count users
        all_users = User.objects.all()
        total_users = all_users.count()

        if total_users == 0:
            self.stdout.write(self.style.WARNING('⚠️ No users found to delete.'))
            return

        # Separate superusers
        superusers = User.objects.filter(is_superuser=True)
        superuser_count = superusers.count()

        # Users to delete
        users_to_delete = all_users
        kept_superuser = None
        if keep_superuser and superuser_count > 0:
            kept_superuser = superusers.first()
            users_to_delete = all_users.exclude(pk=kept_superuser.pk)
            self.stdout.write(self.style.WARNING(
                f'🔒 Keeping superuser: {kept_superuser.email}'
            ))

        delete_count = users_to_delete.count()

        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write(self.style.WARNING('⚠️  WARNING: This will delete all user data!'))
        self.stdout.write(self.style.WARNING('=' * 60))
        self.stdout.write(f'📊 Total users: {total_users}')
        self.stdout.write(f'📊 Superusers: {superuser_count}')
        self.stdout.write(f'📊 Users to delete: {delete_count}')
        self.stdout.write('')

        # Count related data
        self.stdout.write('📊 Related data to be deleted:')
        self.stdout.write(f'   - Tickets: {Ticket.objects.count()}')
        self.stdout.write(f'   - Comments: {TicketComment.objects.count()}')
        self.stdout.write(f'   - Attachments: {Attachment.objects.count()}')
        self.stdout.write(f'   - Activity Logs: {TicketActivityLog.objects.count()}')
        self.stdout.write(f'   - Asset Checkout History: {AssetCheckoutHistory.objects.count()}')
        self.stdout.write(f'   - Asset Logs: {AssetLog.objects.count()}')
        self.stdout.write(f'   - Assets: {Asset.objects.count()}')
        self.stdout.write(f'   - Notifications: {Notification.objects.count()}')
        self.stdout.write(f'   - Articles: {Article.objects.count()}')
        self.stdout.write(f'   - Maintenance Schedules: {MaintenanceSchedule.objects.count()}')
        self.stdout.write(f'   - Impersonation Logs: {ImpersonationLog.objects.count()}')
        self.stdout.write('')

        if dry_run:
            self.stdout.write(self.style.WARNING('⚠️  DRY RUN - No changes were made'))
            return

        if not skip_confirmation:
            confirm = input('⚠️  Are you sure you want to delete ALL user data? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write(self.style.WARNING('❌ Cancelled.'))
                return

        # Perform deletion
        self.stdout.write('🔄 Deleting data...')

        try:
            # Delete in correct order to avoid foreign key issues

            # 1. Impersonation Tokens (references users)
            ImpersonationToken.objects.all().delete()
            self.stdout.write('   ✅ Deleted Impersonation Tokens')

            # 2. Impersonation Logs (references users)
            ImpersonationLog.objects.all().delete()
            self.stdout.write('   ✅ Deleted Impersonation Logs')

            # 3. Client Settings (references users via updated_by)
            ClientSettings.objects.all().delete()
            self.stdout.write('   ✅ Deleted Client Settings')

            # 4. Notifications (references users)
            Notification.objects.all().delete()
            self.stdout.write('   ✅ Deleted Notifications')

            # 5. Asset Checkout History (references users) - DELETE THIS BEFORE USERS
            AssetCheckoutHistory.objects.all().delete()
            self.stdout.write('   ✅ Deleted Asset Checkout History')

            # 6. Asset Logs (references users)
            AssetLog.objects.all().delete()
            self.stdout.write('   ✅ Deleted Asset Logs')

            # 7. Asset Maintenance Logs (references users)
            AssetMaintenanceLog.objects.all().delete()
            self.stdout.write('   ✅ Deleted Asset Maintenance Logs')

            # 8. Assets (references users via assigned_to, created_by, etc.)
            Asset.objects.all().delete()
            self.stdout.write('   ✅ Deleted Assets')

            # 9. Asset Categories (if they reference users, but they don't - safe to keep)
            # AssetCategory.objects.all().delete()
            # self.stdout.write('   ✅ Deleted Asset Categories')

            # 10. Ticket Comments (references users)
            TicketComment.objects.all().delete()
            self.stdout.write('   ✅ Deleted Ticket Comments')

            # 11. Attachments (references users)
            Attachment.objects.all().delete()
            self.stdout.write('   ✅ Deleted Attachments')

            # 12. Ticket Activity Logs (references users)
            TicketActivityLog.objects.all().delete()
            self.stdout.write('   ✅ Deleted Activity Logs')

            # 13. Tickets (references users)
            Ticket.objects.all().delete()
            self.stdout.write('   ✅ Deleted Tickets')

            # 14. Knowledge Base Articles (references users)
            Article.objects.all().delete()
            self.stdout.write('   ✅ Deleted Articles')

            # 15. Article Versions (references users)
            ArticleVersion.objects.all().delete()
            self.stdout.write('   ✅ Deleted Article Versions')

            # 16. Article Feedback (references users)
            ArticleFeedback.objects.all().delete()
            self.stdout.write('   ✅ Deleted Article Feedback')

            # 17. Maintenance Activity Logs (references users)
            MaintenanceActivityLog.objects.all().delete()
            self.stdout.write('   ✅ Deleted Maintenance Activity Logs')

            # 18. Maintenance Schedules (references users)
            MaintenanceSchedule.objects.all().delete()
            self.stdout.write('   ✅ Deleted Maintenance Schedules')

            # 20. Finally, delete users
            users_to_delete.delete()
            self.stdout.write(f'   ✅ Deleted {delete_count} users')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error during deletion: {e}'))
            import traceback
            self.stdout.write(traceback.format_exc())
            return

        # Verify
        remaining_users = User.objects.count()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('✅ WIPE COMPLETE'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(f'📊 Remaining users: {remaining_users}')
        if keep_superuser and kept_superuser:
            self.stdout.write(f'🔒 Kept superuser: {kept_superuser.email}')

        # Verify related data is empty
        self.stdout.write('')
        self.stdout.write('📊 Remaining data:')
        self.stdout.write(f'   - Tickets: {Ticket.objects.count()}')
        self.stdout.write(f'   - Comments: {TicketComment.objects.count()}')
        self.stdout.write(f'   - Notifications: {Notification.objects.count()}')
        self.stdout.write(f'   - Assets: {Asset.objects.count()}')
        self.stdout.write(f'   - Asset Checkout History: {AssetCheckoutHistory.objects.count()}')

        # Reset user ID sequence (PostgreSQL specific)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT setval('accounts_user_id_seq', 1, false);")
                self.stdout.write('   ✅ User ID sequence reset')
        except Exception:
            pass  # Not critical