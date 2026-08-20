from django.core.management.base import BaseCommand
from django.utils.text import slugify
from apps.tickets.models import ServiceCategory

CATEGORIES = [
    # (name, field_group, icon, description) — strictly IT service categories;
    # any department can submit against them. Vessel/Job Number/Dive System
    # are separate global optional fields on every request, not categories.
    ("Hardware Support", "ASSET", "laptop", "Issues with laptops, desktops, monitors, printers, or other physical IT equipment"),
    ("Equipment Request", "ASSET", "package-plus", "Request new IT equipment (laptop, phone, peripherals)"),
    ("Software & Licensing", "GENERAL", "app-window", "Software installation, updates, or licensing requests"),
    ("Network & Connectivity", "GENERAL", "wifi", "Internet, VPN, or network connectivity issues"),
    ("Account & Access", "GENERAL", "key", "New accounts, password resets, or permission/access changes"),
    ("Email & Communication", "GENERAL", "mail", "Email, Teams, or other communication tool support"),
    ("IT Consultation", "GENERAL", "message-circle-question", "General IT advice or consultation"),
    ("Other IT Support", "GENERAL", "circle-help", "Anything else IT-related not covered above"),
]


class Command(BaseCommand):
    help = 'Seed the initial Service Request categories'

    def handle(self, *args, **options):
        if ServiceCategory.objects.exists():
            self.stdout.write(self.style.WARNING('⚠️ Service categories already exist. Skipping seeding to avoid duplicates.'))
            self.stdout.write(self.style.WARNING(f'   Current category count: {ServiceCategory.objects.count()}'))
            return
        for order, (name, field_group, icon, description) in enumerate(CATEGORIES):
            category, created = ServiceCategory.objects.get_or_create(
                name=name,
                defaults={
                    'slug': slugify(name),
                    'field_group': field_group,
                    'icon': icon,
                    'description': description,
                    'order': order,
                },
            )
            if created:
                self.stdout.write(f'Created service category: {name}')
            else:
                self.stdout.write(f'Service category already exists: {name}')
        self.stdout.write(self.style.SUCCESS('Service categories seeded.'))
