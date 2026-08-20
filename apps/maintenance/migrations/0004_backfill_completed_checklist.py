from django.db import migrations


def mark_completed_schedules_checklist_done(apps, schema_editor):
    """Existing COMPLETED schedules never had completed_checklist populated
    (there was no per-item toggle UI) — backfill them to 100% so the
    Maintenance report doesn't show a finished job stuck at 0%."""
    MaintenanceSchedule = apps.get_model('maintenance', 'MaintenanceSchedule')
    for schedule in MaintenanceSchedule.objects.filter(status='COMPLETED'):
        if schedule.checklist_items and not schedule.completed_checklist:
            schedule.completed_checklist = list(schedule.checklist_items)
            schedule.save(update_fields=['completed_checklist'])


class Migration(migrations.Migration):

    dependencies = [
        ('maintenance', '0003_maintenanceschedule_facility_location_and_more'),
    ]

    operations = [
        migrations.RunPython(mark_completed_schedules_checklist_done, migrations.RunPython.noop),
    ]
