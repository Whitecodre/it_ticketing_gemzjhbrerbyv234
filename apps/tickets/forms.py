from django import forms
from .models import (
    Ticket, TicketComment, Asset, AssetCategory, ServiceCategory, Vessel, DiveSystem, JobNumber,
    Mobilization, AssetProcurementRequest, SLA, BusinessCalendar, EscalationRule,
    Location, AssetDepartment,
)
from apps.common.models import Category
from apps.maintenance.models import Vendor
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy

User = get_user_model()

# Shared HTMX wiring for the "pick a department, then narrow the user list"
# pattern (see accounts:department_users_partial). `hx-target` still needs
# to be set per-field to the actual target <select>'s id.
_DEPARTMENT_FILTER_ATTRS = {
    'hx-get': reverse_lazy('accounts:department_users_partial'),
    'hx-trigger': 'change',
    'hx-include': 'this',
    'hx-swap': 'innerHTML',
}

FIELD_CLASS = 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'


class VendorSelect(forms.Select):
    """Plain vendor <select> whose options carry a data-categories
    attribute (comma-separated AssetCategory pks) so the shared
    filterVendorSelectByCategory() JS (static/js/global.js) can narrow the
    list to whichever category a sibling field has selected. A vendor with
    no categories assigned stays visible under every category. Builds one
    pk->categories-csv map per render (from the field's queryset, expected
    to already have .prefetch_related('categories') applied) instead of
    querying per option."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._categories_by_vendor = None

    def _category_csv(self, vendor_pk):
        if self._categories_by_vendor is None:
            self._categories_by_vendor = {}
            queryset = getattr(self.choices, 'queryset', None)
            if queryset is not None:
                for vendor in queryset:
                    self._categories_by_vendor[str(vendor.pk)] = ','.join(
                        str(pk) for pk in vendor.categories.values_list('pk', flat=True)
                    )
        return self._categories_by_vendor.get(str(vendor_pk), '')

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        if value not in (None, ''):
            raw_value = value.value if hasattr(value, 'value') else value
            csv = self._category_csv(raw_value)
            if csv:
                option['attrs']['data-categories'] = csv
        return option


class TicketForm(forms.ModelForm):
    # Override category field to handle "OTHER"
    category = forms.CharField(
        required=True,
        widget=forms.Select(attrs={
            'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'hx-get': '',
            'hx-target': '#kb-suggestions',
            'hx-trigger': 'change',
        })
    )

    # Custom field for "Other" category
    category_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter custom category...',
            'id': 'category_other'
        }),
        label='Custom Category'
    )

    class Meta:
        model = Ticket
        fields = ['type', 'title', 'description', 'category', 'impact', 'urgency']
        widgets = {
            'type': forms.Select(attrs={
                'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'title': forms.TextInput(attrs={
                'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Brief summary of the issue'
            }),
            'description': forms.Textarea(attrs={
                'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'rows': 5,
                'placeholder': 'Describe your issue or request in detail'
            }),
            'impact': forms.Select(attrs={
                'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'urgency': forms.Select(attrs={
                'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Populate the select choices
        categories = Category.objects.all().values_list('id', 'name')
        self.fields['category'].widget.choices = [('', '-- Select Category --')] + list(categories) + [('OTHER', '+ Add Custom Category')]
        
        # If editing and category is custom (not in choices), set to OTHER and pre-fill category_other
        instance = kwargs.get('instance')
        if instance and instance.category_id:
            category_ids = [c[0] for c in categories]
            if instance.category_id not in category_ids:
                self.fields['category'].initial = 'OTHER'
                self.initial['category_other'] = instance.category.name

    def clean(self):
        cleaned_data = super().clean()
        
        # Handle "OTHER" for category
        category = cleaned_data.get('category')
        category_other = cleaned_data.get('category_other', '').strip()
        
        if category == 'OTHER':
            if category_other:
                # Try to find existing category or create new one
                category_obj, created = Category.objects.get_or_create(
                    name=category_other,
                    defaults={'slug': slugify(category_other)}
                )
                cleaned_data['category'] = category_obj
            else:
                self.add_error('category_other', 'Please enter a custom category.')
        elif category and category != '':
            try:
                # Ensure category is a Category object
                if isinstance(category, str):
                    category_obj = Category.objects.get(pk=category)
                    cleaned_data['category'] = category_obj
            except (Category.DoesNotExist, ValueError):
                self.add_error('category', 'Please select a valid category.')
        
        return cleaned_data


class IncidentReportForm(forms.ModelForm):
    """Reporter-facing incident report form (HDG-IT-FRM-086 Sections 1 & 3).

    Kept separate from TicketForm (used for Service Request) since the two
    ticket types now collect materially different fields — Incident no
    longer touches the shared `category`/`impact` fields Service Request
    still relies on.
    """
    incident_category_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': FIELD_CLASS,
            'placeholder': 'Describe the category...',
            'id': 'incident_category_other',
        }),
        label='Custom Incident Category',
    )
    how_discovered_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': FIELD_CLASS,
            'placeholder': 'Describe how it was discovered...',
            'id': 'how_discovered_other',
        }),
        label='Custom Discovery Method',
    )

    class Meta:
        model = Ticket
        fields = [
            'title', 'description', 'urgency', 'incident_datetime',
            'incident_category', 'business_impact', 'how_discovered',
            'location_hostname', 'immediate_actions',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': FIELD_CLASS,
                'placeholder': 'Short summary — e.g. VSAT connectivity dropping intermittently',
            }),
            'description': forms.Textarea(attrs={
                'class': FIELD_CLASS,
                'rows': 5,
                'placeholder': 'What you observed — error messages, timing, anything unusual.',
            }),
            'urgency': forms.Select(attrs={'class': FIELD_CLASS}),
            'incident_datetime': forms.DateTimeInput(attrs={
                'class': FIELD_CLASS,
                'type': 'datetime-local',
            }),
            'incident_category': forms.Select(attrs={
                'class': FIELD_CLASS,
                'onchange': "toggleOtherField('incident_category')",
            }),
            'business_impact': forms.Select(attrs={'class': FIELD_CLASS}),
            'how_discovered': forms.Select(attrs={
                'class': FIELD_CLASS,
                'onchange': "toggleOtherField('how_discovered')",
            }),
            'location_hostname': forms.TextInput(attrs={
                'class': FIELD_CLASS,
                'placeholder': 'e.g. Bridge, MV Adura or 10.4.2.11',
            }),
            'immediate_actions': forms.Textarea(attrs={
                'class': FIELD_CLASS,
                'rows': 3,
                'placeholder': 'Anything already tried before reporting this (optional)',
            }),
        }

    def clean(self):
        cleaned_data = super().clean()

        if cleaned_data.get('incident_category') == Ticket.IncidentCategory.OTHER and not cleaned_data.get('incident_category_other', '').strip():
            self.add_error('incident_category_other', 'Please describe the incident category.')

        if cleaned_data.get('how_discovered') == Ticket.DiscoveryMethod.OTHER and not cleaned_data.get('how_discovered_other', '').strip():
            self.add_error('how_discovered_other', 'Please describe how it was discovered.')

        return cleaned_data


class ServiceRequestForm(forms.ModelForm):
    """Reporter-facing Service Request form. Category-specific extra fields
    (service_request_details) aren't declared here — they're dynamic per
    ServiceCategory.field_group (see service_request_fields.py) and are
    validated/extracted separately in the view, since Django forms can't
    declare a field set that varies per-submission."""

    class Meta:
        model = Ticket
        fields = ['title', 'description', 'urgency', 'service_category', 'purpose', 'vessels', 'dive_systems']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': FIELD_CLASS,
                'placeholder': 'Short summary of the request',
            }),
            'description': forms.Textarea(attrs={
                'class': FIELD_CLASS,
                'rows': 5,
                'placeholder': 'Describe the request in detail',
            }),
            'urgency': forms.Select(attrs={'class': FIELD_CLASS}),
            'service_category': forms.Select(attrs={
                'class': FIELD_CLASS,
                'onchange': 'onServiceCategoryChange(this)',
            }),
            'purpose': forms.TextInput(attrs={
                'class': FIELD_CLASS,
                'placeholder': 'Why is this needed?',
            }),
            # Rendered by hand in the template as a checkbox list (matches the
            # "Additional Roles" checkbox pattern used in admin user
            # management) — nicer UX than a native multi-select box.
            'vessels': forms.CheckboxSelectMultiple(),
            'dive_systems': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service_category'].queryset = ServiceCategory.objects.filter(is_active=True)
        self.fields['service_category'].empty_label = '-- Select Service Category --'
        self.fields['vessels'].queryset = Vessel.objects.filter(is_active=True)
        self.fields['vessels'].required = False
        self.fields['dive_systems'].queryset = DiveSystem.objects.filter(is_active=True)
        self.fields['dive_systems'].required = False
        self.fields['purpose'].required = True


class MobilizationForm(forms.ModelForm):
    """Admin-facing form for sending a batch of assets out to a job/vessel/
    dive system. Asset selection itself is handled as raw POST data in the
    view (a dynamic, HTMX-searched multi-select), not as a form field."""

    # Not a model field — free-text vessel names proposed inline (a vessel
    # not yet in the admin-curated Vessel list). The view resolves each into
    # a real Vessel row (is_active=False, proposed_by=user, reused
    # case-insensitively if already proposed) and adds it to `vessels`,
    # mirroring JobNumber's existing propose-and-approve pattern. Several
    # rows can share this field name (same mechanism as the maintenance
    # app's custom checklist items), so read via getlist in clean().
    third_party_vessels = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Mobilization
        fields = ['job_number', 'vessels', 'dive_systems', 'expected_return_date', 'notes']
        widgets = {
            'job_number': forms.Select(attrs={'class': FIELD_CLASS}),
            'vessels': forms.CheckboxSelectMultiple(),
            'dive_systems': forms.CheckboxSelectMultiple(),
            'expected_return_date': forms.DateInput(attrs={'class': FIELD_CLASS, 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 3, 'placeholder': 'Optional notes...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['job_number'].queryset = JobNumber.objects.filter(is_active=True)
        self.fields['job_number'].required = False
        self.fields['job_number'].empty_label = '-- Select Job Number --'
        self.fields['vessels'].queryset = Vessel.objects.filter(is_active=True)
        self.fields['vessels'].required = False
        self.fields['dive_systems'].queryset = DiveSystem.objects.filter(is_active=True)
        self.fields['dive_systems'].required = False

    def clean_third_party_vessels(self):
        """Collect every posted third_party_vessels value (one per proposed
        vessel row) — same multi-value-under-one-name pattern used for the
        maintenance app's custom checklist items."""
        names = []
        if self.data:
            names = [v.strip() for v in self.data.getlist('third_party_vessels') if v.strip()]
        seen = set()
        deduped = []
        for name in names:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(name)
        return deduped

    def clean(self):
        cleaned_data = super().clean()
        if (
            not cleaned_data.get('job_number')
            and not cleaned_data.get('vessels')
            and not cleaned_data.get('dive_systems')
            and not cleaned_data.get('third_party_vessels')
        ):
            raise forms.ValidationError('Select at least a job number, vessel, dive system, or third-party vessel.')
        return cleaned_data


