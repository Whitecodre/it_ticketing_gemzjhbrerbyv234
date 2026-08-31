from django.db import migrations, models


def migrate_dead_statuses_forward(apps, schema_editor):
    """Rewrite existing rows using status values that are about to be
    dropped from Asset.Status, before the AlterField below shrinks the
    choices — REQUESTED/APPROVED/ORDERED/RECEIVED/RETURNED were never
    produced by any code path (procurement now runs through the separate
    AssetProcurementRequest model), and CHECKED_OUT is merged into IN_USE.
    A name literally flagged "(Scrapped)" is honored as SCRAPPED rather
    than defaulted to IN_STORE like the other stray REQUESTED rows."""
    Asset = apps.get_model('tickets', 'Asset')

    Asset.objects.filter(status='CHECKED_OUT').update(status='IN_USE')

    scrapped_named = Asset.objects.filter(status='REQUESTED', name__icontains='(Scrapped)')
    scrapped_named.update(status='SCRAPPED')
    Asset.objects.filter(status='REQUESTED').update(status='IN_STORE')

    Asset.objects.filter(status__in=['APPROVED', 'ORDERED', 'RECEIVED', 'RETURNED']).update(status='IN_STORE')


def migrate_dead_statuses_backward(apps, schema_editor):
    # No reverse mapping — the original values are gone by design. Leaving
    # rows at their migrated-forward value on a reverse migration.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tickets', '0066_alter_asset_renewal_currency_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_dead_statuses_forward, migrate_dead_statuses_backward),
        migrations.AlterField(
            model_name='asset',
            name='status',
            field=models.CharField(choices=[
                ('IN_STORE', 'In Store'), ('READY', 'Ready for Deployment'),
                ('IN_USE', 'In Use'), ('MOBILIZED', 'Mobilized'),
                ('MAINTENANCE', 'Maintenance'), ('REPAIR', 'Repair'), ('DAMAGED', 'Damaged'),
                ('RETIRED', 'Retired'), ('SCRAPPED', 'Scrapped'), ('LOST', 'Lost'),
                ('STOLEN', 'Stolen'), ('DISPOSED', 'Disposed'),
            ], default='IN_STORE', max_length=20),
        ),
    ]
