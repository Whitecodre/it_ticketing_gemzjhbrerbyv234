import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0054_assetcategory_tag_code'),
    ]

    operations = [
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(blank=True, unique=True)),
                ('tag_code', models.CharField(blank=True, max_length=10)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='tickets.location')),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='AssetDepartment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('tag_code', models.CharField(blank=True, max_length=10)),
                ('is_active', models.BooleanField(default=True)),
                ('legacy_user_department_code', models.CharField(blank=True, choices=[
                    ('MARINE', 'Marine'), ('IT', 'IT'), ('ACCOUNTING', 'Accounting'), ('LEGAL', 'Legal'),
                    ('QHSE', 'QHSE'), ('OPERATIONS', 'Operations'), ('PROJECT', 'Project'),
                    ('VESSEL_CATERING', 'Vessel Catering'), ('PURCHASE_PROTOCOL', 'Purchase/Protocol'),
                    ('FREIGHT', 'Freight'), ('STORE', 'Store'), ('HR', 'HR'), ('ADMIN', 'Admin'),
                    ('COMMERCIAL', 'Commercial'),
                ], max_length=30)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
    ]