class MobilizationItemReturnForm(forms.Form):
    """Demobilize-one-asset form: condition + notes, POSTed against a MobilizationItem."""
    return_condition = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=True,
        widget=forms.Select(attrs={'class': FIELD_CLASS})
    )
    return_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 3, 'placeholder': 'Optional notes...'})
    )


class CommentForm(forms.ModelForm):
    class Meta:
        model = TicketComment
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={
                'rows': 3,
                'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm transition focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Add a comment or provide more information...'
            }),
        }

    def __init__(self, *args, **kwargs):
        # An attachment-only reply is valid — the views enforce "body or
        # attachments required", not "body always required".
        super().__init__(*args, **kwargs)
        self.fields['body'].required = False


class AssetForm(forms.ModelForm):
    """Streamlined Asset Form: identify the asset, where it is, who has it,
    and whether it's under warranty. Category is the single classification
    field (replaces the old, disconnected asset_type) and supports adding a
    new category inline, mirroring TicketForm's category "Other" pattern."""

    # Category - plain Select w/ "+ Add Custom Category" sentinel, resolved
    # (and created if new) in clean() below.
    category = forms.CharField(
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )
    category_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter new category name...',
            'id': 'category_other'
        }),
        label='New Category'
    )

    # Client-side filter only, not saved: narrows the `assigned_to` <select>
    # to one department at a time via HTMX (accounts:department_users_partial)
    # instead of listing every active user in the system at once.
    assignee_department = forms.ChoiceField(
        required=False,
        label='Assignee Department',
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'hx-target': '#id_assigned_to',
            **_DEPARTMENT_FILTER_ATTRS,
        })
    )

    # Location - plain Select w/ "+ Add New Location" sentinel, same
    # OTHER-sentinel pattern as category above, resolved in clean().
    location = forms.CharField(
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )
    location_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter new location name...',
            'id': 'location_other'
        }),
        label='New Location'
    )

    # Department (asset-only AssetDepartment, separate from
    # User.DEPARTMENT_CHOICES) - same OTHER-sentinel pattern.
    department = forms.CharField(
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )
    department_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter new department name...',
            'id': 'department_other'
        }),
        label='New Department'
    )

    # Status is a strict workflow enum - no "Other" escape hatch, since
    # checkout/mobilization/scrap logic all branch on exact status values.
    status = forms.ChoiceField(
        choices=Asset.Status.choices,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )

    condition = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )

    # The underlying model field isn't blank=True, so the default ModelForm
    # behavior marks this required - a plain POST that omits it (e.g. a
    # select that didn't get a value selected) failed validation instead of
    # falling back to the default. required=False here, fallback in clean().
    warranty_duration_years = forms.IntegerField(
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )

    # Same required=False + clean() fallback shape as warranty_duration_years
    # above — only relevant for consumable categories, hidden/unused for
    # individually-tracked assets, so the field must never block a save.
    quantity_in_stock = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'min': 0,
        })
    )

    # Optional reorder point for consumables — left blank disables low-stock
    # alerting for this asset (model field is nullable, not just "0 means
    # off", so an admin can leave it genuinely unset).
    low_stock_threshold = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'min': 0,
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        categories = AssetCategory.objects.all().order_by('name').values_list('id', 'name')
        self.fields['category'].widget.choices = [('', '-- Select Category --')] + list(categories) + [('OTHER', '+ Add Custom Category')]

        # If editing an asset whose category isn't in the active list for
        # some reason, pre-select OTHER and pre-fill the name (mirrors
        # TicketForm's same edit-mode round-trip for categories).
        instance = kwargs.get('instance')
        if instance and instance.category_id:
            category_ids = [c[0] for c in categories]
            if instance.category_id not in category_ids:
                self.fields['category'].initial = 'OTHER'
                self.initial['category_other'] = instance.category.name

        locations = Location.objects.filter(is_active=True).order_by('name').values_list('id', 'name')
        self.fields['location'].widget.choices = [('', '-- Select Location --')] + list(locations) + [('OTHER', '+ Add New Location')]
        if instance and instance.location_id:
            location_ids = [l[0] for l in locations]
            if instance.location_id not in location_ids:
                self.fields['location'].initial = 'OTHER'
                self.initial['location_other'] = instance.location.name

        departments = AssetDepartment.objects.filter(is_active=True).order_by('name').values_list('id', 'name')
        self.fields['department'].widget.choices = [('', '-- Select Department --')] + list(departments) + [('OTHER', '+ Add New Department')]
        if instance and instance.department_id:
            department_ids = [d[0] for d in departments]
            if instance.department_id not in department_ids:
                self.fields['department'].initial = 'OTHER'
                self.initial['department_other'] = instance.department.name

        if 'assignee_department' in self.fields:
            self.fields['assignee_department'].choices = [('', 'Select department...')] + list(User.DEPARTMENT_CHOICES)
            if instance and instance.assigned_to_id:
                self.initial['assignee_department'] = instance.assigned_to.department

        if 'assigned_to' in self.fields:
            # Validation always accepts any active user regardless of the
            # client's department-filter state (a stale/JS-disabled client
            # shouldn't be able to block a legitimate submission) — this
            # queryset is only narrowed for the *unbound* (GET) render below,
            # to match the HTMX-scoped <select> the department picker drives.
            self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
            if not self.is_bound:
                if instance and instance.assigned_to_id:
                    self.fields['assigned_to'].queryset = self.fields['assigned_to'].queryset.filter(department=instance.assigned_to.department)
                else:
                    self.fields['assigned_to'].queryset = self.fields['assigned_to'].queryset.none()
            # Editing an existing asset can't change who has it through this
            # general form anymore — that bypassed assign_to()/release()
            # entirely (no availability check, no AssetCheckoutHistory, no
            # status sync). disabled=True keeps it visible (who has it) but
            # a POSTed value is ignored in favor of the current instance's,
            # so it can't be changed even via a crafted request. Use
            # Reassign instead. Still editable at creation — there's no
            # prior holder to conflict with there.
            if instance and instance.pk:
                self.fields['assigned_to'].disabled = True
                self.fields['assigned_to'].help_text = 'Use Reassign to change who has this asset.'

        # An existing consumable's quantity_in_stock is no longer editable
        # through this general form — silently overwriting the count here
        # bypassed the audited Adjust Stock action (Asset.adjust_stock())
        # and left no reason/before-after trail. Still editable at
        # creation, where there's no prior count to conflict with.
        if instance and instance.pk and instance.is_consumable and 'quantity_in_stock' in self.fields:
            self.fields['quantity_in_stock'].disabled = True
            self.fields['quantity_in_stock'].help_text = 'Use "Adjust Stock" on the asset detail page to change this.'

        if 'renewal_vendor' in self.fields:
            self.fields['renewal_vendor'].queryset = Vendor.objects.filter(is_active=True).prefetch_related('categories')
            self.fields['renewal_vendor'].required = False
            self.fields['renewal_vendor'].empty_label = '-- Select Vendor --'

        self.fields['warranty_duration_years'].widget.choices = [
            (0, 'None'),
            (1, '1 Year'),
            (2, '2 Years'),
            (3, '3 Years'),
            (4, '4 Years'),
            (5, '5 Years'),
        ]

    def clean(self):
        cleaned_data = super().clean()

        # --- Handle "OTHER" for category: create/reuse a real AssetCategory ---
        category = cleaned_data.get('category')
        category_other = cleaned_data.get('category_other', '').strip()

        if category == 'OTHER':
            if category_other:
                category_obj, _ = AssetCategory.objects.get_or_create(name=category_other)
                cleaned_data['category'] = category_obj
            else:
                self.add_error('category_other', 'Please enter a new category name.')
        elif category:
            try:
                cleaned_data['category'] = AssetCategory.objects.get(pk=category)
            except (AssetCategory.DoesNotExist, ValueError):
                self.add_error('category', 'Please select a valid category.')
        else:
            cleaned_data['category'] = None

        # --- Handle "OTHER" for location: create/reuse a real Location ---
        location = cleaned_data.get('location')
        location_other = cleaned_data.get('location_other', '').strip()

        if location == 'OTHER':
            if location_other:
                location_obj, _ = Location.objects.get_or_create(name=location_other, parent=None)
                cleaned_data['location'] = location_obj
            else:
                self.add_error('location_other', 'Please enter a new location name.')
        elif location:
            try:
                cleaned_data['location'] = Location.objects.get(pk=location)
            except (Location.DoesNotExist, ValueError):
                self.add_error('location', 'Please select a valid location.')
        else:
            cleaned_data['location'] = None

        # --- Handle "OTHER" for department: create/reuse a real AssetDepartment ---
        department = cleaned_data.get('department')
        department_other = cleaned_data.get('department_other', '').strip()

        if department == 'OTHER':
            if department_other:
                department_obj, _ = AssetDepartment.objects.get_or_create(name=department_other)
                cleaned_data['department'] = department_obj
            else:
                self.add_error('department_other', 'Please enter a new department name.')
        elif department:
            try:
                cleaned_data['department'] = AssetDepartment.objects.get(pk=department)
            except (AssetDepartment.DoesNotExist, ValueError):
                self.add_error('department', 'Please select a valid department.')
        else:
            cleaned_data['department'] = None

        if not cleaned_data.get('status'):
            cleaned_data['status'] = Asset.Status.IN_STORE

        if cleaned_data.get('warranty_duration_years') in (None, ''):
            cleaned_data['warranty_duration_years'] = 0

        if cleaned_data.get('quantity_in_stock') in (None, ''):
            cleaned_data['quantity_in_stock'] = 1

        return cleaned_data

    class Meta:
        model = Asset
        fields = [
            # Basic
            'name', 'category', 'serial_number', 'model',
            'manufacturer', 'location', 'department', 'quantity_in_stock', 'low_stock_threshold',

            # Purchase & Warranty
            'purchase_date',
            'warranty_expiry', 'warranty_duration_years', 'warranty_provider', 'warranty_notes',

            # Renewal (software licenses, subscriptions) — only meaningful
            # when category.is_renewable, hidden/unused otherwise
            'next_renewal_date', 'renewal_interval_months', 'renewal_cost', 'renewal_currency',
            'renewal_vendor', 'renewal_reference', 'auto_renews',

            # Assignment
            'assigned_to',

            # Status & Condition
            'status', 'condition', 'condition_notes',

            # Notes
            'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'serial_number': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'model': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'manufacturer': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'purchase_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'next_renewal_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'renewal_interval_months': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            }),
            'renewal_cost': forms.NumberInput(attrs={
                'class': 'flex-1 min-w-0 rounded-r-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'min': 0, 'step': '0.01'
            }),
            'renewal_currency': forms.Select(attrs={
                'class': 'w-20 shrink-0 rounded-l-lg border border-r-0 py-2 px-2 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            }),
            'renewal_vendor': VendorSelect(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'renewal_reference': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'License/subscription/contract number'
            }),
            'warranty_expiry': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border py-2 px-3 text-sm bg-gray-100 text-gray-600 cursor-not-allowed focus:outline-none',
                'readonly': True
            }),
            'warranty_provider': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Warranty provider name'
            }),
            'warranty_notes': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Additional warranty notes...'
            }),
            'assigned_to': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'condition_notes': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Notes about asset condition...'
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'General notes about this asset...'
            }),
        }


