from django.db import migrations
from django.utils.text import slugify

OLD_CATEGORY_NAMES = [
    "Vessel / Marine Operations",
    "Asset / Equipment",
    "Job / Work Order",
    "Procurement / Purchase",
    "HR / Personnel",
    "Logistics / Freight",
    "General",
]

NEW_CATEGORIES = [
    # (name, field_group, icon, description)
    ("Hardware Support", "ASSET", "laptop", "Issues with laptops, desktops, monitors, printers, or other physical IT equipment"),
    ("Equipment Request", "ASSET", "package-plus", "Request new IT equipment (laptop, phone, peripherals)"),
    ("Software & Licensing", "GENERAL", "app-window", "Software installation, updates, or licensing requests"),
    ("Network & Connectivity", "GENERAL", "wifi", "Internet, VPN, or network connectivity issues"),
    ("Account & Access", "GENERAL", "key", "New accounts, password resets, or permission/access changes"),
    ("Email & Communication", "GENERAL", "mail", "Email, Teams, or other communication tool support"),
    ("IT Consultation", "GENERAL", "message-circle-question", "General IT advice or consultation"),
    ("Other IT Support", "GENERAL", "circle-help", "Anything else IT-related not covered above"),
]


def deactivate_old_and_create_new(apps, schema_editor):
    ServiceCategory = apps.get_model('tickets', 'ServiceCategory')

    # Deactivate rather than delete — preserves the category label on any
    # existing historical tickets that reference these rows.
    ServiceCategory.objects.filter(name__in=OLD_CATEGORY_NAMES).update(is_active=False)

    for order, (name, field_group, icon, description) in enumerate(NEW_CATEGORIES):
        ServiceCategory.objects.get_or_create(
            name=name,
            defaults={
                'slug': slugify(name),
                'field_group': field_group,
                'icon': icon,
                'description': description,
                'order': order,
                'is_active': True,
            },
        )


def reactivate_old_and_deactivate_new(apps, schema_editor):
    ServiceCategory = apps.get_model('tickets', 'ServiceCategory')
    new_names = [name for name, *_ in NEW_CATEGORIES]
    ServiceCategory.objects.filter(name__in=OLD_CATEGORY_NAMES).update(is_active=True)
    ServiceCategory.objects.filter(name__in=new_names).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0029_jobnumber_divespread'),
    ]

    operations = [
        migrations.RunPython(deactivate_old_and_create_new, reactivate_old_and_deactivate_new),
    ]
