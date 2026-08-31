from django.db import migrations
from django.utils.text import slugify


def backfill(apps, schema_editor):
    Asset = apps.get_model('tickets', 'Asset')
    Location = apps.get_model('tickets', 'Location')
    AssetDepartment = apps.get_model('tickets', 'AssetDepartment')

    department_by_code = {d.legacy_user_department_code: d for d in AssetDepartment.objects.exclude(legacy_user_department_code='')}
    location_cache = {}

    for asset in Asset.objects.all().iterator():
        changed_fields = []

        if asset.location:
            name = asset.location.strip()
            if name:
                location = location_cache.get(name)
                if location is None:
                    location, _ = Location.objects.get_or_create(
                        name=name, parent=None,
                        defaults={'slug': slugify(name) or f'location-{Location.objects.count() + 1}'},
                    )
                    location_cache[name] = location
                asset.location_new_id = location.id
                changed_fields.append('location_new')

        if asset.department:
            department = department_by_code.get(asset.department)
            if department:
                asset.department_new_id = department.id
                changed_fields.append('department_new')

        if changed_fields:
            asset.save(update_fields=changed_fields)


def noop_reverse(apps, schema_editor):
    # location_new/department_new are dropped in 0059 anyway; nothing to
    # unwind here beyond that.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0057_asset_location_new_department_new'),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
