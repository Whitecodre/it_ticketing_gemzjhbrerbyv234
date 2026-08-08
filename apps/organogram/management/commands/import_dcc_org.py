from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.organogram.models import OrgPublished, OrgDraft
import json
from django.utils import timezone

User = get_user_model()

class Command(BaseCommand):
    help = 'Import DCC-provided organization structure from JSON file'

    def add_arguments(self, parser):
        parser.add_argument('json_file', type=str, help='Path to JSON file')
        parser.add_argument('--publish', action='store_true', help='Publish immediately')

    def handle(self, *args, **options):
        file_path = options['json_file']
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            # Validate structure
            if 'nodes' not in data:
                self.stderr.write('❌ Invalid structure: missing "nodes" key')
                return
            
            # Create or update published version
            admin = User.objects.filter(role='SUPERADMIN').first()
            if not admin:
                admin = User.objects.filter(is_superuser=True).first()
            
            if not admin:
                self.stderr.write('❌ No admin user found to assign as publisher')
                return
            
            # Delete existing published versions (or archive)
            OrgPublished.objects.all().delete()
            
            published = OrgPublished.objects.create(
                draft=None,  # No draft - DCC provided
                structure=data,
                name=data.get('name', 'DCC Organization Chart'),
                description=data.get('description', 'Provided by DCC'),
                version=1,
                department=data.get('department', ''),
                published_by=admin,
                published_at=timezone.now()
            )
            
            self.stdout.write(f'✅ DCC structure imported and published as v{published.version}')
            
        except FileNotFoundError:
            self.stderr.write(f'❌ File not found: {file_path}')
        except json.JSONDecodeError as e:
            self.stderr.write(f'❌ Invalid JSON: {e}')
        except Exception as e:
            self.stderr.write(f'❌ Error: {e}')