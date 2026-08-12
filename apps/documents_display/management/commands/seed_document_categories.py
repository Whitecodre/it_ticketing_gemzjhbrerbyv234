# apps/documents_display/management/commands/seed_document_categories.py
# Named distinctly from apps/tickets/management/commands/seed_categories.py
# (which seeds unrelated ticket Category records) to avoid a Django
# management-command name collision between the two apps.
from django.core.management.base import BaseCommand
from apps.documents_display.models import DisplayCategory

# Mirrors the organization's real document folder structure. A few names
# were rephrased into a plain "adjective noun" description of the category
# (e.g. "Minutes of Meeting" -> "Meeting Minutes", "Onboarding New Employee"
# -> "Employee Onboarding") rather than the original verb-first/abbreviated
# phrasing.
DEFAULT_CATEGORIES = [
    ('Access Control', 'key', 'Access permissions, login credentials, and system access records'),
    ('Acknowledgement & Request', 'clipboard-check', 'Signed acknowledgements and formal requests'),
    ('Asset Disposal', 'trash-2', 'Records of retired, scrapped, or disposed assets'),
    ('Audit Status', 'search-check', 'Audit findings, tracking, and status updates'),
    ('Backup & Maintenance', 'wrench', 'System backup logs and maintenance records'),
    ('IT Infrastructure', 'server', 'Network diagrams, server documentation, and infrastructure records'),
    ('Job Description', 'briefcase', 'Role and job description documents'),
    ('Knowledge Sharing', 'share-2', 'Guides, write-ups, and shared team knowledge'),
    ('KPI & Objectives', 'target', 'Key performance indicators and objective-setting documents'),
    ('Meeting Minutes', 'clipboard', 'Minutes and notes from meetings'),
    ('Network Issues', 'network', 'Network incident reports and troubleshooting records'),
    ('New & Reviewed Documents', 'file-check', 'Recently added or reviewed documents pending wider circulation'),
    ('Employee Onboarding', 'user-plus', 'Onboarding checklists and new-employee documentation'),
    ('Organogram', 'network', 'Organizational structure and reporting-line documents'),
    ('Policies & Procedures', 'book-text', 'Company policies and standard operating procedures'),
    ('Safety Tips & Surveys', 'shield-alert', 'Safety guidance, tips, and survey results'),
    ('Service Tracker', 'list-checks', 'Service request and fulfillment tracking documents'),
    ('Software & Licenses', 'package', 'Software licenses, keys, and subscription records'),
    ('Training', 'graduation-cap', 'Training materials, records, and certifications'),
    ('Vendors & SLA', 'handshake', 'Vendor contracts and service-level agreements'),
]


class Command(BaseCommand):
    help = 'Seed default document categories (idempotent — only creates categories that do not already exist).'

    def handle(self, *args, **options):
        created_count = 0
        for order, (name, icon, description) in enumerate(DEFAULT_CATEGORIES):
            _category, created = DisplayCategory.objects.get_or_create(
                name=name,
                defaults={'icon': icon, 'description': description, 'display_order': order},
            )
            if created:
                created_count += 1

        if created_count:
            self.stdout.write(self.style.SUCCESS(f'✅ Created {created_count} document categor{"y" if created_count == 1 else "ies"}.'))
        else:
            self.stdout.write(self.style.WARNING('⚠️ All default document categories already exist. Nothing to do.'))
