# apps/organogram/forms.py
from django import forms
from .models import OrgDraft


class OrgDraftForm(forms.ModelForm):
    """Form for creating/editing organization organogram drafts."""
    
    class Meta:
        model = OrgDraft
        fields = ['name', 'description', 'department', 'change_summary']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Enter organogram name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'rows': 3,
                'placeholder': 'Describe this organogram...'
            }),
            'department': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'change_summary': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'rows': 2,
                'placeholder': 'Summary of changes made...'
            }),
        }