from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tickets', '0060_asset_tag_slot_number'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssetImportBatch',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('uploaded_file', models.FileField(upload_to='asset_imports/%Y/%m/%d/')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('normalized_data', models.JSONField(blank=True, default=list)),
                ('status', models.CharField(choices=[('PENDING_REVIEW', 'Pending Review'), ('COMMITTED', 'Committed'), ('DISCARDED', 'Discarded')], default='PENDING_REVIEW', max_length=20)),
                ('committed_at', models.DateTimeField(blank=True, null=True)),
                ('row_count', models.PositiveIntegerField(default=0)),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-uploaded_at'],
            },
        ),
    ]
