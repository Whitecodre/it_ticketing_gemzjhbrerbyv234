# apps/common/migrations/0008_drop_form_builder_tables.py
#
# The form_builder app has been removed from INSTALLED_APPS and deleted
# from the codebase (deprecated formio.js-based dynamic form builder,
# superseded by the fixed ticket forms). Since the app is no longer
# registered, Django can't generate a normal delete-model migration for
# it — this drops its three tables directly via raw SQL instead. Living
# in apps.common (which stays installed) rather than a form_builder
# migration that no longer has an app to belong to.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0007_category_icon'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                'DROP TABLE IF EXISTS form_builder_formsubmission CASCADE;',
                'DROP TABLE IF EXISTS form_builder_formtemplate CASCADE;',
                'DROP TABLE IF EXISTS form_builder_formdefinition CASCADE;',
                # Clear the app's migration history too, so it doesn't
                # linger as a ghost app in `showmigrations`.
                "DELETE FROM django_migrations WHERE app = 'form_builder';",
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
