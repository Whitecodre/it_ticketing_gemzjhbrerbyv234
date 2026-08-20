# apps/maintenance/management/commands/send_maintenance_reminders.py
"""Single-pass command, meant to run on a schedule (e.g. every few minutes
via the same scheduler that drives run_sla_scheduler/process_sla), that
sends 24-hour, 1-hour, and 10-minute due-date reminders for maintenance
schedules that haven't started yet, and auto-starts schedules whose
scheduled date/time has arrived."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.utils import role_of
from apps.maintenance.models import MaintenanceSchedule, MaintenanceActivityLog, MaintenanceAssetConfirmation
from apps.maintenance.views import (
    log_activity, notify_maintenance_assignees, notify_maintenance_management,
    notify_asset_confirmers, send_asset_owner_reminder_email, _asset_confirmation_recipients,
    _asset_review_url,
)

CONFIRMATION_OVERDUE_THRESHOLD = timedelta(hours=24)

REMINDER_THRESHOLDS = [
    ('reminder_24h_sent', timedelta(hours=24), '24 hours'),
    ('reminder_1h_sent', timedelta(hours=1), '1 hour'),
    ('reminder_10m_sent', timedelta(minutes=10), '10 minutes'),
]


def auto_start_due_schedules():
    """Transition SCHEDULED schedules to IN_PROGRESS once their scheduled
    date/time has arrived — starting is automatic, unlike Complete/Cancel
    which stay manual actions."""
    now = timezone.now()
    started = 0
    for schedule in MaintenanceSchedule.objects.filter(status=MaintenanceSchedule.Status.SCHEDULED):
        if schedule.due_datetime() > now:
            continue

        schedule.status = MaintenanceSchedule.Status.IN_PROGRESS
        schedule.save(update_fields=['status', 'updated_at'])

        log_activity(
            schedule,
            MaintenanceActivityLog.Action.STATUS_CHANGED,
            actor=None,
            details={'from': 'SCHEDULED', 'to': 'IN_PROGRESS', 'comment': 'Auto-started (scheduled time reached).'},
        )
        notify_maintenance_assignees(schedule, f'▶️ Maintenance "{schedule.title}" started automatically (scheduled time reached).')
        notify_maintenance_management(schedule, f'▶️ "{schedule.title}" started automatically (scheduled time reached).', actor=None)
        started += 1
    return started


class Command(BaseCommand):
    help = 'Auto-start due maintenance schedules and send 24h/1h/10m due-date reminders for upcoming ones.'

    def handle(self, *args, **options):
        started = auto_start_due_schedules()
        if started:
            self.stdout.write(self.style.SUCCESS(f'Auto-started {started} maintenance schedule(s).'))

        now = timezone.now()
        upcoming = MaintenanceSchedule.objects.exclude(
            status__in=[MaintenanceSchedule.Status.COMPLETED, MaintenanceSchedule.Status.CANCELLED]
        )

        sent_count = 0
        for schedule in upcoming:
            due = schedule.due_datetime()
            if due < now:
                continue

            assignee_recipients = list(schedule.additional_assignees.all())
            if schedule.assigned_to:
                assignee_recipients.append(schedule.assigned_to)
            target_assets = list(schedule.target_assets.all())

            for field_name, threshold, label in REMINDER_THRESHOLDS:
                if getattr(schedule, field_name):
                    continue
                if due - now > threshold:
                    continue

                for recipient in {r.pk: r for r in assignee_recipients}.values():
                    Notification.objects.create(
                        recipient=recipient,
                        role=role_of(recipient),
                        message=f'⏰ Maintenance "{schedule.title}" is due in {label} ({due.strftime("%b %d, %H:%M")}).',
                        url=f'/maintenance/{schedule.pk}/',
                        type=Notification.Type.GENERAL,
                    )

                # Asset owner (or department Team Lead / Admin fallback)
                # pre-maintenance heads-up — same cadence/thresholds as the
                # technician reminder above, in-app + email.
                for asset in target_assets:
                    if asset.assigned_to_id:
                        owner_recipients = [asset.assigned_to]
                    else:
                        owner_recipients = list(User.objects.filter(
                            role=User.Role.TEAM_LEAD, department=asset.department, is_active=True,
                        ))
                    for recipient in {r.pk: r for r in owner_recipients}.values():
                        Notification.objects.create(
                            recipient=recipient,
                            role=role_of(recipient),
                            message=f'⏰ Maintenance "{schedule.title}" affecting your asset {asset.name} ({asset.tracking_id}) is due in {label}.',
                            url=_asset_review_url(asset, schedule, recipient),
                            type=Notification.Type.GENERAL,
                        )
                        send_asset_owner_reminder_email(schedule, asset, recipient, label)

                setattr(schedule, field_name, True)
                schedule.save(update_fields=[field_name])
                sent_count += 1

        # Post-completion: nudge asset owners who haven't confirmed/disputed
        # within CONFIRMATION_OVERDUE_THRESHOLD of the technician marking
        # the work complete. Single fixed threshold, idempotent per row.
        overdue_confirmations = MaintenanceAssetConfirmation.objects.filter(
            status=MaintenanceAssetConfirmation.Status.PENDING,
            confirmation_reminder_sent=False,
            technician_completed_at__lte=now - CONFIRMATION_OVERDUE_THRESHOLD,
        ).select_related('schedule', 'asset')

        overdue_count = 0
        for row in overdue_confirmations:
            notify_asset_confirmers(
                row.asset, row.schedule,
                f'⏰ Still awaiting your confirmation for "{row.schedule.title}" on {row.asset.name} ({row.asset.tracking_id}).',
            )
            for recipient in _asset_confirmation_recipients(row.asset):
                send_asset_owner_reminder_email(row.schedule, row.asset, recipient, 'overdue confirmation')
            row.confirmation_reminder_sent = True
            row.save(update_fields=['confirmation_reminder_sent'])
            overdue_count += 1

        if overdue_count:
            self.stdout.write(self.style.SUCCESS(f'Sent {overdue_count} overdue-confirmation reminder(s).'))

        if sent_count:
            self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} maintenance reminder(s).'))
        else:
            self.stdout.write('No maintenance reminders due.')
