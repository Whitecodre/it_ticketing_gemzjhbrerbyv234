# apps/documents_display/forms.py

import re

from django import forms
from django.urls import reverse_lazy
from .models import DisplayDocument, DisplayCategory, DocumentFolder
from apps.accounts.models import User

# Splits a pasted email list on commas, whitespace, or newlines - covers
# "a@x.com, b@x.com", "a@x.com b@x.com" and one-per-line alike.
EMAIL_SPLIT_RE = re.compile(r'[\s,]+')

SHARE_TYPE_CHOICES = [('internal', 'Existing user in the system'), ('external', 'External email address')]
SHARE_MODE_CHOICES = [('single', 'Single'), ('multiple', 'Multiple')]


def get_multi_values(data, name):
    """QueryDict.getlist() equivalent that also works when `data` is a
    plain dict, as when a form is constructed directly in a unit test
    (data={'external_emails': 'a@b.com'}) rather than bound from a real
    POST's QueryDict."""
    if hasattr(data, 'getlist'):
        return data.getlist(name)
    value = data.get(name)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_email_list(raw, form, field_name):
    """Split, validate, and de-dupe (case-insensitive) a textarea of email
    addresses. Invalid entries are added as field errors on `form` rather
    than silently dropped. Returns the list of valid, deduped addresses in
    their original casing."""
    candidates = [e for e in EMAIL_SPLIT_RE.split(raw.strip()) if e]
    validator = forms.EmailField()
    emails = []
    seen = set()
    for candidate in candidates:
        try:
            validator.clean(candidate)
        except forms.ValidationError:
            form.add_error(field_name, f'"{candidate}" is not a valid email address.')
            continue
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            emails.append(candidate)
    return emails