class ProcurementRequestForm(forms.ModelForm):
    """Record that an item isn't in inventory and is being sourced from a
    vendor, against either a Service Request ticket or a Mobilization (the
    view sets whichever one applies). Vendor supports the same free-text
    propose-and-approve pattern as MobilizationForm.third_party_vessels —
    an unrecognized name becomes an inactive Vendor pending admin review."""

    new_vendor_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': "Vendor not listed? Type a new name..."})
    )

    class Meta:
        model = AssetProcurementRequest
        fields = ['item_name', 'category', 'quantity', 'vendor', 'external_reference', 'expected_arrival_date', 'notes']
        widgets = {
            'item_name': forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'e.g. Dell Latitude 5440 Laptop'}),
            'category': forms.Select(attrs={'class': FIELD_CLASS, 'onchange': "filterVendorSelectByCategory(this, document.getElementById('id_vendor'))"}),
            'quantity': forms.NumberInput(attrs={'class': FIELD_CLASS, 'min': 1}),
            'vendor': VendorSelect(attrs={'class': FIELD_CLASS}),
            'external_reference': forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'PMS reference number (optional)'}),
            'expected_arrival_date': forms.DateInput(attrs={'class': FIELD_CLASS, 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 2, 'placeholder': 'Optional notes...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vendor'].queryset = Vendor.objects.filter(is_active=True).prefetch_related('categories')
        self.fields['vendor'].required = False
        self.fields['vendor'].empty_label = '-- Select Vendor --'
        self.fields['category'].queryset = AssetCategory.objects.all().order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        new_vendor_name = cleaned_data.get('new_vendor_name', '').strip()
        if new_vendor_name and not cleaned_data.get('vendor'):
            vendor, created = Vendor.objects.get_or_create(
                name__iexact=new_vendor_name,
                defaults={'name': new_vendor_name, 'is_active': False}
            )
            cleaned_data['vendor'] = vendor
            cleaned_data['_new_vendor_proposed'] = created
        return cleaned_data


class _LenientMultipleChoiceField(forms.MultipleChoiceField):
    """Skips Django's built-in "not a valid choice" rejection — unrecognized
    values are silently dropped in the form's clean() instead of failing
    the whole submission, matching the resolve flow's original behavior
    (a stray/unrecognized root-cause-category checkbox shouldn't block
    resolving the ticket)."""

    def validate(self, value):
        if self.required and not value:
            raise forms.ValidationError(self.error_messages['required'], code='required')


class TicketResolveForm(forms.Form):
    """Agent/Team Lead resolve-confirmation form (partials/resolve_modal.html).
    Not a ModelForm — it drives a request-confirmation workflow rather than
    saving directly onto the Ticket, and root_cause/resolution_steps are
    only required for Incident tickets, so that's enforced in clean() using
    the ticket type passed in at construction rather than via field-level
    required=True."""

    resolution_root_cause = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 3, 'placeholder': 'What caused this incident?'}),
        label='Root Cause',
    )
    resolution_steps = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 4, 'placeholder': 'What did you do to fix it?'}),
        label='Resolution Steps',
    )
    resolution_root_cause_category = _LenientMultipleChoiceField(
        required=False,
        choices=Ticket.RootCauseCategory.choices,
        widget=forms.CheckboxSelectMultiple,
    )
    comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 3, 'placeholder': 'Add any notes about the resolution...'}),
        label='Optional comment',
    )

    def __init__(self, *args, is_incident=False, **kwargs):
        self.is_incident = is_incident
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.is_incident:
            if not cleaned_data.get('resolution_root_cause', '').strip():
                self.add_error('resolution_root_cause', 'Root Cause is required to resolve an Incident ticket.')
            if not cleaned_data.get('resolution_steps', '').strip():
                self.add_error('resolution_steps', 'Resolution Steps are required to resolve an Incident ticket.')

        valid_categories = dict(Ticket.RootCauseCategory.choices)
        categories = cleaned_data.get('resolution_root_cause_category') or []
        cleaned_data['resolution_root_cause_category'] = [c for c in categories if c in valid_categories]
        return cleaned_data


