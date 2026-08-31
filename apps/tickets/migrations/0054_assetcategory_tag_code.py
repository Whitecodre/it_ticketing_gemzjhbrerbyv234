from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0053_mobilizationitem_return_requested_at_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='assetcategory',
            name='tag_code',
            field=models.CharField(blank=True, max_length=10),
        ),
    ]
