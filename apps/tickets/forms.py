from django import forms
from .models import Ticket, TicketComment, Asset, AssetCategory
from apps.common.models import Category
from django.utils.text import slugify
from django.contrib.auth import get_user_model

User = get_user_model()

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


# apps/tickets/forms.py - Replace the AssetForm with this updated version

class AssetForm(forms.ModelForm):
    """Enhanced Asset Form with all new fields."""
    
    # ================================================================
    # EXPLICIT FIELD DECLARATIONS (to control widgets and choices)
    # ================================================================
    
    # Category - explicit ModelChoiceField
    category = forms.ModelChoiceField(
        queryset=AssetCategory.objects.all().order_by('name'),
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        }),
        empty_label="-- Select Category --"
    )
    
    asset_type = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )
    
    location = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )
    
    status = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )
    
    condition = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )

    # These three carry sensible model defaults (3 years / 0 years / 6
    # months) but the underlying model fields aren't blank=True, so the
    # default ModelForm behavior marked them required — a plain POST that
    # omits any of them (e.g. a select that didn't get a value selected)
    # failed validation instead of falling back to the default. required=False
    # here, with the fallback applied in clean() below.
    depreciation_years = forms.IntegerField(
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )

    warranty_duration_years = forms.IntegerField(
        required=False,
        widget=forms.Select(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )

    maintenance_interval_months = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
        })
    )

    # "Other" fields
    location_other = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter custom location...',
            'id': 'location_other'
        }),
        label='Custom Location'
    )
    
    asset_type_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter custom asset type...',
            'id': 'asset_type_other'
        }),
        label='Custom Asset Type'
    )
    
    status_other = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
            'placeholder': 'Enter custom status...',
            'id': 'status_other'
        }),
        label='Custom Status'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Populate select choices
        self.fields['asset_type'].widget.choices = [('', '-- Select Type --')] + list(Asset.AssetType.choices)
        self.fields['location'].widget.choices = [('', '-- Select Location --')] + list(Asset.Location.choices)
        self.fields['status'].widget.choices = [('', '-- Select Status --')] + list(Asset.Status.choices)
        self.fields['condition'].widget.choices = [('', '-- Select Condition --')] + list(Asset.Condition.choices)
        
        # Category queryset is already set above, but we can add additional filtering if needed
        # The category field is already defined as a ModelChoiceField with the queryset set
        
        # Filter assigned_to to active users only
        if 'assigned_to' in self.fields:
            self.fields['assigned_to'].queryset = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
        
        # Set depreciation years choices
        if 'depreciation_years' in self.fields:
            self.fields['depreciation_years'].widget.choices = [
                ('', '-- Select --'),
                (1, '1 Year'),
                (2, '2 Years'),
                (3, '3 Years'),
                (4, '4 Years'),
                (5, '5 Years'),
            ]
        
        # Set warranty duration choices
        if 'warranty_duration_years' in self.fields:
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
        
        # --- Handle "OTHER" for asset_type ---
        asset_type = cleaned_data.get('asset_type')
        asset_type_other = cleaned_data.get('asset_type_other', '').strip()
        
        if asset_type == 'OTHER':
            if asset_type_other:
                cleaned_data['asset_type'] = asset_type_other
            else:
                self.add_error('asset_type_other', 'Please enter a custom asset type.')
        elif not asset_type:
            cleaned_data['asset_type'] = ''
        
        # --- Handle "OTHER" for location ---
        location = cleaned_data.get('location')
        location_other = cleaned_data.get('location_other', '').strip()
        
        if location == 'OTHER':
            if location_other:
                cleaned_data['location'] = location_other
            else:
                self.add_error('location_other', 'Please enter a custom location.')
        elif not location:
            cleaned_data['location'] = ''
        
        # --- Handle "OTHER" for status ---
        status = cleaned_data.get('status')
        status_other = cleaned_data.get('status_other', '').strip()
        
        if status == 'OTHER':
            if status_other:
                cleaned_data['status'] = status_other
            else:
                self.add_error('status_other', 'Please enter a custom status.')
        elif not status:
            cleaned_data['status'] = Asset.Status.IN_STORE

        # Fall back to the model defaults when these were left blank.
        if cleaned_data.get('depreciation_years') in (None, ''):
            cleaned_data['depreciation_years'] = 3
        if cleaned_data.get('warranty_duration_years') in (None, ''):
            cleaned_data['warranty_duration_years'] = 0
        if cleaned_data.get('maintenance_interval_months') in (None, ''):
            cleaned_data['maintenance_interval_months'] = 6

        return cleaned_data

    class Meta:
        model = Asset
        fields = [
            # Basic
            'name', 'category', 'asset_type', 'serial_number', 'model', 
            'manufacturer', 'location',
            
            # Financial
            'purchase_date', 'purchase_price', 'depreciation_years', 'salvage_value',
            
            # Warranty
            'warranty_expiry', 'warranty_duration_years', 'warranty_provider', 'warranty_notes',
            
            # Assignment
            'assigned_to', 'assigned_to_department',
            
            # Status & Condition
            'status', 'condition', 'condition_notes',
            
            # Maintenance
            'last_maintenance', 'next_maintenance', 'maintenance_interval_months', 'maintenance_notes',
            
            # Supplier
            'supplier', 'invoice_number', 'po_number', 'purchase_order',
            
            # Notes
            'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'category': forms.Select(attrs={
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
            'purchase_price': forms.NumberInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'step': '0.01',
                'placeholder': '0.00'
            }),
            'depreciation_years': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'salvage_value': forms.NumberInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'step': '0.01',
                'placeholder': '0.00'
            }),
            'warranty_expiry': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border py-2 px-3 text-sm bg-gray-100 text-gray-600 cursor-not-allowed focus:outline-none',
                'readonly': True
            }),
            'warranty_duration_years': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
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
            'assigned_to_department': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Department name'
            }),
            'status': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'condition': forms.Select(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'condition_notes': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Notes about asset condition...'
            }),
            'last_maintenance': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'next_maintenance': forms.DateInput(attrs={
                'type': 'date',
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary'
            }),
            'maintenance_interval_months': forms.NumberInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'min': 1,
                'max': 60
            }),
            'maintenance_notes': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Maintenance notes...'
            }),
            'supplier': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Supplier/Vendor name'
            }),
            'invoice_number': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Invoice number'
            }),
            'po_number': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'PO number'
            }),
            'purchase_order': forms.TextInput(attrs={
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'Purchase Order number'
            }),
            'notes': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full rounded-lg border py-2 px-3 text-sm focus:outline-none focus:ring-2 bg-background border-border text-text-primary ring-primary',
                'placeholder': 'General notes about this asset...'
            }),
        }