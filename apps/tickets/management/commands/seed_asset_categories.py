from django.core.management.base import BaseCommand
from apps.tickets.models import AssetCategory

CATEGORIES = [
    "Computer",
    "Laptop",
    "Server",
    "Network Device",
    "Printer",
    "Software License",
]


class Command(BaseCommand):
    help = 'Seed the default asset categories (replaces the old hardcoded asset_type list)'

    def handle(self, *args, **options):
        for name in CATEGORIES:
            category, created = AssetCategory.objects.get_or_create(name=name)
            if created:
                self.stdout.write(f'Created asset category: {name}')
            else:
                self.stdout.write(f'Asset category already exists: {name}')
        self.stdout.write(self.style.SUCCESS('Asset categories seeded.'))
