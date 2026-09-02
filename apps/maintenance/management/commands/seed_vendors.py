from django.core.management.base import BaseCommand

from apps.maintenance.models import Vendor
from apps.tickets.models import AssetCategory

# Each vendor's `categories` narrows the vendor picker wherever a category
# is already known (procurement requests, asset renewal) — see
# Vendor.categories on the model. Covers every category seed_asset_categories
# creates, some vendors spanning several related categories the way a real
# IT hardware reseller would, so the picker isn't empty for any category
# right after a fresh deploy.
VENDORS = [
    {
        'name': 'CompuTech Solutions',
        'contact_person': 'Adaeze Okonkwo',
        'phone': '+234 803 111 2222',
        'email': 'sales@computech-solutions.example.com',
        'notes': 'Primary supplier for desktops, laptops, and general IT hardware.',
        'categories': ['Computer', 'Laptop'],
    },
    {
        'name': 'ServerLine Systems',
        'contact_person': 'Tunde Bakare',
        'phone': '+234 803 222 3333',
        'email': 'accounts@serverline-systems.example.com',
        'notes': 'Enterprise server hardware and rack infrastructure.',
        'categories': ['Server'],
    },
    {
        'name': 'NetGear Distribution Ltd',
        'contact_person': 'Ifeoma Chukwu',
        'phone': '+234 803 333 4444',
        'email': 'orders@netgear-distribution.example.com',
        'notes': 'Switches, routers, and other network devices.',
        'categories': ['Network Device'],
    },
    {
        'name': 'PrintPoint Office Supplies',
        'contact_person': 'Emeka Nwosu',
        'phone': '+234 803 444 5555',
        'email': 'info@printpoint-supplies.example.com',
        'notes': 'Printers, toners, and consumables.',
        'categories': ['Printer'],
    },
    {
        'name': 'SoftLicense Nigeria',
        'contact_person': 'Bisi Adewale',
        'phone': '+234 803 555 6666',
        'email': 'licensing@softlicense-ng.example.com',
        'notes': 'Software license procurement and renewal (Microsoft, Adobe, antivirus, etc.).',
        'categories': ['Software License'],
    },
    {
        'name': 'General Office Equipment Co.',
        'contact_person': 'Yusuf Abdullahi',
        'phone': '+234 803 666 7777',
        'email': 'sales@generaloffice-equip.example.com',
        'notes': 'Catch-all supplier for miscellaneous/other asset types not covered elsewhere.',
        'categories': ['Other'],
    },
    {
        'name': 'Nationwide IT Partners',
        'contact_person': 'Chinwe Eze',
        'phone': '+234 803 777 8888',
        'email': 'partners@nationwide-it.example.com',
        'notes': 'Full-range IT reseller — computers, laptops, servers, and networking equipment.',
        'categories': ['Computer', 'Laptop', 'Server', 'Network Device'],
    },
]


class Command(BaseCommand):
    help = 'Seed sample vendors covering every default asset category (run after seed_asset_categories).'

    def handle(self, *args, **options):
        for entry in VENDORS:
            category_names = entry.pop('categories')
            vendor, created = Vendor.objects.get_or_create(
                name=entry['name'],
                defaults=entry,
            )
            categories = AssetCategory.objects.filter(name__in=category_names)
            vendor.categories.set(categories)
            entry['categories'] = category_names  # restore for idempotent re-runs
            if created:
                self.stdout.write(f'Created vendor: {vendor.name} ({categories.count()} categories)')
            else:
                self.stdout.write(f'Vendor already exists: {vendor.name} - categories synced')

        self.stdout.write(self.style.SUCCESS(f'Seeded {len(VENDORS)} vendor(s).'))
