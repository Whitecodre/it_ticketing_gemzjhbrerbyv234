from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0036_asset_department'),
    ]

    operations = [
        migrations.RenameModel(old_name='DiveSpread', new_name='DiveSystem'),
        migrations.RenameField(model_name='ticket', old_name='dive_spreads', new_name='dive_systems'),
        migrations.RenameField(model_name='mobilization', old_name='dive_spreads', new_name='dive_systems'),
    ]