ASSET_MODAL_FIELD_CLASS = 'w-full rounded-lg border py-2.5 px-4 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'


class _UserWithRoleChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return user.get_full_name_with_role()


class AssetReassignForm(forms.Form):
    """partials/asset_reassign_modal.html. assigned_to left required=False —
    the view unassigns (clears assigned_to) when it's left blank, matching
    the existing asset_reassign view behavior."""

    assignee_department = forms.ChoiceField(
        required=False,
        label='Department',
        widget=forms.Select(attrs={
            'class': ASSET_MODAL_FIELD_CLASS,
            'hx-target': '#id_assigned_to',
            **_DEPARTMENT_FILTER_ATTRS,
        }),
    )
    assigned_to = _UserWithRoleChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('first_name', 'last_name'),
        required=False,
        widget=forms.Select(attrs={'class': ASSET_MODAL_FIELD_CLASS}),
        empty_label='Select a user...',
    )
    comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': ASSET_MODAL_FIELD_CLASS, 'rows': 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee_department'].choices = [('', 'Select department...')] + list(User.DEPARTMENT_CHOICES)
        # Narrow the visible user list to "nothing yet" on first (unbound)
        # render — the paired department <select> HTMX-fills it in. Keep
        # validation unfiltered on POST so a stale client can't block a
        # legitimate submission.
        if not self.is_bound:
            self.fields['assigned_to'].queryset = self.fields['assigned_to'].queryset.none()


