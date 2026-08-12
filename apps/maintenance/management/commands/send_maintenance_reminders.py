# apps/maintenance/management/commands/send_maintenance_reminders.py
"""Single-pass command, meant to run on a schedule (e.g. every few minutes
via the same scheduler that drives run_sla_scheduler/process_sla), that
sends 24-hour, 1-hour, and 10-minute due-date reminders for maintenance
schedules that haven't started yet."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.common.models import Notification
from apps.maintenance.models import MaintenanceSchedule

REMINDER_THRESHOLDS = [
    ('reminder_24h_sent', timedelta(hours=24), '24 hours'),
    ('reminder_1h_sent', timedelta(hours=1), '1 hour'),
    ('reminder_10m_sent', timedelta(minutes=10), '10 minutes'),
]


class Command(BaseCommand):
    help = 'Send 24h/1h/10m due-date reminders for upcoming maintenance schedules.'

    def handle(self, *args, **options):
        now = timezone.now()
        upcoming = MaintenanceSchedule.objects.exclude(
            status__in=[MaintenanceSchedule.Status.COMPLETED, MaintenanceSchedule.Status.CANCELLED]
        )

        sent_count = 0
        for schedule in upcoming:
            due = schedule.due_datetime()
            if due < now:
                continue

            recipients = list(schedule.additional_assignees.all())
            if schedule.assigned_to:
                recipients.append(schedule.assigned_to)
            if not recipients:
                continue

            for field_name, threshold, label in REMINDER_THRESHOLDS:
                if getattr(schedule, field_name):
                    continue
                if due - now > threshold:
                    continue

                for recipient in {r.pk: r for r in recipients}.values():
                    Notification.objects.create(
                        recipient=recipient,
                        message=f'⏰ Maintenance "{schedule.title}" is due in {label} ({due.strftime("%b %d, %H:%M")}).',
                        url=f'/maintenance/{schedule.pk}/',
                        type=Notification.Type.GENERAL,
                    )
                setattr(schedule, field_name, True)
                schedule.save(update_fields=[field_name])
                sent_count += 1

        if sent_count:
            self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} maintenance reminder(s).'))
        else:
            self.stdout.write('No maintenance reminders due.')