CHECKBOX_ATTRS = {'class': 'rounded border-border text-primary focus:ring-primary'}
SELECT_ATTRS = {
    'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
}
# Shared HTMX wiring for the "pick a department, then narrow the recipient
# list" pattern (see accounts:department_users_partial). `hx-target` is set
# per-field to the actual target <select>'s id.
DEPARTMENT_FILTER_ATTRS = {
    'hx-get': reverse_lazy('accounts:department_users_partial'),
    'hx-target': '#id_recipient',
    'hx-trigger': 'change',
    'hx-include': 'this',
    'hx-swap': 'innerHTML',
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

    # Overridden to a plain CharField so it can hold either an existing
    # category's pk or the sentinel 'OTHER' — mirrors the ticket form's
    # category/category_other pattern (apps/tickets/forms.py).
    category = forms.CharField(
        required=True,
        widget=forms.Select(attrs=SELECT_ATTRS),
    )
    category_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter custom category...',
            'id': 'category_other',
        }),
        label='Custom Category',
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
        categories = DisplayCategory.objects.filter(is_active=True).order_by('display_order', 'name').values_list('id', 'name')
        self.fields['category'].widget.choices = (
            [('', '-- Select Category --')] + list(categories) + [('OTHER', '+ Add Custom Category')]
        )

        # If editing and the category isn't in the active list (e.g. was
        # deactivated), show it as a custom entry instead of silently
        # dropping the selection.
        instance = kwargs.get('instance')
        if instance and instance.category_id:
            category_ids = [c[0] for c in categories]
            if instance.category_id not in category_ids:
                self.fields['category'].initial = 'OTHER'
                self.initial['category_other'] = instance.category.name
            else:
                self.fields['category'].initial = instance.category_id

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        category_other = cleaned_data.get('category_other', '').strip()

        if category == 'OTHER':
            if category_other:
                category_obj, _created = DisplayCategory.objects.get_or_create(name=category_other)
                cleaned_data['category'] = category_obj
            else:
                self.add_error('category_other', 'Please enter a custom category.')
        elif category:
            try:
                cleaned_data['category'] = DisplayCategory.objects.get(pk=category)
            except (DisplayCategory.DoesNotExist, ValueError):
                self.add_error('category', 'Please select a valid category.')
        return cleaned_data


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
    """Share with either an existing in-system user (or several) or one or
    more raw external email addresses with no account - `share_type`
    (internal/external) and `share_mode` (single/multiple) together pick
    which of recipient/recipients/external_email/external_emails is
    actually read; the rest are ignored. clean() resolves all of that into
    `cleaned_data['targets']`, a list of {'recipient': user} or
    {'external_email': email} dicts the view can loop over to create one
    DocumentShare per target - all sharing the same can_edit/can_download/
    expires_at. Expiration is optional for internal shares (preserves prior
    behavior) but required for external ones, since a no-login link with no
    expiry is a materially bigger risk than one tied to a real account."""
    # Not required: a submit that omits them entirely (e.g. a pre-existing
    # integration, or the field simply not rendered) falls back to
    # inferring share_type/share_mode from which of the target fields
    # were actually filled in - see clean() below.
    share_type = forms.ChoiceField(
        choices=SHARE_TYPE_CHOICES, initial='internal', required=False, widget=forms.RadioSelect,
    )
    share_mode = forms.ChoiceField(
        choices=SHARE_MODE_CHOICES, initial='single', required=False, widget=forms.RadioSelect,
    )
    recipient_department = forms.ChoiceField(
        required=False,
        label='Department',
        widget=forms.Select(attrs={**SELECT_ATTRS, **DEPARTMENT_FILTER_ATTRS}),
        help_text="Pick a department to narrow the recipient list below."
    )
    recipient = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('department', 'first_name', 'last_name'),
        required=False,
        widget=forms.Select(attrs=SELECT_ATTRS),
        help_text="Must be an existing, active account."
    )
    # Rendered as the searchableSelect Alpine component (chips + search
    # dropdown, see the template), not this field's default widget - it
    # posts one hidden input per selection under the same 'recipients'
    # name, which ModelMultipleChoiceField reads exactly like a native
    # <select multiple> would.
    recipients = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('department', 'first_name', 'last_name'),
        required=False,
        widget=forms.SelectMultiple,
        help_text="Search and select any number of existing, active accounts."
    )
    external_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'someone@example.com'
        }),
        help_text="No account needed - the link itself grants access."
    )
    # Rendered as one text input per address ("+ Add another email
    # address" dynamic rows, see the template), all posted under this same
    # name - clean() reads the full list via self.data.getlist() rather
    # than this field's own (single-value) cleaned_data entry, so this
    # declaration exists only so add_error('external_emails', ...) has a
    # field to attach to.
    external_emails = forms.CharField(required=False, widget=forms.HiddenInput)
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipient_department'].choices = [('', 'Select department...')] + list(User.DEPARTMENT_CHOICES)
        if not self.is_bound:
            self.fields['recipient'].queryset = self.fields['recipient'].queryset.none()

    def clean(self):
        cleaned = super().clean()

        # A caller that never posts share_type at all (e.g. code predating
        # the bulk-sharing UI) gets the exact old single-target XOR
        # validation, rather than the new field inferring a type and
        # silently ignoring whichever of recipient/external_email it
        # didn't pick.
        if 'share_type' not in self.data:
            recipient = cleaned.get('recipient')
            external_email = cleaned.get('external_email')
            if bool(recipient) == bool(external_email):
                raise forms.ValidationError('Choose an existing user OR enter an email address - not both, not neither.')
            if external_email and not cleaned.get('expires_at'):
                raise forms.ValidationError('External email shares must have an expiration date.')
            cleaned['targets'] = [{'recipient': recipient}] if recipient else [{'external_email': external_email}]
            return cleaned

        share_type = cleaned.get('share_type') or (
            'external' if (cleaned.get('external_email') or get_multi_values(self.data, 'external_emails')) else 'internal'
        )
        share_mode = cleaned.get('share_mode') or (
            'multiple' if (cleaned.get('recipients') or get_multi_values(self.data, 'external_emails')) else 'single'
        )
        targets = []

        if share_type == 'internal':
            if share_mode == 'multiple':
                recipients = cleaned.get('recipients')
                if not recipients:
                    self.add_error('recipients', 'Select at least one user.')
                else:
                    targets = [{'recipient': r} for r in recipients]
            else:
                recipient = cleaned.get('recipient')
                if not recipient:
                    self.add_error('recipient', 'Select a user.')
                else:
                    targets = [{'recipient': recipient}]
        elif share_type == 'external':
            if share_mode == 'multiple':
                emails = parse_email_list('\n'.join(get_multi_values(self.data, 'external_emails')), self, 'external_emails')
                if not emails and 'external_emails' not in self.errors:
                    self.add_error('external_emails', 'Enter at least one email address.')
                targets = [{'external_email': e} for e in emails]
            else:
                email = cleaned.get('external_email')
                if not email:
                    self.add_error('external_email', 'Enter an email address.')
                else:
                    targets = [{'external_email': email}]
            if not cleaned.get('expires_at'):
                self.add_error('expires_at', 'External email shares must have an expiration date.')

        cleaned['targets'] = targets
        return cleaned


class DocumentFolderForm(forms.ModelForm):
    class Meta:
        model = DocumentFolder
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'e.g. Q1 Compliance Documents'
            }),
            'description': forms.Textarea(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'rows': 3,
                'placeholder': 'Optional description'
            }),
        }