class AssetScrapRequestForm(forms.Form):
    """partials/scrap_request_modal.html. The template has always marked
    the reason as required (HTML5 `required`), but the view never enforced
    it server-side — closing that gap here."""

    comment = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'class': ASSET_MODAL_FIELD_CLASS, 'rows': 3,
            'placeholder': 'Explain why this asset should be scrapped...',
        }),
        label='Reason for scrapping',
        error_messages={'required': 'Please explain why this asset should be scrapped.'},
    )


class _UserWithDepartmentChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        return f"{user.get_full_name() or user.email} ({user.get_department_display()})"


class AssetCheckoutForm(forms.Form):
    """partials/asset_checkout_modal.html."""

    assignee_department = forms.ChoiceField(
        required=False,
        label='Department',
        widget=forms.Select(attrs={
            'class': ASSET_MODAL_FIELD_CLASS,
            'hx-target': '#id_user_id',
            **_DEPARTMENT_FILTER_ATTRS,
        }),
    )
    user_id = _UserWithDepartmentChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('first_name', 'last_name'),
        required=True,
        widget=forms.Select(attrs={'class': ASSET_MODAL_FIELD_CLASS}),
        label='Check Out To',
        empty_label='Select a user...',
        error_messages={'required': 'Please select a user to check out this asset.'},
    )
    expected_return_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': ASSET_MODAL_FIELD_CLASS, 'type': 'date'}),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': ASSET_MODAL_FIELD_CLASS, 'rows': 2}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assignee_department'].choices = [('', 'Select department...')] + list(User.DEPARTMENT_CHOICES)
        if not self.is_bound:
            self.fields['user_id'].queryset = self.fields['user_id'].queryset.none()


