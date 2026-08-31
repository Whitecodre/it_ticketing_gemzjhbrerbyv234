from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tickets', '0061_assetimportbatch'),
        ('maintenance', '0009_vendor_proposed_by'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssetBackupStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('NOT_BACKED_UP', 'Not Backed Up'), ('IN_PROGRESS', 'Backup In Progress'), ('BACKED_UP', 'Backed Up'), ('FAILED', 'Backup Failed')], default='NOT_BACKED_UP', max_length=20)),
                ('method', models.CharField(blank=True, max_length=100)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('asset', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='backup_status', to='tickets.asset')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Asset Backup Status',
                'verbose_name_plural': 'Asset Backup Statuses',
            },
        ),
    ]
