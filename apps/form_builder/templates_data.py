# apps/form_builder/templates_data.py

TEMPLATES = {
    'CONTACT': {
        'name': 'Contact Form',
        'icon': '✉️',
        'description': 'A simple contact form with name, email, subject, and message fields.',
        'schema': {
            'fields': [
                {'id': 1, 'type': 'text', 'label': 'Full Name', 'key': 'full_name', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Enter your full name'},
                {'id': 2, 'type': 'email', 'label': 'Email Address', 'key': 'email', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Enter your email'},
                {'id': 3, 'type': 'text', 'label': 'Subject', 'key': 'subject', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Subject of your message'},
                {'id': 4, 'type': 'textarea', 'label': 'Message', 'key': 'message', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Write your message here...'},
            ]
        }
    },
    'INCIDENT_REPORT': {
        'name': 'Incident Report',
        'icon': '⚠️',
        'description': 'Report an incident with date, location, description, and priority.',
        'schema': {
            'fields': [
                {'id': 1, 'type': 'text', 'label': 'Report Title', 'key': 'title', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Brief title'},
                {'id': 2, 'type': 'date', 'label': 'Date of Incident', 'key': 'incident_date', 'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 3, 'type': 'text', 'label': 'Location', 'key': 'location', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Where did it happen?'},
                {'id': 4, 'type': 'select', 'label': 'Priority', 'key': 'priority', 'options': 'Low, Medium, High, Critical', 'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 5, 'type': 'textarea', 'label': 'Description', 'key': 'description', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Describe the incident in detail...'},
            ]
        }
    },
    'JOB_MOBILIZATION': {
        'name': 'Job Mobilization',
        'icon': '🚢',
        'description': 'Marine job mobilization form with vessel, job number, and crew details.',
        'schema': {
            'fields': [
                {'id': 1, 'type': 'text', 'label': 'Job Number', 'key': 'job_number', 'required': True, 'show_placeholder': False, 'placeholder_text': 'e.g., JOB-2026-001'},
                {'id': 2, 'type': 'text', 'label': 'Vessel Name', 'key': 'vessel', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Name of the vessel'},
                {'id': 3, 'type': 'date', 'label': 'Mobilization Date', 'key': 'mob_date', 'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 4, 'type': 'text', 'label': 'Port/Location', 'key': 'location', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Port or location'},
                {'id': 5, 'type': 'number', 'label': 'Number of Crew', 'key': 'crew_count', 'required': True, 'show_placeholder': False, 'placeholder_text': '0'},
                {'id': 6, 'type': 'textarea', 'label': 'Scope of Work', 'key': 'scope', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Describe the work to be done...'},
                {'id': 7, 'type': 'file', 'label': 'Attach Documents', 'key': 'attachments', 'required': False, 'show_placeholder': False, 'placeholder_text': ''},
            ]
        }
    },
    'EMPLOYEE_ONBOARDING': {
        'name': 'Employee Onboarding',
        'icon': '👤',
        'description': 'Onboard new employees with personal details, role, and equipment needs.',
        'schema': {
            'fields': [
                {'id': 1, 'type': 'text', 'label': 'Employee Name', 'key': 'name', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Full name'},
                {'id': 2, 'type': 'email', 'label': 'Email Address', 'key': 'email', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Corporate email'},
                {'id': 3, 'type': 'text', 'label': 'Job Title', 'key': 'job_title', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Position'},
                {'id': 4, 'type': 'text', 'label': 'Department', 'key': 'department', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Department name'},
                {'id': 5, 'type': 'date', 'label': 'Start Date', 'key': 'start_date', 'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 6, 'type': 'select', 'label': 'Equipment Needed', 'key': 'equipment', 'options': 'Laptop, Desktop, Monitor, Phone, Other', 'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 7, 'type': 'textarea', 'label': 'Additional Notes', 'key': 'notes', 'required': False, 'show_placeholder': False, 'placeholder_text': 'Any special requirements...'},
            ]
        }
    },
    'FEEDBACK': {
        'name': 'Feedback Form',
        'icon': '⭐',
        'description': 'Collect feedback with ratings and comments.',
        'schema': {
            'fields': [
                {'id': 1, 'type': 'text', 'label': 'Your Name', 'key': 'name', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Your name'},
                {'id': 2, 'type': 'email', 'label': 'Email (Optional)', 'key': 'email', 'required': False, 'show_placeholder': False, 'placeholder_text': 'your@email.com'},
                {'id': 3, 'type': 'select', 'label': 'Rating', 'key': 'rating', 'options': '⭐ Excellent, ⭐⭐ Good, ⭐⭐⭐ Average, ⭐⭐⭐⭐ Poor, ⭐⭐⭐⭐⭐ Very Poor', 'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 4, 'type': 'textarea', 'label': 'Feedback', 'key': 'feedback', 'required': True, 'show_placeholder': False, 'placeholder_text': 'Share your thoughts...'},
            ]
        }
    },
    'SURVEY': {
        'name': 'Survey Form',
        'icon': '📊',
        'description': 'General survey with multiple question types.',
        'schema': {
            'fields': [
                {'id': 1, 'type': 'text', 'label': 'Name (Optional)', 'key': 'name', 'required': False, 'show_placeholder': False, 'placeholder_text': 'Your name'},
                {'id': 2, 'type': 'radio', 'label': 'Overall Experience', 'key': 'experience', 'options': 'Excellent, Good, Average, Poor', 'required': True, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 3, 'type': 'checkbox', 'label': 'Services Used', 'key': 'services', 'required': False, 'show_placeholder': False, 'placeholder_text': ''},
                {'id': 4, 'type': 'textarea', 'label': 'Suggestions for Improvement', 'key': 'suggestions', 'required': False, 'show_placeholder': False, 'placeholder_text': 'How can we improve?'},
            ]
        }
    },
}