class AssetCheckinForm(forms.Form):
    """partials/asset_checkin_modal.html."""

    return_reason = forms.ChoiceField(
        choices=Asset.ReturnReason.choices,
        required=True,
        widget=forms.Select(attrs={'class': ASSET_MODAL_FIELD_CLASS}),
        error_messages={'required': 'Please select a return reason.'},
    )
    return_condition = forms.ChoiceField(
        # Value IS the display label (not the enum key) — return_condition on
        # the model is a free-text field that has always stored "Good"/
        # "Fair"/etc. rather than the Condition enum's key, and other code
        # (checkin notes/logs, asset detail display) expects that casing.
        choices=[('', 'Select condition...')] + [(label, label) for _, label in Asset.Condition.choices],
        required=False,
        widget=forms.Select(attrs={'class': ASSET_MODAL_FIELD_CLASS}),
    )
    return_comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': ASSET_MODAL_FIELD_CLASS, 'rows': 2}),
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('return_reason') == Asset.ReturnReason.OTHER and not cleaned_data.get('return_comment', '').strip():
            self.add_error('return_comment', 'Please describe the return reason.')
        return cleaned_data


class AssetReturnRequestForm(forms.Form):
    """partials/asset_return_request_modal.html — the holder self-initiating
    a return from My Assets. No condition field: only the admin physically
    receiving the item can actually assess its condition, at confirm time."""

    return_reason = forms.ChoiceField(
        choices=Asset.ReturnReason.choices,
        required=True,
        widget=forms.Select(attrs={'class': ASSET_MODAL_FIELD_CLASS}),
        error_messages={'required': 'Please select a reason for returning this asset.'},
    )
    return_comment = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': ASSET_MODAL_FIELD_CLASS, 'rows': 2, 'placeholder': 'Any details for the admin arranging pickup...'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('return_reason') == Asset.ReturnReason.OTHER and not cleaned_data.get('return_comment', '').strip():
            self.add_error('return_comment', 'Please describe the return reason.')
        return cleaned_data


