# apps/documents_display/forms.py

from django import forms
from .models import DisplayDocument
from apps.accounts.models import User


CHECKBOX_ATTRS = {'class': 'rounded border-border text-primary focus:ring-primary'}
SELECT_ATTRS = {
    'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
}


class DisplayDocumentForm(forms.ModelForm):
    visibility = forms.ChoiceField(
        choices=DisplayDocument.Visibility.choices,
        initial=DisplayDocument.Visibility.PUBLIC,
        widget=forms.Select(attrs=SELECT_ATTRS)
    )
    public_can_edit = forms.BooleanField(
        required=False,
        label="Everyone can edit",
        widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS)
    )
    public_can_download = forms.BooleanField(
        required=False,
        label="Everyone can download",
        widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS)
    )
    version_comment = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'What changed? (optional)'
        })
    )

    class Meta:
        model = DisplayDocument
        fields = [
            'title', 'category', 'file', 'document_date', 'visibility',
            'public_can_edit', 'public_can_download',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Document title...'
            }),
            'category': forms.Select(attrs=SELECT_ATTRS),
            'file': forms.FileInput(attrs={
                'class': 'block w-full text-sm text-text-secondary file:mr-4 file:py-2.5 file:px-5 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-primary/10 file:text-primary hover:file:bg-primary/20 transition cursor-pointer'
            }),
            'document_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].empty_label = "-- Select Category --"


class DepartmentAccessForm(forms.Form):
    """One row of the per-department permission matrix on the document form."""
    department = forms.ChoiceField(choices=User.DEPARTMENT_CHOICES, widget=forms.HiddenInput)
    grant = forms.BooleanField(required=False, label="Access", widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS))
    can_edit = forms.BooleanField(required=False, label="Edit", widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS))
    can_download = forms.BooleanField(required=False, label="Download", widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS))

    def clean(self):
        cleaned = super().clean()
        # Edit/download always implies at least read access, even if "Access" wasn't ticked.
        if cleaned.get('can_edit') or cleaned.get('can_download'):
            cleaned['grant'] = True
        return cleaned


DepartmentAccessFormSet = forms.formset_factory(DepartmentAccessForm, extra=0)


def build_department_access_initial(document=None):
    """Initial data for DepartmentAccessFormSet: one row per department, pre-filled from
    the document's existing DocumentDepartmentAccess rows when editing."""
    existing = {}
    if document and document.pk:
        existing = {a.department: a for a in document.department_access.all()}
    return [
        {
            'department': code,
            'grant': code in existing,
            'can_edit': existing[code].can_edit if code in existing else False,
            'can_download': existing[code].can_download if code in existing else False,
        }
        for code, _label in User.DEPARTMENT_CHOICES
    ]


class ShareDocumentForm(forms.Form):
    """Share with either an existing in-system user (`recipient`) or a raw
    external email address with no account (`external_email`) - exactly one
    of the two, enforced in clean(). Expiration is optional for internal
    shares (preserves prior behavior) but required for external ones, since
    a no-login link with no expiry is a materially bigger risk than one
    tied to a real account."""
    recipient = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('department', 'first_name', 'last_name'),
        required=False,
        widget=forms.Select(attrs=SELECT_ATTRS),
        help_text="Must be an existing, active account."
    )
    external_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'someone@example.com'
        }),
        help_text="No account needed - the link itself grants access."
    )
    can_edit = forms.BooleanField(required=False, label="Can edit", widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS))
    can_download = forms.BooleanField(required=False, label="Can download", widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS))
    expires_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        }),
        help_text="Optional for internal shares. Required for external email shares."
    )

    def clean(self):
        cleaned = super().clean()
        recipient = cleaned.get('recipient')
        external_email = cleaned.get('external_email')
        if bool(recipient) == bool(external_email):
            raise forms.ValidationError('Choose an existing user OR enter an email address - not both, not neither.')
        if external_email and not cleaned.get('expires_at'):
            raise forms.ValidationError('External email shares must have an expiration date.')
        return cleaned
