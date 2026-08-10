from django.db import migrations


def backfill_department_access(apps, schema_editor):
    DisplayDocument = apps.get_model('documents_display', 'DisplayDocument')
    DocumentDepartmentAccess = apps.get_model('documents_display', 'DocumentDepartmentAccess')

    for doc in DisplayDocument.objects.all():
        if doc.visibility == 'PUBLIC':
            # public_can_download already defaults to True from migration 0005 —
            # nothing to backfill, preserves the old "view implies download" behavior.
            continue

        if doc.visibility == 'DEPARTMENT':
            department = doc.created_by.department if doc.created_by_id else None
            if department:
                DocumentDepartmentAccess.objects.get_or_create(
                    document=doc,
                    department=department,
                    defaults={'can_download': True, 'can_edit': False},
                )
            doc.visibility = 'RESTRICTED'
            doc.save(update_fields=['visibility'])
            continue

        if doc.visibility == 'RESTRICTED':
            for code in (doc.allowed_departments or []):
                DocumentDepartmentAccess.objects.get_or_create(
                    document=doc,
                    department=code,
                    defaults={'can_download': True, 'can_edit': False},
                )


class Migration(migrations.Migration):

    dependencies = [
        ('documents_display', '0005_remove_displaydocument_allowed_departments_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_department_access, migrations.RunPython.noop),
    ]
