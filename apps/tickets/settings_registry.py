# apps/tickets/settings_registry.py
"""
Small declarative registry driving the generic CRUD tabs on the System
Settings page. Adding a new editable list later is one more SettingsResource
entry here, not a new hand-written form/view — same shape as report_registry.py.
"""
from dataclasses import dataclass, field

from .models import ServiceCategory, Vessel, AssetCategory, DiveSystem, JobNumber
from apps.common.models import Category
from apps.maintenance.models import MaintenanceChecklistTemplate, Vendor


@dataclass
class SettingsField:
    name: str
    label: str
    kind: str = 'text'  # 'text' | 'textarea' | 'checkbox' | 'number' | 'select'
    choices: list = field(default_factory=list)


@dataclass
class SettingsResource:
    slug: str
    label: str
    icon: str
    model: type
    fields: list
    list_columns: list  # (attr_name, column_label) shown in the table
    # Explicit rather than derived from `label` (e.g. via slice(':-1')) —
    # English pluralization is irregular ("Categories" -> "Category", not
    # "Categorie"), so guessing breaks for every "-ies" label.
    singular_label: str = ''

    def __post_init__(self):
        if not self.singular_label:
            self.singular_label = self.label


SETTINGS_RESOURCES = {
    'service-categories': SettingsResource(
        slug='service-categories',
        label='Service Categories',
        singular_label='Service Category',
        icon='clipboard-list',
        model=ServiceCategory,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('description', 'Description', 'textarea'),
            SettingsField('field_group', 'Field Group', 'select', choices=ServiceCategory.FieldGroup.choices),
            SettingsField('icon', 'Icon (lucide name)'),
            SettingsField('order', 'Order', 'number'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('field_group', 'Field Group'), ('order', 'Order'), ('is_active', 'Active')],
    ),
    'vessels': SettingsResource(
        slug='vessels',
        label='Vessels',
        singular_label='Vessel',
        icon='anchor',
        model=Vessel,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('imo_number', 'IMO Number'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('imo_number', 'IMO Number'), ('proposed_by', 'Proposed By'), ('is_active', 'Active')],
    ),
    'dive-systems': SettingsResource(
        slug='dive-systems',
        label='Dive Systems',
        singular_label='Dive System',
        icon='waves',
        model=DiveSystem,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('is_active', 'Active')],
    ),
    'job-numbers': SettingsResource(
        slug='job-numbers',
        label='Job Numbers',
        singular_label='Job Number',
        icon='briefcase',
        model=JobNumber,
        fields=[
            SettingsField('number', 'Job Number'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('number', 'Job Number'), ('proposed_by', 'Proposed By'), ('is_active', 'Active')],
    ),
    'asset-categories': SettingsResource(
        slug='asset-categories',
        label='Asset Categories',
        singular_label='Asset Category',
        icon='hard-drive',
        model=AssetCategory,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('description', 'Description', 'textarea'),
            SettingsField('icon', 'Icon (lucide name)'),
            SettingsField('color', 'Color (hex)'),
            SettingsField('is_consumable', 'Bulk/Consumable Stock (quantity-tracked, not individually)', 'checkbox'),
            SettingsField('is_renewable', 'Renewable (tracks recurring renewal dates & cost)', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('color', 'Color'), ('is_consumable', 'Consumable'), ('is_renewable', 'Renewable')],
    ),
    'categories': SettingsResource(
        slug='categories',
        label='Categories (Incident Tickets, KB Articles)',
        singular_label='Category',
        icon='folder',
        model=Category,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('description', 'Description', 'textarea'),
            SettingsField('icon', 'Icon (lucide name)'),
            SettingsField('parent', 'Parent Category (leave blank for a top-level section)', 'select'),
        ],
        list_columns=[('name', 'Name'), ('parent', 'Parent'), ('description', 'Description')],
    ),
    'maintenance-checklist-items': SettingsResource(
        slug='maintenance-checklist-items',
        label='Maintenance Checklist Items',
        singular_label='Checklist Item',
        icon='list-checks',
        model=MaintenanceChecklistTemplate,
        fields=[
            SettingsField('department', 'Department', 'select', choices=MaintenanceChecklistTemplate.Department.choices),
            SettingsField('text', 'Item Text'),
            SettingsField('order', 'Order', 'number'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('text', 'Item'), ('department', 'Department'), ('order', 'Order'), ('is_active', 'Active')],
    ),
    'vendors': SettingsResource(
        slug='vendors',
        label='Vendors',
        singular_label='Vendor',
        icon='truck',
        model=Vendor,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('contact_person', 'Contact Person'),
            SettingsField('phone', 'Phone'),
            SettingsField('email', 'Email'),
            # Callable, not a static list — resolved lazily wherever it's
            # consumed (same pattern as report_registry.FilterField.choices)
            # so newly-added AssetCategories show up without a restart.
            SettingsField('categories', 'Asset Categories Supplied', 'multiselect',
                           choices=lambda: [(c.pk, c.full_name) for c in AssetCategory.objects.order_by('name')]),
            SettingsField('notes', 'Notes', 'textarea'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('categories_display', 'Categories'), ('contact_person', 'Contact Person'), ('phone', 'Phone'), ('is_active', 'Active')],
    ),
}
