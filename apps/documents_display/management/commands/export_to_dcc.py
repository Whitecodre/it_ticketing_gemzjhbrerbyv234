# apps/documents_display/management/commands/export_to_dcc.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.documents_display.models import DisplayDocument
import json


class Command(BaseCommand):
    help = 'Export display documents for DCC system import'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default='dcc_export.json',
            help='Output file path'
        )
        parser.add_argument(
            '--pretty',
            action='store_true',
            help='Pretty print JSON'
        )

    def handle(self, *args, **options):
        export_data = {
            'version': '1.0',
            'export_date': timezone.now().isoformat(),
            'documents': []
        }

        for doc in DisplayDocument.objects.filter(is_deleted=False):
            export_data['documents'].append({
                'title': doc.title,
                'category': doc.category.name,
                'content': doc.content,
                'file_url': doc.file.url if doc.file else None,
                'file_name': doc.file_name,
                'version': doc.version,
                'created_by': doc.created_by.email,
                'created_at': doc.created_at.isoformat(),
                'updated_at': doc.updated_at.isoformat(),
                'tags': doc.tags,
                'version_history': [
                    {
                        'version': v.version_number,
                        'content': v.content,
                        'created_by': v.created_by.email,
                        'created_at': v.created_at.isoformat(),
                    }
                    for v in doc.versions.all()
                ]
            })

        with open(options['output'], 'w') as f:
            if options['pretty']:
                json.dump(export_data, f, indent=2)
            else:
                json.dump(export_data, f)

        self.stdout.write(self.style.SUCCESS(
            f'✅ Exported {len(export_data["documents"])} documents to {options["output"]}'
        ))