class ConnectorEditForm(forms.Form):
    """admin/connector_form.html. Every field here is genuinely optional
    (a connector can be disabled with no instructions on either side), so
    this exists for consistent cleaned_data access rather than closing any
    validation gap."""

    is_active = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-border text-primary focus:ring-primary'}),
    )
    instructions_for_requester = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 5,
            'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2 font-mono',
        }),
    )
    instructions_for_agent = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 5,
            'class': 'block w-full rounded-lg border py-2.5 px-4 text-sm bg-background border-border text-text-primary ring-primary focus:outline-none focus:ring-2 font-mono',
        }),
    )


class SLAForm(forms.Form):
    """admin/sla_management.html — Add SLA Policy modal."""

    priority = forms.ChoiceField(
        choices=Ticket.Priority.choices,
        widget=forms.Select(attrs={'class': FIELD_CLASS}),
        error_messages={'required': 'Please select a priority for the SLA policy.'},
    )
    # No max_value on the *_minutes fields — the original view did plain
    # hours*60+minutes arithmetic with no upper bound on minutes, so e.g.
    # "60 minutes" was accepted as equivalent to 1 hour rather than rejected.
    response_hours = forms.IntegerField(required=False, min_value=0, initial=0, widget=forms.NumberInput(attrs={'class': FIELD_CLASS, 'placeholder': 'Hrs'}))
    response_minutes = forms.IntegerField(required=False, min_value=0, initial=0, widget=forms.NumberInput(attrs={'class': FIELD_CLASS, 'placeholder': 'Mins'}))
    resolution_hours = forms.IntegerField(required=False, min_value=0, initial=0, widget=forms.NumberInput(attrs={'class': FIELD_CLASS, 'placeholder': 'Hrs'}))
    resolution_minutes = forms.IntegerField(required=False, min_value=0, initial=0, widget=forms.NumberInput(attrs={'class': FIELD_CLASS, 'placeholder': 'Mins'}))
    calendar_id = forms.ModelChoiceField(
        queryset=BusinessCalendar.objects.all(),
        required=False,
        empty_label='Default Calendar',
        widget=forms.Select(attrs={'class': FIELD_CLASS}),
    )

    def clean(self):
        cleaned_data = super().clean()
        # Mirrors the same hours*60+minutes totals and zero-fallback
        # defaults sla_create() uses when actually saving, so this compares
        # what will really be persisted rather than the raw sub-fields.
        response_total = (cleaned_data.get('response_hours') or 0) * 60 + (cleaned_data.get('response_minutes') or 0)
        resolution_total = (cleaned_data.get('resolution_hours') or 0) * 60 + (cleaned_data.get('resolution_minutes') or 0)
        response_total = response_total if response_total > 0 else 60
        resolution_total = resolution_total if resolution_total > 0 else 480
        if resolution_total < response_total:
            raise forms.ValidationError(
                'Resolution time must be greater than or equal to response time — '
                'a ticket can\'t be resolved before it\'s even been responded to.'
            )
        return cleaned_data


