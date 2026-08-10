# Schema cleanup, safe to run only after 0006's backfill has been applied and
# spot-checked. In a production rollout, deploy 0005+0006 first, verify, then
# apply this migration in a follow-up deploy.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documents_display', '0006_backfill_department_access'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='displaydocument',
            name='allowed_departments',
        ),
        migrations.AlterField(
            model_name='displaydocument',
            name='visibility',
            field=models.CharField(choices=[('PUBLIC', 'Public (All Users)'), ('RESTRICTED', 'Restricted (Specific Departments)')], default='PUBLIC', max_length=20),
        ),
    ]
