# apps/maintenance/management/commands/seed_maintenance_demo_data.py
"""Seeds a self-contained demo scenario for manually testing the per-asset
maintenance confirmation flow end-to-end: multi-department scheduling,
owner confirmation, the IT-Team-Lead fallback (for any ownerless/shared
asset, regardless of which department it's tagged with — shared pool
inventory is IT-managed), and an upcoming schedule due soon enough to
exercise send_maintenance_reminders.

Admin is deliberately NOT a confirmer/override here — whoever schedules
maintenance and is accountable for it doesn't also get final say over
whether it actually happened, which is the whole point of the independent
confirmation step. Admin/Superadmin are only eligible as a genuine
last-resort fallback (no owner AND no IT Team Lead in the system at all),
which this demo data doesn't exercise since demo.it.lead@example.com
always exists.

Idempotent: skipped entirely if the demo schedule titles already exist, so
re-running it is safe.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.tickets.models import Asset, AssetCategory, AssetDepartment
from apps.maintenance.models import MaintenanceSchedule, MaintenanceAssetConfirmation, Vendor

DEMO_PASSWORD = 'DemoPass123!'

MULTI_DEPT_SCHEDULE_TITLE = 'Demo: Quarterly Multi-Department IT Audit'
UPCOMING_SCHEDULE_TITLE = 'Demo: Upcoming Server Room Check'
IN_PROGRESS_SCHEDULE_TITLE = 'Demo: In-Progress Network Check'
FACILITY_ONLY_SCHEDULE_TITLE = 'Demo: Completed Facility-Only Maintenance'
RESOLVED_SCHEDULE_TITLE = 'Demo: Completed With Resolved Confirmations'


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
        # Users — spans IT, MARINE, and ACCOUNTING. marine_lead exists to
        # test that a non-IT Team Lead can still view/act on schedules
        # targeting their own department, but does NOT confirm any
        # ownerless asset below — that fallback always goes to the IT
        # Team Lead now, regardless of the asset's own department.
        # ------------------------------------------------------------
        admin, _ = get_or_create_user('demo.admin@example.com', 'Demo', 'Admin', 'IT', User.Role.ADMIN)
        technician, _ = get_or_create_user('demo.technician@example.com', 'Demo', 'Technician', 'IT', User.Role.AGENT)
        # Second IT technician — used as `additional_assignees` on the
        # in-progress schedule below, since assigned_to/additional_assignees
        # are now restricted to TEAM_LEAD/AGENT in the IT department only
        # (maintenance is carried out by Team Lead/Support Team, never
        # Admin/Superadmin — see MaintenanceScheduleForm).
        technician2, _ = get_or_create_user('demo.technician2@example.com', 'Demo', 'Technician2', 'IT', User.Role.AGENT)
        it_lead, _ = get_or_create_user('demo.it.lead@example.com', 'Demo', 'ITLead', 'IT', User.Role.TEAM_LEAD)
        marine_lead, _ = get_or_create_user('demo.marine.lead@example.com', 'Demo', 'MarineLead', 'MARINE', User.Role.TEAM_LEAD)
        it_owner, _ = get_or_create_user('demo.it.owner@example.com', 'Demo', 'ITOwner', 'IT', User.Role.END_USER)
        marine_owner, _ = get_or_create_user('demo.marine.owner@example.com', 'Demo', 'MarineOwner', 'MARINE', User.Role.END_USER)

        # ------------------------------------------------------------
        # Assets — one owned + one ownerless per department in the
        # multi-department schedule. Every ownerless asset here (IT,
        # Marine, Accounting alike) confirms to the IT Team Lead, since
        # shared/pool inventory is IT-managed regardless of department tag.
        # ------------------------------------------------------------
        category, _ = AssetCategory.objects.get_or_create(name='Demo Equipment')

        def make_asset(name, department_code, assigned_to=None):
            # Asset.department is an AssetDepartment FK, not a raw string —
            # resolve via legacy_user_department_code so these demo assets
            # land in the same AssetDepartment row the maintenance views'
            # department-scoped filters already match against real users.
            department = AssetDepartment.objects.filter(legacy_user_department_code=department_code).first()
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
        accounting_ownerless_asset = make_asset('Demo Accounting Scanner (Shared)', 'ACCOUNTING', None)

        vendor, _ = Vendor.objects.get_or_create(
            name='Demo IT Vendor Ltd',
            defaults={'contact_person': 'Demo Contact', 'phone': '000-000-0000', 'email': 'vendor@example.com'},
        )

        # ------------------------------------------------------------
        # Schedule 1 — already COMPLETED, spans 3 departments, targets all
        # 5 assets above. Confirmation rows are PENDING, ready for you to
        # confirm/dispute (as the owner / IT Team Lead fallback / Admin).
        # ------------------------------------------------------------
        completed_at = timezone.now() - timedelta(hours=2)
        multi_dept_schedule = MaintenanceSchedule.objects.create(
            title=MULTI_DEPT_SCHEDULE_TITLE,
            description='Seeded demo schedule spanning IT, Marine, and Accounting — used to test per-asset owner confirmation and the IT Team Lead fallback in one place.',
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

        # ------------------------------------------------------------
        # Schedule 3 — IN_PROGRESS right now, with a second technician as
        # additional_assignees and a vendor attached. Used to test the
        # "Mark Complete" action from the detail page (log in as
        # demo.technician@example.com or demo.technician2@example.com) and
        # to exercise the schedule_edit personnel pickers on an active
        # multi-person schedule.
        # ------------------------------------------------------------
        in_progress_schedule = MaintenanceSchedule.objects.create(
            title=IN_PROGRESS_SCHEDULE_TITLE,
            description='Seeded demo schedule already in progress — used to test Mark Complete, the status modal, and multi-person assignment.',
            departments=['IT'],
            scheduled_date=(timezone.now() - timedelta(hours=1)).date(),
            start_time=(timezone.now() - timedelta(hours=1)).time(),
            assigned_to=technician,
            status=MaintenanceSchedule.Status.IN_PROGRESS,
            checklist_items=['Check server room temperature', 'Inspect network switches', 'Update firmware'],
        )
        in_progress_schedule.additional_assignees.set([technician2])
        in_progress_schedule.target_assets.set([it_owned_asset, it_ownerless_asset])
        in_progress_schedule.vendors.set([vendor])

        # ------------------------------------------------------------
        # Schedule 4 — COMPLETED with NO target assets (facility_location
        # only). Used to check the "NOT_APPLICABLE" confirmation state and
        # the completion email's wording when there's no asset owner to
        # ever confirm anything.
        # ------------------------------------------------------------
        facility_completed_at = timezone.now() - timedelta(hours=5)
        MaintenanceSchedule.objects.create(
            title=FACILITY_ONLY_SCHEDULE_TITLE,
            description='Seeded demo schedule with no target assets — checks the facility-only completion path (no per-asset confirmation applies).',
            departments=['IT'],
            scheduled_date=(timezone.now() - timedelta(days=1)).date(),
            assigned_to=technician,
            status=MaintenanceSchedule.Status.COMPLETED,
            completed_at=facility_completed_at,
            facility_location='Generator House',
        )

        # ------------------------------------------------------------
        # Schedule 5 — COMPLETED with confirmations already resolved (one
        # CONFIRMED, one DISPUTED), so both end states are visible without
        # having to click through the confirm modal yourself first.
        # ------------------------------------------------------------
        resolved_completed_at = timezone.now() - timedelta(days=2)
        resolved_schedule = MaintenanceSchedule.objects.create(
            title=RESOLVED_SCHEDULE_TITLE,
            description='Seeded demo schedule with confirmations already resolved — one confirmed, one disputed.',
            departments=['MARINE'],
            scheduled_date=(timezone.now() - timedelta(days=3)).date(),
            assigned_to=technician,
            status=MaintenanceSchedule.Status.COMPLETED,
            completed_at=resolved_completed_at,
        )
        resolved_schedule.target_assets.set([marine_owned_asset, marine_ownerless_asset])
        MaintenanceAssetConfirmation.objects.create(
            schedule=resolved_schedule, asset=marine_owned_asset,
            technician_completed_at=resolved_completed_at,
            status=MaintenanceAssetConfirmation.Status.CONFIRMED,
            confirmed_by=marine_owner, confirmed_at=resolved_completed_at + timedelta(minutes=30),
            notes='Looks good, thanks.',
        )
        MaintenanceAssetConfirmation.objects.create(
            schedule=resolved_schedule, asset=marine_ownerless_asset,
            technician_completed_at=resolved_completed_at,
            status=MaintenanceAssetConfirmation.Status.DISPUTED,
            confirmed_by=it_lead, confirmed_at=resolved_completed_at + timedelta(hours=1),
            dispute_reason='Winch is still making the same noise as before.',
        )

        self.stdout.write(self.style.SUCCESS('\nDemo data seeded successfully.\n'))
        self.stdout.write('Demo accounts (password for all: %s):' % DEMO_PASSWORD)
        self.stdout.write(f'  Admin           demo.admin@example.com          (schedules maintenance, but cannot confirm/override — see notes above)')
        self.stdout.write(f'  Technician      demo.technician@example.com     (primary assignee on schedules 1, 3, 4, 5)')
        self.stdout.write(f'  Technician 2    demo.technician2@example.com    (additional personnel on schedule 3)')
        self.stdout.write(f'  IT Team Lead    demo.it.lead@example.com        (confirms every ownerless/shared asset, any department — see My Assets "Shared IT Inventory" section; disputed schedule 5)')
        self.stdout.write(f'  Marine Lead     demo.marine.lead@example.com    (can view/manage schedules targeting MARINE, but no longer confirms ownerless assets — IT Team Lead handles those now)')
        self.stdout.write(f'  IT Owner        demo.it.owner@example.com       (confirms Demo IT Laptop)')
        self.stdout.write(f'  Marine Owner    demo.marine.owner@example.com   (confirms Demo Marine Radio; already confirmed schedule 5)')
        self.stdout.write('')
        self.stdout.write(f'1. "{MULTI_DEPT_SCHEDULE_TITLE}" — completed, all 5 assets PENDING confirmation. Log in as each owner to confirm their own asset, or as demo.it.lead@example.com to confirm the three ownerless ones (IT printer, Marine winch, Accounting scanner — all fall to IT regardless of department). demo.admin@example.com cannot act on any of these — an IT Team Lead exists, so the Admin last-resort fallback never applies.')
        self.stdout.write(f'2. "{UPCOMING_SCHEDULE_TITLE}" — due in ~90 minutes. Run `python manage.py send_maintenance_reminders` to fire the pre-maintenance reminders immediately (also exercises auto-start once due).')
        self.stdout.write(f'3. "{IN_PROGRESS_SCHEDULE_TITLE}" — IN_PROGRESS now, 2 assignees + a vendor attached. Log in as demo.technician@example.com to hit Mark Complete from the detail page.')
        self.stdout.write(f'4. "{FACILITY_ONLY_SCHEDULE_TITLE}" — completed, no target assets (facility_location only) — confirmation state should read NOT_APPLICABLE.')
        self.stdout.write(f'5. "{RESOLVED_SCHEDULE_TITLE}" — completed, confirmations already resolved (one CONFIRMED, one DISPUTED) — check both end states on the detail page without needing to act.')