class BusinessCalendarForm(forms.Form):
    """admin/sla_management.html — Add Business Calendar modal."""

    WORKDAY_CHOICES = [(str(i), name) for i, name in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'])]

    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'Calendar name'}),
        error_messages={'required': 'Please enter a name for the business calendar.'},
    )
    workdays = forms.MultipleChoiceField(
        choices=WORKDAY_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    work_start = forms.TimeField(widget=forms.TimeInput(attrs={'class': FIELD_CLASS, 'type': 'time'}))
    work_end = forms.TimeField(widget=forms.TimeInput(attrs={'class': FIELD_CLASS, 'type': 'time'}))
    holidays = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'YYYY-MM-DD, YYYY-MM-DD'}),
    )

    def clean_holidays(self):
        raw = self.cleaned_data.get('holidays', '')
        return [h.strip() for h in raw.split(',') if h.strip()]


class EscalationRuleForm(forms.Form):
    """admin/sla_management.html — Add Escalation Rule modal."""

    NOTIFY_ROLE_CHOICES = [('', '— Select Role —'), ('TEAM_LEAD', 'Team Lead'), ('ADMIN', 'Admin')]
    REASSIGN_ROLE_CHOICES = [('', '— Select Role —'), ('TEAM_LEAD', 'Team Lead'), ('ADMIN', 'Admin'), ('AGENT', 'Agent')]

    priority = forms.ChoiceField(choices=Ticket.Priority.choices, widget=forms.Select(attrs={'class': FIELD_CLASS}))
    timer_type = forms.ChoiceField(choices=EscalationRule.TIMER_CHOICES, widget=forms.Select(attrs={'class': FIELD_CLASS}))
    threshold_percent = forms.IntegerField(min_value=1, max_value=100, widget=forms.NumberInput(attrs={'class': FIELD_CLASS, 'placeholder': '75'}))
    action_type = forms.ChoiceField(choices=EscalationRule.ACTION_CHOICES, widget=forms.Select(attrs={'class': FIELD_CLASS, 'onchange': 'toggleTargetDropdown()', 'id': 'actionTypeSelect'}))
    notify_role = forms.ChoiceField(choices=NOTIFY_ROLE_CHOICES, required=False, widget=forms.Select(attrs={'class': FIELD_CLASS}))
    reassign_to_role = forms.ChoiceField(choices=REASSIGN_ROLE_CHOICES, required=False, widget=forms.Select(attrs={'class': FIELD_CLASS}))

    def clean(self):
        cleaned_data = super().clean()
        # Only the field matching the selected action is meaningful — the
        # other stays cleared, mirroring the view's original behavior.
        if cleaned_data.get('action_type') != 'notify':
            cleaned_data['notify_role'] = ''
        if cleaned_data.get('action_type') != 'reassign':
            cleaned_data['reassign_to_role'] = ''
        return cleaned_data


ESCALATED_FIELD_CLASS = 'w-full rounded-lg border py-2.5 px-4 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'


class EscalatedReassignForm(forms.Form):
    """team_lead/escalated_tickets.html — Reassign modal. agent_id's
    queryset is department-scoped, so it's built by the view and passed in
    at construction rather than declared statically here."""

    agent_id = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=True,
        widget=forms.Select(attrs={'class': ESCALATED_FIELD_CLASS, 'id': 'reassignAgent'}),
        label='Assign to Agent',
        empty_label='Select an agent',
        error_messages={'required': 'Please select an agent to reassign this ticket to.'},
    )
    comment = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'class': ESCALATED_FIELD_CLASS, 'rows': 3, 'id': 'reassignComment', 'placeholder': 'Explain the reason for reassigning…'}),
        error_messages={'required': 'Please explain the reason for reassigning.'},
    )

    def __init__(self, *args, agents=None, **kwargs):
        super().__init__(*args, **kwargs)
        if agents is not None:
            self.fields['agent_id'].queryset = agents


class EscalatedReturnForm(forms.Form):
    """team_lead/escalated_tickets.html — Return to Pool modal."""

    comment = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'class': ESCALATED_FIELD_CLASS, 'rows': 3, 'id': 'returnComment', 'placeholder': 'Explain why this ticket is being returned to the pool…'}),
        error_messages={'required': 'Please explain why this ticket is being returned to the pool.'},
    )