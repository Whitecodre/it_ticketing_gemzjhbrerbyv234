# apps/maintenance/management/commands/seed_maintenance_demo_data.py
"""Seeds a self-contained demo scenario for manually testing the per-asset
maintenance confirmation flow end-to-end: multi-department scheduling,
owner confirmation, department-Team-Lead fallback (for an ownerless asset),
Admin fallback (for a department with no Team Lead at all), and an upcoming
schedule due soon enough to exercise send_maintenance_reminders.

Idempotent: skipped entirely if the demo schedule titles already exist, so
re-running it is safe.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.tickets.models import Asset, AssetCategory
from apps.maintenance.models import MaintenanceSchedule, MaintenanceAssetConfirmation

DEMO_PASSWORD = 'DemoPass123!'

MULTI_DEPT_SCHEDULE_TITLE = 'Demo: Quarterly Multi-Department IT Audit'
UPCOMING_SCHEDULE_TITLE = 'Demo: Upcoming Server Room Check'


class Command(BaseCommand):
    help = 'Seed a demo scenario (users, assets, schedules) for manually testing the maintenance confirmation flow.'

    def handle(self, *args, **options):
        if MaintenanceSchedule.objects.filter(title=MULTI_DEPT_SCHEDULE_TITLE).exists():
            self.stdout.write(self.style.WARNING(
                f'Demo data already exists (schedule "{MULTI_DEPT_SCHEDULE_TITLE}" found). Skipping.'
            ))
            return

        def get_or_create_user(email, first_name, last_name, department, role):
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first_name, 'last_name': last_name,
                    'department': department, 'role': role,
                    'is_active': True, 'email_verified': True, 'password_changed': True,
                },
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()  # 2nd save (1st happens inside get_or_create) — triggers sync_roles() so active_role/roles M2M are actually populated, since sync_roles() no-ops on a row with no pk yet.
            return user, created

        # ------------------------------------------------------------
        # Users — spans IT, MARINE, and ACCOUNTING (the last one
        # deliberately has NO Team Lead, to exercise the Admin fallback).
        # ------------------------------------------------------------
        admin, _ = get_or_create_user('demo.admin@example.com', 'Demo', 'Admin', 'IT', User.Role.ADMIN)
        technician, _ = get_or_create_user('demo.technician@example.com', 'Demo', 'Technician', 'IT', User.Role.AGENT)
        it_lead, _ = get_or_create_user('demo.it.lead@example.com', 'Demo', 'ITLead', 'IT', User.Role.TEAM_LEAD)
        marine_lead, _ = get_or_create_user('demo.marine.lead@example.com', 'Demo', 'MarineLead', 'MARINE', User.Role.TEAM_LEAD)
        it_owner, _ = get_or_create_user('demo.it.owner@example.com', 'Demo', 'ITOwner', 'IT', User.Role.END_USER)
        marine_owner, _ = get_or_create_user('demo.marine.owner@example.com', 'Demo', 'MarineOwner', 'MARINE', User.Role.END_USER)

        # ------------------------------------------------------------
        # Assets — one owned + one ownerless per department in the
        # multi-department schedule, plus one ownerless ACCOUNTING asset
        # (no Team Lead there at all → falls all the way to Admin).
        # ------------------------------------------------------------
        category, _ = AssetCategory.objects.get_or_create(name='Demo Equipment')

        def make_asset(name, department, assigned_to=None):
            # Reuse-by-name rather than always creating a new row: assets
            # can end up PROTECTED against deletion by unrelated FKs (e.g.
            # MobilizationItem), so a demo re-seed can't just delete and
            # recreate them — reset the existing row back to the intended
            # demo state instead.
            asset, _ = Asset.objects.update_or_create(
                name=name,
                defaults={
                    'category': category, 'department': department,
                    'assigned_to': assigned_to,
                    'status': Asset.Status.IN_USE if assigned_to else Asset.Status.IN_STORE,
                    'manufacturer': 'Demo Corp', 'model': 'Demo Model',
                },
            )
            return asset

        it_owned_asset = make_asset('Demo IT Laptop (Owned)', 'IT', it_owner)
        it_ownerless_asset = make_asset('Demo IT Printer (Shared)', 'IT', None)
        marine_owned_asset = make_asset('Demo Marine Radio (Owned)', 'MARINE', marine_owner)
        marine_ownerless_asset = make_asset('Demo Marine Winch (Shared)', 'MARINE', None)
        accounting_ownerless_asset = make_asset('Demo Accounting Scanner (Shared, No Team Lead)', 'ACCOUNTING', None)

        # ------------------------------------------------------------
        # Schedule 1 — already COMPLETED, spans 3 departments, targets all
        # 5 assets above. Confirmation rows are PENDING, ready for you to
        # confirm/dispute (as the owner / department Team Lead / Admin).
        # ------------------------------------------------------------
        completed_at = timezone.now() - timedelta(hours=2)
        multi_dept_schedule = MaintenanceSchedule.objects.create(
            title=MULTI_DEPT_SCHEDULE_TITLE,
            description='Seeded demo schedule spanning IT, Marine, and Accounting — used to test per-asset owner confirmation, Team Lead fallback, and Admin fallback in one place.',
            departments=['IT', 'MARINE', 'ACCOUNTING'],
            scheduled_date=(timezone.now() - timedelta(days=1)).date(),
            assigned_to=technician,
            status=MaintenanceSchedule.Status.COMPLETED,
            completed_at=completed_at,
        )
        multi_dept_schedule.target_assets.set([
            it_owned_asset, it_ownerless_asset, marine_owned_asset, marine_ownerless_asset, accounting_ownerless_asset,
        ])
        for asset in multi_dept_schedule.target_assets.all():
            MaintenanceAssetConfirmation.objects.create(
                schedule=multi_dept_schedule, asset=asset, technician_completed_at=completed_at,
            )

        # ------------------------------------------------------------
        # Schedule 2 — still SCHEDULED, due in ~90 minutes (inside the 24h
        # and 1h reminder thresholds already, so running
        # `python manage.py send_maintenance_reminders` immediately fires
        # both technician and owner reminders without waiting).
        # ------------------------------------------------------------
        due_soon = timezone.now() + timedelta(minutes=90)
        upcoming_schedule = MaintenanceSchedule.objects.create(
            title=UPCOMING_SCHEDULE_TITLE,
            description='Seeded demo schedule due soon — used to test the pre-maintenance reminder notifications (technician + asset owner).',
            departments=['IT'],
            scheduled_date=due_soon.date(),
            start_time=due_soon.time(),
            assigned_to=technician,
            status=MaintenanceSchedule.Status.SCHEDULED,
        )
        upcoming_schedule.target_assets.set([it_owned_asset])

        self.stdout.write(self.style.SUCCESS('\nDemo data seeded successfully.\n'))
        self.stdout.write('Demo accounts (password for all: %s):' % DEMO_PASSWORD)
        self.stdout.write(f'  Admin           demo.admin@example.com          (Admin override / Accounting fallback confirmer)')
        self.stdout.write(f'  Technician      demo.technician@example.com     (marked both schedules)')
        self.stdout.write(f'  IT Team Lead    demo.it.lead@example.com        (confirms Demo IT Printer — no owner)')
        self.stdout.write(f'  Marine Lead     demo.marine.lead@example.com    (confirms Demo Marine Winch — no owner)')
        self.stdout.write(f'  IT Owner        demo.it.owner@example.com       (confirms Demo IT Laptop)')
        self.stdout.write(f'  Marine Owner    demo.marine.owner@example.com   (confirms Demo Marine Radio)')
        self.stdout.write('')
        self.stdout.write(f'"{MULTI_DEPT_SCHEDULE_TITLE}" — completed, all 5 assets PENDING confirmation. Log in as each user above to confirm/dispute their asset; log in as demo.admin@example.com to override any of them, including the Accounting one (no Team Lead exists for that department).')
        self.stdout.write(f'"{UPCOMING_SCHEDULE_TITLE}" — due in ~90 minutes. Run `python manage.py send_maintenance_reminders` to fire the pre-maintenance reminders immediately.')
