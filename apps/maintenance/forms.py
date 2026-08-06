# apps/maintenance/forms.py
from django import forms
from django.contrib.auth import get_user_model
from .models import MaintenanceSchedule

User = get_user_model()


class MaintenanceScheduleForm(forms.ModelForm):
    """Form for creating/editing maintenance schedules."""
    
    checklist_items = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Enter each checklist item on a new line...',
            'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2'
        }),
        help_text='One item per line'
    )
    
    class Meta:
        model = MaintenanceSchedule
        fields = [
            'title', 'description', 'department', 'scheduled_date',
            'start_time', 'end_time', 'assigned_to'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2',
                'placeholder': 'e.g., Monthly IT Audit - Accounting'
            }),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2',
                'placeholder': 'Details about the maintenance work...'
            }),
            'department': forms.Select(attrs={
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2'
            }),
            'scheduled_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2'
            }),
            'start_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2'
            }),
            'end_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2'
            }),
            'assigned_to': forms.Select(attrs={
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filter assigned_to to only IT staff
        it_roles = ['SUPERADMIN', 'ADMIN', 'TEAM_LEAD', 'AGENT']
        self.fields['assigned_to'].queryset = User.objects.filter(
            role__in=it_roles,
            is_active=True
        ).order_by('first_name', 'last_name')
        
        self.fields['assigned_to'].label_from_instance = lambda obj: (
            obj.get_full_name() or obj.email
        )
        
        # If editing, pre-populate checklist_items as text
        if self.instance and self.instance.pk and self.instance.checklist_items:
            self.initial['checklist_items'] = '\n'.join(self.instance.checklist_items)
    
    def clean_checklist_items(self):
        """Convert textarea lines to list."""
        text = self.cleaned_data.get('checklist_items', '')
        if not text:
            return []
        # Split by newline and strip empty
        items = [line.strip() for line in text.split('\n') if line.strip()]
        return items


class MaintenanceStatusForm(forms.Form):
    """Form for updating maintenance status."""
    
    status = forms.ChoiceField(
        choices=MaintenanceSchedule.Status.choices,
        widget=forms.RadioSelect
    )
    comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'class': 'w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2',
            'placeholder': 'Reason for status change...'
        })
    )


class MaintenanceConfirmForm(forms.Form):
    """Form for manager confirmation."""
    
    comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'class': 'w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2',
            'placeholder': 'Any notes about the maintenance...'
        })
    )