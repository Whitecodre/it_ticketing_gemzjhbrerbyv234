# apps/form_builder/management/commands/migrate_forms.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.form_builder.models import FormDefinition, FormSubmission
from apps.tickets.models import Ticket, TicketComment

User = get_user_model()


class Command(BaseCommand):
    help = 'Migrate hardcoded forms to dynamic forms'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--migrate-data',
            action='store_true',
            help='Migrate existing ticket data to form submissions',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
    
    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        migrate_data = options.get('migrate_data', False)
        
        self.stdout.write('🔄 Starting form migration...')
        
        # Get or create admin user for creation
        admin_user = User.objects.filter(role='SUPERADMIN').first()
        if not admin_user:
            admin_user = User.objects.filter(is_superuser=True).first()
            if not admin_user:
                self.stdout.write(self.style.ERROR('No admin user found. Create a superuser first.'))
                return
        
        self.stdout.write(f'Using admin: {admin_user.email}')
        
        # Define form schemas
        forms = self.get_form_schemas()
        
        created_forms = []
        updated_forms = []
        
        for slug, data in forms.items():
            if dry_run:
                self.stdout.write(f'[DRY RUN] Would create/update: {slug}')
                continue
            
            form, created = FormDefinition.objects.get_or_create(
                slug=slug,
                defaults={
                    'title': data['title'],
                    'description': data.get('description', ''),
                    'status': 'PUBLISHED',
                    'schema': {'fields': data['fields']},
                    'created_by': admin_user,
                    'require_login': data.get('require_login', True),
                    'confirmation_message': data.get('confirmation_message', 'Thank you! Your submission has been received.'),
                    'redirect_url': data.get('redirect_url', ''),
                    'form_type': data.get('form_type', 'OTHER'),
                }
            )
            
            if not created:
                # Update existing form
                form.title = data['title']
                form.schema = {'fields': data['fields']}
                form.save(update_fields=['title', 'schema'])
                updated_forms.append(slug)
            else:
                created_forms.append(slug)
            
            self.stdout.write(f"{'✅ Created' if created else '📝 Updated'} {slug}: {data['title']}")
        
        self.stdout.write(f'\n📊 Summary:')
        self.stdout.write(f'  Created: {len(created_forms)}')
        self.stdout.write(f'  Updated: {len(updated_forms)}')
        
        # Migrate existing ticket data
        if migrate_data:
            self.stdout.write('\n🔄 Migrating existing ticket data...')
            self.migrate_ticket_data(dry_run=dry_run)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n⚠️ Dry run completed. No changes made.'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✅ Migration completed successfully!'))
    
    def get_form_schemas(self):
        """Define all form schemas."""
        return {
            'incident-report': {
                'title': 'Incident Report',
                'description': 'Report an IT incident or issue',
                'form_type': 'INCIDENT',
                'require_login': True,
                'confirmation_message': 'Thank you! Your incident has been reported and assigned to our support team.',
                'redirect_url': '/tickets/my/',
                'fields': [
                    {'id': 1, 'type': 'text', 'label': 'Incident Title', 'key': 'title', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Brief summary of the issue'},
                    {'id': 2, 'type': 'textarea', 'label': 'Description', 'key': 'description', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Describe the issue in detail...'},
                    {'id': 3, 'type': 'date', 'label': 'Date of Incident', 'key': 'incident_date', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 4, 'type': 'text', 'label': 'Location', 'key': 'location', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Where did this occur?'},
                    {'id': 5, 'type': 'select', 'label': 'Priority', 'key': 'priority', 
                     'options': 'Low, Medium, High, Critical', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 6, 'type': 'select', 'label': 'Impact', 'key': 'impact', 
                     'options': 'Individual, Department, Site, Organization', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 7, 'type': 'file', 'label': 'Attachments', 'key': 'attachments', 
                     'required': False, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 8, 'type': 'select', 'label': 'Department', 'key': 'department', 
                     'options': 'IT, Accounting, HR, Operations, Legal, QHSE, Marine, Other', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                ]
            },
            'service-request': {
                'title': 'Service Request',
                'description': 'Request a service or resource',
                'form_type': 'SERVICE_REQUEST',
                'require_login': True,
                'confirmation_message': 'Your service request has been submitted and is awaiting manager review.',
                'redirect_url': '/tickets/my/',
                'fields': [
                    {'id': 1, 'type': 'text', 'label': 'Request Title', 'key': 'title', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'What do you need?'},
                    {'id': 2, 'type': 'textarea', 'label': 'Description', 'key': 'description', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Describe what you need and why...'},
                    {'id': 3, 'type': 'text', 'label': 'Department', 'key': 'department', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Your department'},
                    {'id': 4, 'type': 'select', 'label': 'Priority', 'key': 'priority', 
                     'options': 'Low, Medium, High', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 5, 'type': 'date', 'label': 'Required By', 'key': 'required_by', 
                     'required': False, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 6, 'type': 'select', 'label': 'Category', 'key': 'category', 
                     'options': 'Hardware, Software, Access, Training, Other', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 7, 'type': 'file', 'label': 'Attachments', 'key': 'attachments', 
                     'required': False, 'show_placeholder': False, 'placeholder_text': ''},
                ]
            },
            'job-mobilization': {
                'title': 'Job Mobilization',
                'description': 'Request mobilization of a job',
                'form_type': 'MOBILIZATION',
                'require_login': True,
                'confirmation_message': 'Job mobilization request submitted successfully.',
                'redirect_url': '/dashboard/',
                'fields': [
                    {'id': 1, 'type': 'text', 'label': 'Job Number', 'key': 'job_number', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'e.g., JOB-2026-001'},
                    {'id': 2, 'type': 'text', 'label': 'Vessel Name', 'key': 'vessel', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Name of the vessel'},
                    {'id': 3, 'type': 'date', 'label': 'Mobilization Date', 'key': 'mob_date', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 4, 'type': 'text', 'label': 'Port/Location', 'key': 'location', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Port or location'},
                    {'id': 5, 'type': 'number', 'label': 'Number of Crew', 'key': 'crew_count', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': '0'},
                    {'id': 6, 'type': 'textarea', 'label': 'Scope of Work', 'key': 'scope', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Describe the work to be done...'},
                    {'id': 7, 'type': 'file', 'label': 'Attach Documents', 'key': 'attachments', 
                     'required': False, 'show_placeholder': False, 'placeholder_text': ''},
                ]
            },
            'job-return': {
                'title': 'Job Return',
                'description': 'Return from a completed job',
                'form_type': 'RETURN',
                'require_login': True,
                'confirmation_message': 'Job return logged successfully.',
                'redirect_url': '/dashboard/',
                'fields': [
                    {'id': 1, 'type': 'text', 'label': 'Job Number', 'key': 'job_number', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'e.g., JOB-2026-001'},
                    {'id': 2, 'type': 'date', 'label': 'Return Date', 'key': 'return_date', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 3, 'type': 'select', 'label': 'Equipment Status', 'key': 'equipment_status', 
                     'options': 'Good, Fair, Poor, Damaged, Lost', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 4, 'type': 'textarea', 'label': 'Notes', 'key': 'notes', 
                     'required': False, 'show_placeholder': True, 'placeholder_text': 'Any additional notes...'},
                    {'id': 5, 'type': 'file', 'label': 'Attach Documents', 'key': 'attachments', 
                     'required': False, 'show_placeholder': False, 'placeholder_text': ''},
                ]
            },
            'feedback': {
                'title': 'Feedback Form',
                'description': 'Submit feedback about your experience',
                'form_type': 'FEEDBACK',
                'require_login': False,
                'confirmation_message': 'Thank you for your feedback!',
                'redirect_url': '/dashboard/',
                'fields': [
                    {'id': 1, 'type': 'text', 'label': 'Your Name', 'key': 'name', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Your name'},
                    {'id': 2, 'type': 'email', 'label': 'Email (Optional)', 'key': 'email', 
                     'required': False, 'show_placeholder': True, 'placeholder_text': 'your@email.com'},
                    {'id': 3, 'type': 'select', 'label': 'Rating', 'key': 'rating', 
                     'options': '⭐ Excellent, ⭐⭐ Good, ⭐⭐⭐ Average, ⭐⭐⭐⭐ Poor, ⭐⭐⭐⭐⭐ Very Poor', 
                     'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                    {'id': 4, 'type': 'textarea', 'label': 'Feedback', 'key': 'feedback', 
                     'required': True, 'show_placeholder': True, 'placeholder_text': 'Share your thoughts...'},
                ]
            },
        }
    
    def migrate_ticket_data(self, dry_run=False):
        """Migrate existing tickets to form submissions."""
        incident_form = FormDefinition.objects.filter(slug='incident-report').first()
        service_form = FormDefinition.objects.filter(slug='service-request').first()
        
        if not incident_form and not service_form:
            self.stdout.write(self.style.WARNING('Forms not found. Run migration first.'))
            return
        
        incident_count = 0
        service_count = 0
        
        # Migrate incident tickets
        if incident_form:
            tickets = Ticket.objects.filter(type='INCIDENT')
            for ticket in tickets:
                if dry_run:
                    incident_count += 1
                    continue
                
                # Check if already migrated
                if FormSubmission.objects.filter(
                    form=incident_form,
                    data__ticket_id=ticket.pk
                ).exists():
                    continue
                
                data = {
                    'title': ticket.title,
                    'description': ticket.description,
                    'priority': ticket.get_priority_display() if ticket.priority else 'Medium',
                    'impact': ticket.get_impact_display() if ticket.impact else 'Individual',
                    'status': ticket.get_status_display() if ticket.status else 'New',
                    'department': ticket.requester.department if ticket.requester else '',
                    'ticket_id': ticket.pk,
                }
                
                FormSubmission.objects.create(
                    form=incident_form,
                    submitted_by=ticket.requester,
                    data=data,
                    submitted_at=ticket.created_at,
                )
                incident_count += 1
        
        # Migrate service request tickets
        if service_form:
            tickets = Ticket.objects.filter(type='SERVICE_REQUEST')
            for ticket in tickets:
                if dry_run:
                    service_count += 1
                    continue
                
                if FormSubmission.objects.filter(
                    form=service_form,
                    data__ticket_id=ticket.pk
                ).exists():
                    continue
                
                data = {
                    'title': ticket.title,
                    'description': ticket.description,
                    'priority': ticket.get_priority_display() if ticket.priority else 'Medium',
                    'category': ticket.category.name if ticket.category else 'Other',
                    'department': ticket.requester.department if ticket.requester else '',
                    'ticket_id': ticket.pk,
                }
                
                FormSubmission.objects.create(
                    form=service_form,
                    submitted_by=ticket.requester,
                    data=data,
                    submitted_at=ticket.created_at,
                )
                service_count += 1
        
        self.stdout.write(f'  Incident submissions: {incident_count}')
        self.stdout.write(f'  Service request submissions: {service_count}')