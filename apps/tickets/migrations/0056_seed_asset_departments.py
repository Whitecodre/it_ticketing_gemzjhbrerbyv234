from django.db import migrations

# Seed AssetDepartment from the existing User.DEPARTMENT_CHOICES list (so no
# asset that already had one of these department values loses it), plus the
# department names found in the client's real physical inventory list that
# don't exist in that list at all. tag_code is only filled in where the
# client's sheet gave us a real abbreviation to go on — blank ones are left
# for an admin to fill in later via System Settings (Asset Departments).
LEGACY_DEPARTMENTS = [
    # (User.DEPARTMENT_CHOICES code, tag_code)
    ('MARINE', ''),
    ('IT', 'IT'),
    ('ACCOUNTING', 'ACC'),
    ('LEGAL', ''),
    ('QHSE', 'HSE'),
    ('OPERATIONS', ''),
    ('PROJECT', 'PRJ'),
    ('VESSEL_CATERING', 'VCT'),
    ('PURCHASE_PROTOCOL', ''),
    ('FREIGHT', ''),
    ('STORE', ''),
    ('HR', ''),
    ('ADMIN', 'ADM'),
    ('COMMERCIAL', ''),
]

LEGACY_LABELS = {
    'MARINE': 'Marine', 'IT': 'IT', 'ACCOUNTING': 'Accounting', 'LEGAL': 'Legal',
    'QHSE': 'QHSE', 'OPERATIONS': 'Operations', 'PROJECT': 'Project',
    'VESSEL_CATERING': 'Vessel Catering', 'PURCHASE_PROTOCOL': 'Purchase/Protocol',
    'FREIGHT': 'Freight', 'STORE': 'Store', 'HR': 'HR', 'ADMIN': 'Admin',
    'COMMERCIAL': 'Commercial',
}

# Department names present in the client's real inventory list with no
# equivalent in User.DEPARTMENT_CHOICES — asset-only, no legacy mapping.
NEW_CLIENT_DEPARTMENTS = [
    ('PLD', 'PLD'),
    ('Management', 'MGT'),
    ('Fabrication', 'FAB'),
    ('Electrical', 'ELE'),
    ('Mechanic', 'MEC'),
    ('Dive Tech', 'DVT'),
    ('Logistics', 'LOG'),
    ('Base Store', 'BST'),
    ('Dive Store', 'DVS'),
]


def seed_departments(apps, schema_editor):
    AssetDepartment = apps.get_model('tickets', 'AssetDepartment')
    for code, tag_code in LEGACY_DEPARTMENTS:
        AssetDepartment.objects.get_or_create(
            name=LEGACY_LABELS[code],
            defaults={'tag_code': tag_code, 'legacy_user_department_code': code},
        )
    for name, tag_code in NEW_CLIENT_DEPARTMENTS:
        AssetDepartment.objects.get_or_create(
            name=name,
            defaults={'tag_code': tag_code, 'legacy_user_department_code': ''},
        )


def unseed_departments(apps, schema_editor):
    AssetDepartment = apps.get_model('tickets', 'AssetDepartment')
    names = [LEGACY_LABELS[c] for c, _ in LEGACY_DEPARTMENTS] + [n for n, _ in NEW_CLIENT_DEPARTMENTS]
    AssetDepartment.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0055_location_assetdepartment'),
    ]

    operations = [
        migrations.RunPython(seed_departments, unseed_departments),
    ]
