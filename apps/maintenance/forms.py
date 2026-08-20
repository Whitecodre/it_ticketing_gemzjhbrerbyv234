# apps/maintenance/forms.py
from django import forms
from django.contrib.auth import get_user_model
from .models import MaintenanceSchedule, Vendor
from apps.tickets.models import Asset

User = get_user_model()


class MaintenanceScheduleForm(forms.ModelForm):
    """Form for creating/editing maintenance schedules."""

    # ArrayField's auto-generated ModelForm field is a comma-separated
    # SimpleArrayField text input — overridden here with a real multi-select
    # so a schedule can target several under-loaded departments at once.
    departments = forms.MultipleChoiceField(
        choices=MaintenanceSchedule.Department.choices,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label='Target Department(s)',
    )

    checklist_items = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Enter each checklist item on a new line...',
            'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2'
        }),
        help_text='One item per line'
    )

    additional_assignees = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Additional Personnel',
        help_text='Anyone else on this schedule besides the primary assignee above.',
    )

    target_assets = forms.ModelMultipleChoiceField(
        queryset=Asset.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Target Asset(s)',
        help_text='Tracked assets undergoing this maintenance (optional).',
    )

    vendors = forms.ModelMultipleChoiceField(
        queryset=Vendor.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label='Third-Party Vendor(s)',
        help_text='Record-keeping only — vendors are not assignees and cannot change this schedule\'s status.',
    )

    class Meta:
        model = MaintenanceSchedule
        fields = [
            'title', 'description', 'departments', 'scheduled_date',
            'start_time', 'end_time', 'assigned_to', 'additional_assignees',
            'target_assets', 'facility_location', 'vendors',
        ]
        widgets = {
            'facility_location': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2',
                'placeholder': 'e.g., Server Room A, Generator House'
            }),
            'title': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2',
                'placeholder': 'e.g., Monthly IT Audit - Accounting'
            }),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full rounded-lg border px-4 py-2.5 text-sm focus:outline-none focus:ring-2',
                'placeholder': 'Details about the maintenance work...'
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

        self.fields['additional_assignees'].queryset = User.objects.filter(
            role__in=it_roles,
            is_active=True
        ).order_by('first_name', 'last_name')
        self.fields['additional_assignees'].label_from_instance = lambda obj: (
            obj.get_full_name() or obj.email
        )

        # Exclude assets that are no longer usable/trackable from the
        # target-asset picker, and narrow to the posted department(s) (when
        # bound) so a tampered POST can't attach an out-of-department asset
        # — the department-scoped picker in the template is a UX filter,
        # this is the actual validation boundary.
        excluded_statuses = [
            Asset.Status.RETIRED, Asset.Status.SCRAPPED, Asset.Status.DISPOSED,
            Asset.Status.LOST, Asset.Status.STOLEN,
        ]
        assets_qs = Asset.objects.exclude(status__in=excluded_statuses)
        posted_departments = self.data.getlist('departments') if self.data else []
        if posted_departments:
            assets_qs = assets_qs.filter(department__in=posted_departments)
        self.fields['target_assets'].queryset = assets_qs.order_by('name')
        self.fields['target_assets'].label_from_instance = lambda obj: (
            f"{obj.name} ({obj.tracking_id})"
        )

        self.fields['vendors'].queryset = Vendor.objects.filter(is_active=True).order_by('name')

        # If editing, pre-populate checklist_items as text
        if self.instance and self.instance.pk and self.instance.checklist_items:
            self.initial['checklist_items'] = '\n'.join(self.instance.checklist_items)

    def clean_checklist_items(self):
        """Collect all posted checklist_items values — both the picklist
        checkboxes and any freeform "custom item" inputs share this same
        field name, and QueryDict collapses repeated keys to the last one
        via plain .get(), so we must read the full list explicitly."""
        items = []
        if self.data:
            items = [v.strip() for v in self.data.getlist('checklist_items') if v.strip()]
        # De-duplicate while preserving order.
        seen = set()
        deduped = []
        for item in items:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped


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


class MaintenanceAssetConfirmForm(forms.Form):
    """Form for an asset owner (or fallback confirmer) to confirm or dispute
    that maintenance was actually carried out on one of their assets."""

    DECISION_CHOICES = [
        ('CONFIRMED', 'Confirm — the work was done'),
        ('DISPUTED', 'Dispute — something is wrong'),
    ]

    decision = forms.ChoiceField(
        choices=DECISION_CHOICES,
        widget=forms.RadioSelect,
        label='Decision',
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'class': 'w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2',
            'placeholder': 'Any notes about the maintenance...'
        })
    )
    dispute_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'class': 'w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2',
            'placeholder': 'What is wrong with the work performed?'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('decision') == 'DISPUTED' and not cleaned_data.get('dispute_reason', '').strip():
            self.add_error('dispute_reason', 'Please explain what is wrong so it can be addressed.')
        return cleaned_data