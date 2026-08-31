from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0059_asset_location_department_cutover'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='tag_slot_number',
            field=models.PositiveIntegerField(blank=True, editable=False, null=True),
        ),
    ]