class ShareFolderForm(forms.Form):
    """Share an entire folder with one or more existing in-system users or
    one or more raw external email addresses with no account - mirrors
    ShareDocumentForm (including the share_type/share_mode -> `targets`
    resolution in clean()) minus can_edit, since folder sharing only ever
    grants view/download of its documents."""
    # Not required: a submit that omits them entirely (e.g. a pre-existing
    # integration, or the field simply not rendered) falls back to
    # inferring share_type/share_mode from which of the target fields
    # were actually filled in - see clean() below.
    share_type = forms.ChoiceField(
        choices=SHARE_TYPE_CHOICES, initial='internal', required=False, widget=forms.RadioSelect,
    )
    share_mode = forms.ChoiceField(
        choices=SHARE_MODE_CHOICES, initial='single', required=False, widget=forms.RadioSelect,
    )
    recipient_department = forms.ChoiceField(
        required=False,
        label='Department',
        widget=forms.Select(attrs={**SELECT_ATTRS, **DEPARTMENT_FILTER_ATTRS}),
        help_text="Pick a department to narrow the recipient list below."
    )
    recipient = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('department', 'first_name', 'last_name'),
        required=False,
        widget=forms.Select(attrs=SELECT_ATTRS),
        help_text="Must be an existing, active account."
    )
    # Rendered as the searchableSelect Alpine component (chips + search
    # dropdown, see the template), not this field's default widget - it
    # posts one hidden input per selection under the same 'recipients'
    # name, which ModelMultipleChoiceField reads exactly like a native
    # <select multiple> would.
    recipients = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('department', 'first_name', 'last_name'),
        required=False,
        widget=forms.SelectMultiple,
        help_text="Search and select any number of existing, active accounts."
    )
    external_email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'someone@example.com'
        }),
        help_text="No account needed - the link itself grants access."
    )
    # Rendered as one text input per address ("+ Add another email
    # address" dynamic rows, see the template), all posted under this same
    # name - clean() reads the full list via self.data.getlist() rather
    # than this field's own (single-value) cleaned_data entry, so this
    # declaration exists only so add_error('external_emails', ...) has a
    # field to attach to.
    external_emails = forms.CharField(required=False, widget=forms.HiddenInput)
    can_download = forms.BooleanField(required=False, label="Can download", widget=forms.CheckboxInput(attrs=CHECKBOX_ATTRS))
    expires_at = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        }),
        help_text="Optional for internal shares. Required for external email shares."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['recipient_department'].choices = [('', 'Select department...')] + list(User.DEPARTMENT_CHOICES)
        if not self.is_bound:
            self.fields['recipient'].queryset = self.fields['recipient'].queryset.none()

    def clean(self):
        cleaned = super().clean()

        # A caller that never posts share_type at all (e.g. code predating
        # the bulk-sharing UI) gets the exact old single-target XOR
        # validation, rather than the new field inferring a type and
        # silently ignoring whichever of recipient/external_email it
        # didn't pick.
        if 'share_type' not in self.data:
            recipient = cleaned.get('recipient')
            external_email = cleaned.get('external_email')
            if bool(recipient) == bool(external_email):
                raise forms.ValidationError('Choose an existing user OR enter an email address - not both, not neither.')
            if external_email and not cleaned.get('expires_at'):
                raise forms.ValidationError('External email shares must have an expiration date.')
            cleaned['targets'] = [{'recipient': recipient}] if recipient else [{'external_email': external_email}]
            return cleaned

        share_type = cleaned.get('share_type') or (
            'external' if (cleaned.get('external_email') or get_multi_values(self.data, 'external_emails')) else 'internal'
        )
        share_mode = cleaned.get('share_mode') or (
            'multiple' if (cleaned.get('recipients') or get_multi_values(self.data, 'external_emails')) else 'single'
        )
        targets = []

        if share_type == 'internal':
            if share_mode == 'multiple':
                recipients = cleaned.get('recipients')
                if not recipients:
                    self.add_error('recipients', 'Select at least one user.')
                else:
                    targets = [{'recipient': r} for r in recipients]
            else:
                recipient = cleaned.get('recipient')
                if not recipient:
                    self.add_error('recipient', 'Select a user.')
                else:
                    targets = [{'recipient': recipient}]
        elif share_type == 'external':
            if share_mode == 'multiple':
                emails = parse_email_list('\n'.join(get_multi_values(self.data, 'external_emails')), self, 'external_emails')
                if not emails and 'external_emails' not in self.errors:
                    self.add_error('external_emails', 'Enter at least one email address.')
                targets = [{'external_email': e} for e in emails]
            else:
                email = cleaned.get('external_email')
                if not email:
                    self.add_error('external_email', 'Enter an email address.')
                else:
                    targets = [{'external_email': email}]
            if not cleaned.get('expires_at'):
                self.add_error('expires_at', 'External email shares must have an expiration date.')

        cleaned['targets'] = targets
        return cleaned
