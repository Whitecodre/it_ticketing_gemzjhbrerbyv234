# apps/tickets/settings_registry.py
"""
Small declarative registry driving the generic CRUD tabs on the System
Settings page. Adding a new editable list later is one more SettingsResource
entry here, not a new hand-written form/view — same shape as report_registry.py.
"""
from dataclasses import dataclass, field

from .models import ServiceCategory, Vessel, AssetCategory, DiveSystem, JobNumber, Location, AssetDepartment
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
    # True for resources where a non-admin can propose a new row inline on
    # some other form (a new vessel/job number/vendor typed on a
    # mobilization/service-request/procurement form) — created is_active=
    # False + proposed_by=<that user>. Drives the pending-approval banner
    # on this resource's System Settings page.
    has_proposals: bool = False
    # Which card-grid section this resource's icon button lands in on the
    # System Settings hub — see SETTINGS_GROUP_ORDER below for the section
    # display order. Purely a hub-layout grouping, unrelated to has_proposals.
    group: str = 'Tickets & Service'

    def __post_init__(self):
        if not self.singular_label:
            self.singular_label = self.label


# Display order for the hub's section headings — anything with a group not
# listed here would simply be appended at the end.
SETTINGS_GROUP_ORDER = ['Tickets & Service', 'Assets & Fleet']

SETTINGS_RESOURCES = {
    'service-categories': SettingsResource(
        slug='service-categories',
        label='Service Categories',
        singular_label='Service Category',
        icon='clipboard-list',
        group='Tickets & Service',
        model=ServiceCategory,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('description', 'Description', 'textarea'),
            SettingsField('field_group', 'Field Group', 'select', choices=ServiceCategory.FieldGroup.choices),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('field_group', 'Field Group'), ('is_active', 'Active')],
    ),
    'vessels': SettingsResource(
        slug='vessels',
        label='Vessels',
        singular_label='Vessel',
        icon='anchor',
        group='Assets & Fleet',
        model=Vessel,
        has_proposals=True,
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
        group='Assets & Fleet',
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
        group='Assets & Fleet',
        model=JobNumber,
        has_proposals=True,
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
        group='Assets & Fleet',
        model=AssetCategory,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('description', 'Description', 'textarea'),
            SettingsField('is_consumable', 'Bulk/Consumable Stock (quantity-tracked, not individually)', 'checkbox'),
            SettingsField('is_renewable', 'Renewable (tracks recurring renewal dates & cost)', 'checkbox'),
            SettingsField('tag_code', 'Tag Code (e.g. MNT, CPU, LP — used in auto-generated asset tags)'),
        ],
        list_columns=[('name', 'Name'), ('is_consumable', 'Consumable'), ('is_renewable', 'Renewable'), ('tag_code', 'Tag Code')],
    ),
    'locations': SettingsResource(
        slug='locations',
        label='Locations',
        singular_label='Location',
        icon='map-pin',
        group='Assets & Fleet',
        model=Location,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('parent', 'Parent Location (leave blank for a top-level Building)', 'select'),
            SettingsField('tag_code', 'Tag Code (e.g. GF, 1F, AN — used in auto-generated asset tags)'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('parent', 'Parent'), ('tag_code', 'Tag Code'), ('is_active', 'Active')],
    ),
    'asset-departments': SettingsResource(
        slug='asset-departments',
        label='Asset Departments',
        singular_label='Asset Department',
        icon='building',
        group='Assets & Fleet',
        model=AssetDepartment,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('tag_code', 'Tag Code (e.g. ACC, IT, PLD — used in auto-generated asset tags)'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('name', 'Name'), ('tag_code', 'Tag Code'), ('is_active', 'Active')],
    ),
    'categories': SettingsResource(
        slug='categories',
        label='Categories (Incident Tickets, KB Articles)',
        singular_label='Category',
        icon='folder',
        group='Tickets & Service',
        model=Category,
        fields=[
            SettingsField('name', 'Name'),
            SettingsField('description', 'Description', 'textarea'),
            SettingsField('parent', 'Parent Category (leave blank for a top-level section)', 'select'),
        ],
        list_columns=[('name', 'Name'), ('parent', 'Parent'), ('description', 'Description')],
    ),
    'maintenance-checklist-items': SettingsResource(
        slug='maintenance-checklist-items',
        label='Maintenance Checklist Items',
        singular_label='Checklist Item',
        icon='list-checks',
        group='Tickets & Service',
        model=MaintenanceChecklistTemplate,
        fields=[
            SettingsField('department', 'Department', 'select', choices=MaintenanceChecklistTemplate.Department.choices),
            SettingsField('text', 'Item Text'),
            SettingsField('is_active', 'Active', 'checkbox'),
        ],
        list_columns=[('text', 'Item'), ('department', 'Department'), ('is_active', 'Active')],
    ),
    'vendors': SettingsResource(
        slug='vendors',
        label='Vendors',
        singular_label='Vendor',
        icon='truck',
        group='Assets & Fleet',
        model=Vendor,
        has_proposals=True,
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
