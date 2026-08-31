import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds new FK columns side-by-side with the existing free-text
    `location`/`department` CharFields, so the data migration in 0058 can
    read the old values while writing the new ones — the old columns are
    only removed in 0059, after every row has been backfilled."""

    dependencies = [
        ('tickets', '0056_seed_asset_departments'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='location_new',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='assets_new_location', to='tickets.location'),
        ),
        migrations.AddField(
            model_name='asset',
            name='department_new',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='assets_new_department', to='tickets.assetdepartment'),
        ),
    ]
