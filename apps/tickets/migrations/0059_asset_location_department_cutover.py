import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Cutover: drop the old free-text `location`/`department` columns
    (fully backfilled into location_new/department_new by 0058) and rename
    the new FK columns into their place, matching the final Asset model."""

    dependencies = [
        ('tickets', '0058_backfill_asset_location_department'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='asset',
            name='location',
        ),
        migrations.RemoveField(
            model_name='asset',
            name='department',
        ),
        migrations.RenameField(
            model_name='asset',
            old_name='location_new',
            new_name='location',
        ),
        migrations.RenameField(
            model_name='asset',
            old_name='department_new',
            new_name='department',
        ),
        migrations.AlterField(
            model_name='asset',
            name='location',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='assets', to='tickets.location'),
        ),
        migrations.AlterField(
            model_name='asset',
            name='department',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='assets', to='tickets.assetdepartment'),
        ),
    ]
