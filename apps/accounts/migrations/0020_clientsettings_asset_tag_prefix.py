from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0019_clientsettings_currency_symbol'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientsettings',
            name='asset_tag_prefix',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
    ]
