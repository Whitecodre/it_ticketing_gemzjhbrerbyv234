from django.db import migrations


class Migration(migrations.Migration):
    """Removes the redundant assigned_to_department snapshot field —
    wherever the app needs to show which department the current holder is
    in, it now reads that live via assigned_to.department instead. See
    Asset.department's docstring for why this is separate from the asset's
    own owning department."""

    dependencies = [
        ('tickets', '0061_assetimportbatch'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='asset',
            name='assigned_to_department',
        ),
    ]
