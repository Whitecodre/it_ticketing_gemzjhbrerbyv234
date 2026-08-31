# apps/tickets/management/commands/seed_mobilization_demo.py
"""
One-shot, idempotent seed for demoing the mobilization/demobilization
feature end-to-end: request-type flag, dual fulfillment entry points,
traceable linkage, batch demobilize, extendable date with audit trail,
requester confirm-receipt, and vendor-by-category filtering + mobilization
prefill. Safe to re-run — every row is created via get_or_create keyed on
something stable, so running it twice just confirms everything is in place
rather than duplicating data.
"""
import datetime

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.tickets.models import (
    Ticket, ServiceCategory, AssetCategory, Asset, JobNumber, Vessel,
    DiveSystem, Mobilization, MobilizationItem, MobilizationDateExtension,
)
from apps.maintenance.models import Vendor

User = get_user_model()

DEMO_PASSWORD = 'DemoPass123!'


class Command(BaseCommand):
    help = 'Seed a complete, idempotent demo dataset for the mobilization/demobilization feature.'

    def handle(self, *args, **options):
        users = self._seed_users()
        categories = self._seed_categories()
        self._seed_vendors(categories)
        job, vessel, dive_system = self._seed_lookups()
        service_category = self._seed_service_category()
        assets = self._seed_assets(categories)
        self._seed_tickets(users, service_category, job, vessel)
        self._seed_standalone_mobilization(users, categories, job, vessel, assets)

        self.stdout.write(self.style.SUCCESS('\nDemo data ready.'))
        self._print_walkthrough(users)

    # ------------------------------------------------------------------
    def _seed_users(self):
        specs = [
            ('mobdemo.requester@example.com', 'Rita', 'Requester', User.Role.END_USER, False),
            ('mobdemo.manager@example.com', 'Mona', 'Manager', User.Role.TEAM_LEAD, False),
            ('mobdemo.admin@example.com', 'Adam', 'Admin', User.Role.ADMIN, True),
        ]
        users = {}
        for email, first, last, role, is_super in specs:
            defaults = {
                'first_name': first, 'last_name': last, 'department': 'IT',
                'role': role, 'is_active': True,
            }
            if is_super:
                user, created = User.objects.get_or_create(email=email, defaults={**defaults, 'is_staff': True, 'is_superuser': True})
            else:
                user, created = User.objects.get_or_create(email=email, defaults=defaults)
            user.set_password(DEMO_PASSWORD)
            user.is_active = True
            user.save()
            users[role if role != User.Role.ADMIN or not is_super else 'ADMIN'] = user
            self.stdout.write(self.style.SUCCESS(f'{"Created" if created else "Reset password for"} user: {email}'))
        return {
            'requester': users[User.Role.END_USER],
            'manager': users[User.Role.TEAM_LEAD],
            'admin': users['ADMIN'],
        }

    # ------------------------------------------------------------------
    def _seed_categories(self):
        names = ['Laptop', 'Server', 'Network Device', 'Printer']
        categories = {}
        for name in names:
            cat, _ = AssetCategory.objects.get_or_create(name=name)
            categories[name] = cat
        return categories

    def _seed_vendors(self, categories):
        vendor, created = Vendor.objects.get_or_create(
            name='Acme Laptops Ltd',
            defaults={'contact_person': 'Sam Acme', 'phone': '555-0101', 'email': 'sales@acmelaptops.example', 'is_active': True},
        )
        vendor.categories.set([categories['Laptop'], categories['Network Device']])
        self.stdout.write(self.style.SUCCESS(f'{"Created" if created else "Updated"} vendor: {vendor.name} -> Laptop, Network Device'))

        vendor2, created2 = Vendor.objects.get_or_create(
            name='ServerPro Supplies',
            defaults={'contact_person': 'Priya Rao', 'phone': '555-0102', 'email': 'sales@serverpro.example', 'is_active': True},
        )
        vendor2.categories.set([categories['Server']])
        self.stdout.write(self.style.SUCCESS(f'{"Created" if created2 else "Updated"} vendor: {vendor2.name} -> Server'))

        vendor3, created3 = Vendor.objects.get_or_create(
            name='General Office Supplies Co',
            defaults={'contact_person': 'Chidi Okoro', 'phone': '555-0103', 'email': 'sales@generaloffice.example', 'is_active': True},
        )
        # Deliberately no categories assigned — demonstrates the "serves
        # every category" default for an uncategorized vendor.
        self.stdout.write(self.style.SUCCESS(f'{"Created" if created3 else "Confirmed"} vendor: {vendor3.name} -> (no categories, visible everywhere)'))

    def _seed_lookups(self):
        job, _ = JobNumber.objects.get_or_create(number='JOB-DEMO-01', defaults={'is_active': True})
        if not job.is_active:
            job.is_active = True
            job.save()
        vessel, _ = Vessel.objects.get_or_create(name='MV Demo Explorer', defaults={'is_active': True})
        if not vessel.is_active:
            vessel.is_active = True
            vessel.save()
        dive_system, _ = DiveSystem.objects.get_or_create(name='Demo Dive System A', defaults={'is_active': True})
        if not dive_system.is_active:
            dive_system.is_active = True
            dive_system.save()
        self.stdout.write(self.style.SUCCESS(f'Job/Vessel/Dive System ready: {job.number}, {vessel.name}, {dive_system.name}'))
        return job, vessel, dive_system

    def _seed_service_category(self):
        service_category, created = ServiceCategory.objects.get_or_create(
            slug='equipment-request-demo',
            defaults={
                'name': 'Equipment Request (Demo)',
                'field_group': ServiceCategory.FieldGroup.ASSET,
                'icon': 'hard-drive',
                'is_active': True,
                'order': 0,
            },
        )
        self.stdout.write(self.style.SUCCESS(f'{"Created" if created else "Confirmed"} service category: {service_category.name}'))
        return service_category

    def _seed_assets(self, categories):
        specs = [
            ('Demo Laptop Alpha', categories['Laptop'], 'DEMO-SN-LT-01'),
            ('Demo Laptop Beta', categories['Laptop'], 'DEMO-SN-LT-02'),
            ('Demo Laptop Gamma', categories['Laptop'], 'DEMO-SN-LT-03'),
            ('Demo Server Rack Unit', categories['Server'], 'DEMO-SN-SV-01'),
            ('Demo Network Switch', categories['Network Device'], 'DEMO-SN-NW-01'),
        ]
        assets = []
        for name, category, serial in specs:
            asset, created = Asset.objects.get_or_create(
                name=name, serial_number=serial,
                defaults={
                    'category': category,
                    'location': 'Demo Stock Room',
                    'status': Asset.Status.IN_STORE,
                },
            )
            assets.append(asset)
            self.stdout.write(self.style.SUCCESS(f'{"Created" if created else "Confirmed"} asset: {asset.tracking_id} — {asset.name}'))
        return assets

    # ------------------------------------------------------------------
    def _seed_tickets(self, users, service_category, job, vessel):
        requester, manager, admin = users['requester'], users['manager'], users['admin']

        # (a) Normal single-asset request, ready to fulfill via the plain
        # "Fulfill Request" path (not mobilization-flagged).
        Ticket.objects.get_or_create(
            number='DEMO#0001',
            defaults=dict(
                type=Ticket.Type.SERVICE_REQUEST, title='New laptop for onboarding',
                description='New hire starting Monday needs a laptop.',
                requester=requester, service_category=service_category,
                purpose='Onboarding a new developer',
                status=Ticket.Status.PENDING_FULFILLMENT,
                is_asset_request=True, is_mobilization_request=False,
                service_request_details={'asset_type': 'LAPTOP', 'number_of_assets': '1'},
            ),
        )
        self.stdout.write(self.style.SUCCESS('Ticket DEMO#0001 — normal asset request, PENDING_FULFILLMENT'))

        # (b) Mobilization-flagged request — demoes "Mobilize Assets" +
        # the job/vessel/notes/quantity/category prefill.
        Ticket.objects.get_or_create(
            number='DEMO#0002',
            defaults=dict(
                type=Ticket.Type.SERVICE_REQUEST, title='Laptops for offshore crew',
                description='Crew mobilizing to MV Demo Explorer needs laptops for the job.',
                requester=requester, service_category=service_category,
                purpose='Offshore crew laptops for JOB-DEMO-01',
                status=Ticket.Status.PENDING_FULFILLMENT,
                is_asset_request=True, is_mobilization_request=True,
                job_number=job,
                service_request_details={'asset_type': 'LAPTOP', 'number_of_assets': '2'},
            ),
        )
        ticket_b = Ticket.objects.get(number='DEMO#0002')
        ticket_b.vessels.set([vessel])
        self.stdout.write(self.style.SUCCESS('Ticket DEMO#0002 — mobilization request, PENDING_FULFILLMENT (prefill-ready)'))

        # (c) Already fulfilled, sitting at PENDING_USER — demoes "Confirm
        # Received" immediately without redoing the fulfillment steps.
        asset_for_c, _ = Asset.objects.get_or_create(
            name='Demo Laptop Delta', serial_number='DEMO-SN-LT-04',
            defaults={'category': AssetCategory.objects.get(name='Laptop'), 'location': 'Demo Stock Room', 'status': Asset.Status.IN_STORE},
        )
        ticket_c, created_c = Ticket.objects.get_or_create(
            number='DEMO#0003',
            defaults=dict(
                type=Ticket.Type.SERVICE_REQUEST, title='Laptop for field technician',
                description='Field technician needs a replacement laptop.',
                requester=requester, service_category=service_category,
                purpose='Replacement laptop',
                status=Ticket.Status.PENDING_USER,
                is_asset_request=True, is_mobilization_request=False,
                assigned_asset=asset_for_c,
                fulfilled_at=timezone.now(), fulfilled_by=admin,
                service_request_details={'asset_type': 'LAPTOP', 'number_of_assets': '1'},
            ),
        )
        if created_c:
            asset_for_c.status = Asset.Status.IN_USE
            asset_for_c.assigned_to = requester
            asset_for_c.save(update_fields=['status', 'assigned_to'])
        self.stdout.write(self.style.SUCCESS('Ticket DEMO#0003 — already fulfilled, PENDING_USER (ready for "Confirm Received")'))

    # ------------------------------------------------------------------
    def _seed_standalone_mobilization(self, users, categories, job, vessel, assets):
        """An ACTIVE mobilization not tied to any ticket, with items already
        out and one date extension already on record — lets "Demobilize
        All" and the extension history be demoed immediately."""
        admin = users['admin']
        mobilization, created = Mobilization.objects.get_or_create(
            job_number=job,
            notes='Standalone demo mobilization — Demobilize All / Extend Date',
            defaults=dict(
                mobilized_by=admin,
                mobilized_at=timezone.now() - datetime.timedelta(days=5),
                expected_return_date=timezone.now().date() + datetime.timedelta(days=2),
                original_expected_return_date=timezone.now().date() - datetime.timedelta(days=3),
            ),
        )
        if created:
            mobilization.vessels.set([vessel])

            demo_items_assets = [a for a in assets if a.category_id == categories['Server'].id or a.category_id == categories['Network Device'].id]
            for asset in demo_items_assets:
                if asset.status != Asset.Status.MOBILIZED:
                    MobilizationItem.objects.create(mobilization=mobilization, asset=asset, quantity=1)
                    asset.status = Asset.Status.MOBILIZED
                    asset.status_updated_at = timezone.now()
                    asset.status_updated_by = admin
                    asset.save(update_fields=['status', 'status_updated_at', 'status_updated_by'])

            MobilizationDateExtension.objects.create(
                mobilization=mobilization,
                previous_date=mobilization.original_expected_return_date,
                new_date=mobilization.expected_return_date,
                reason='Job running longer than planned',
                extended_by=admin,
            )
            self.stdout.write(self.style.SUCCESS(f'Mobilization #{mobilization.pk} — ACTIVE, 2 items out, 1 prior extension on record'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Mobilization #{mobilization.pk} — already present'))

    # ------------------------------------------------------------------
    def _print_walkthrough(self, users):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=== Demo login credentials (password for all: %s) ===' % DEMO_PASSWORD))
        self.stdout.write(f'  Requester : {users["requester"].email}')
        self.stdout.write(f'  Manager   : {users["manager"].email}')
        self.stdout.write(f'  Admin     : {users["admin"].email}')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=== Walkthrough ==='))
        self.stdout.write('1. Login as manager -> Manager Review -> approve DEMO#0001 and DEMO#0002.')
        self.stdout.write('2. Login as admin -> Admin Dashboard "Pending Asset Fulfillment" widget (or the ticket conversation page):')
        self.stdout.write('   - DEMO#0001 shows a plain "Fulfill" button -> pick an asset -> ticket goes to PENDING_USER.')
        self.stdout.write('   - DEMO#0002 shows a "Mobilize" button -> opens pre-filled with Job/Vessel + Laptop x2 in Quick Add + purpose in Notes.')
        self.stdout.write('3. Login as requester -> open DEMO#0003 -> "Confirm Received" in the details panel -> ticket moves to APPROVED (receipt confirmed, not yet resolved).')
        self.stdout.write('   Then login as admin/agent on the same ticket -> "Resolve" now submits directly with no modal (receipt already confirmed) -> ticket RESOLVED.')
        self.stdout.write('4. As admin, open Mobilizations list -> the standalone demo mobilization:')
        self.stdout.write('   - "Demobilize All" returns every active item in one action.')
        self.stdout.write('   - "Extend Date" adds another entry to the visible extension history (original date is preserved).')
        self.stdout.write('5. System Settings -> Vendors: "Acme Laptops Ltd" and "ServerPro Supplies" are category-scoped;')
        self.stdout.write('   "General Office Supplies Co" has no categories and shows up regardless. Try the vendor picker on')
        self.stdout.write('   the "Order from Vendor" section of a fulfillment modal or a mobilization procurement row —')
        self.stdout.write('   switching category live-narrows the vendor list.')
