from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_clientsettings_asset_tag_prefix'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientsettings',
            name='company_initials',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
    ]
