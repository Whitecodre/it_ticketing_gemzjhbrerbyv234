# apps/tickets/management/commands/seed_assets.py
import random
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.tickets.models import Asset, AssetCategory, AssetLog

User = get_user_model()


class Command(BaseCommand):
    help = 'Seed the asset database with a handful of sample assets for testing (only if empty)'

    def handle(self, *args, **options):
        if Asset.objects.exists():
            self.stdout.write(self.style.WARNING('⚠️ Assets already exist. Skipping seeding to avoid duplicates.'))
            self.stdout.write(self.style.WARNING(f'   Current asset count: {Asset.objects.count()}'))
            return

        actor = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not actor:
            self.stdout.write(self.style.ERROR('No users found. Please create at least one user first.'))
            return

        users = list(User.objects.filter(is_active=True))
        if not users:
            self.stdout.write(self.style.WARNING('No active users found. Assets will be unassigned.'))

        def category(name):
            obj, _ = AssetCategory.objects.get_or_create(name=name)
            return obj

        asset_data = [
            {
                'name': 'Dell Latitude 5420',
                'category': category('Laptop'),
                'serial_number': f'SN-{random.randint(1000, 9999)}',
                'model': 'Latitude 5420',
                'manufacturer': 'Dell',
                'location': 'Building A, Floor 3, IT Dept',
                'purchase_date': date.today() - timedelta(days=random.randint(30, 900)),
                'warranty_expiry': date.today() + timedelta(days=random.randint(100, 500)),
                'status': Asset.Status.IN_USE,
                'checked_out': True,
                'notes': 'Standard issue laptop for developers.'
            },
            {
                'name': 'Dell PowerEdge R740',
                'category': category('Server'),
                'serial_number': f'SN-{random.randint(1000, 9999)}',
                'model': 'PowerEdge R740',
                'manufacturer': 'Dell',
                'location': 'Data Center A, Rack 12',
                'purchase_date': date.today() - timedelta(days=random.randint(30, 900)),
                'warranty_expiry': date.today() + timedelta(days=random.randint(100, 500)),
                'status': Asset.Status.IN_STORE,
                'notes': 'Spare production application server.'
            },
            {
                'name': 'HP LaserJet Enterprise M607',
                'category': category('Printer'),
                'serial_number': f'SN-{random.randint(1000, 9999)}',
                'model': 'LaserJet Enterprise M607',
                'manufacturer': 'HP',
                'location': 'Building A, Floor 2, Breakroom',
                'purchase_date': date.today() - timedelta(days=random.randint(30, 900)),
                'warranty_expiry': date.today() + timedelta(days=random.randint(100, 500)),
                'status': Asset.Status.IN_STORE,
                'notes': 'High-volume printer for staff.'
            },
            {
                'name': 'Microsoft Office 365 E3 License',
                'category': category('Software License'),
                'serial_number': '',
                'model': 'Office 365 E3',
                'manufacturer': 'Microsoft',
                'location': 'Global',
                'purchase_date': date.today() - timedelta(days=random.randint(30, 900)),
                'warranty_expiry': None,
                'status': Asset.Status.IN_USE,
                'notes': 'Enterprise license for all employees.'
            },
            {
                'name': 'Dell Latitude 7400 (Damaged)',
                'category': category('Laptop'),
                'serial_number': f'SN-{random.randint(1000, 9999)}',
                'model': 'Latitude 7400',
                'manufacturer': 'Dell',
                'location': 'IT Repair Shop',
                'purchase_date': date.today() - timedelta(days=500),
                'warranty_expiry': date.today() - timedelta(days=100),
                'status': Asset.Status.MAINTENANCE,
                'notes': 'Screen cracked, pending repair.'
            },
        ]

        created_count = 0
        for data in asset_data:
            assigned_to = random.choice(users) if data.get('checked_out') and users else None

            asset = Asset.objects.create(
                name=data['name'],
                category=data['category'],
                serial_number=data['serial_number'],
                model=data['model'],
                manufacturer=data['manufacturer'],
                location=data['location'],
                purchase_date=data['purchase_date'],
                warranty_expiry=data['warranty_expiry'],
                status=data['status'],
                assigned_to=assigned_to,
                checked_out_to=assigned_to,
                notes=data['notes'],
            )

            AssetLog.objects.create(
                asset=asset,
                action=AssetLog.Action.CREATED,
                actor=actor,
                details={'source': 'seed_assets', 'initial_status': data['status']}
            )

            created_count += 1
            self.stdout.write(self.style.SUCCESS(f'✅ Created asset: {asset.tracking_id} - {asset.name}'))

        self.stdout.write(self.style.SUCCESS(f'\n🎉 Done! {created_count} new assets created.'))
