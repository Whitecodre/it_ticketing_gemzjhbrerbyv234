# apps/tickets/service_request_fields.py
"""
Declarative registry mapping each ServiceCategory.field_group to the extra
fields the Service Request form shows for it, and the logic to validate +
extract those fields from a POST into Ticket.service_request_details.
Adding a new field to a group (or a new group) is a small addition here —
no new model fields/migrations needed, since these live in the JSONField.
"""
from dataclasses import dataclass, field

@dataclass
class DynamicField:
    key: str
    label: str
    kind: str = 'text'  # 'text' | 'textarea' | 'number' | 'date' | 'select'
    required: bool = False
    placeholder: str = ''
    choices: list = field(default_factory=list)  # for kind='select'
    has_other: bool = False  # reveals a "<key>_other" text field when the OTHER option is picked


DYNAMIC_FIELDS_BY_GROUP = {
    'ASSET': [
        DynamicField('number_of_assets', 'Number of Assets', 'number', required=True),
        DynamicField('asset_type', 'Asset Type', 'select', required=True, choices=[
            ('COMPUTER', 'Computer'), ('LAPTOP', 'Laptop'), ('SERVER', 'Server'),
            ('NETWORK', 'Network Device'), ('PRINTER', 'Printer'), ('SOFTWARE', 'Software License'),
            ('OTHER', 'Other'),
        ], has_other=True),
    ],
    'JOB': [
        # 'job_number' intentionally not here — Job Number is now a global,
        # admin-curated field on every service request (see Ticket.job_number),
        # not a category-specific free-text field.
        DynamicField('job_description', 'Job Description', 'textarea', required=True),
    ],
    'VESSEL': [
        DynamicField('port_location', 'Port / Location', 'text', placeholder='e.g. Lagos Anchorage'),
    ],
    'PROCUREMENT': [
        DynamicField('budget_code', 'Budget / Cost Code', 'text'),
        DynamicField('quantity', 'Quantity', 'number'),
        DynamicField('preferred_vendor', 'Preferred Vendor', 'text'),
        DynamicField('estimated_cost', 'Estimated Cost', 'text'),
    ],
    'HR': [
        DynamicField('employee_affected', 'Employee Affected', 'text', placeholder="Leave blank if it's you"),
        DynamicField('effective_date', 'Effective Date', 'date'),
    ],
    'LOGISTICS': [
        DynamicField('shipment_reference', 'Shipment / Cargo Reference', 'text'),
        DynamicField('origin_destination', 'Origin → Destination', 'text', placeholder='e.g. Lagos → Port Harcourt'),
    ],
    'GENERAL': [],
}


def fields_for_group(field_group):
    return DYNAMIC_FIELDS_BY_GROUP.get(field_group, [])


def build_service_request_details(field_group, post_data):
    """Validates + extracts the POSTed dynamic fields for a field group.
    Returns (details_dict, errors_dict) — errors_dict maps field key -> message.
    For a has_other select field with value 'OTHER', the free-text "<key>_other"
    value is stored in place of the literal 'OTHER' so downstream display never
    has to know about the Other convention."""
    details = {}
    errors = {}
    for f in fields_for_group(field_group):
        value = (post_data.get(f.key) or '').strip()
        if f.required and not value:
            errors[f.key] = f'{f.label} is required.'
            continue
        if not value:
            continue
        if f.has_other and value == 'OTHER':
            other_value = (post_data.get(f.key + '_other') or '').strip()
            if not other_value:
                errors[f.key + '_other'] = f'Please describe the {f.label.lower()}.'
                continue
            details[f.key] = other_value
        else:
            details[f.key] = value
    return details, errors


def display_value_for_field(f, raw_value):
    """Maps a stored value through the field's choices for nicer display
    (e.g. 'LAPTOP' -> 'Laptop'); falls back to the raw value for free text
    or an Other-supplied value that was already stored as free text."""
    if f.kind == 'select' and f.choices:
        return dict(f.choices).get(raw_value, raw_value)
    return raw_value
