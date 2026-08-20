# apps/tickets/management/commands/send_renewal_reminders.py
"""Single-pass command, meant to run on the same schedule as
run_sla_scheduler/process_sla, that sends 90/30/7-day reminders for
renewable assets (software licenses, subscriptions, support contracts)
approaching their next_renewal_date. Notifies Admin/Superadmin — an
org-wide financial/audit concern, same audience as the low-stock alert."""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.utils import role_of
from apps.tickets.models import Asset

# Checked smallest to largest window. If an asset is already within a
# closer window the first time it's evaluated (e.g. created with only 5
# days left), only the closest crossed threshold actually sends a
# notification — farther-out thresholds that are also already past are
# marked sent without notifying, so the admin isn't hit with 3 redundant
# notifications in one run.
REMINDER_THRESHOLDS = [
    (7, 'renewal_reminder_7d_sent', '7 days'),
    (30, 'renewal_reminder_30d_sent', '30 days'),
    (90, 'renewal_reminder_90d_sent', '90 days'),
]


class Command(BaseCommand):
    help = 'Send 90/30/7-day renewal reminders for renewable assets approaching their next_renewal_date.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        upcoming = Asset.objects.filter(category__is_renewable=True, next_renewal_date__isnull=False)

        recipients = list(User.objects.filter(role__in=[User.Role.ADMIN, User.Role.SUPERADMIN], is_active=True))

        sent_count = 0
        for asset in upcoming:
            days_remaining = (asset.next_renewal_date - today).days

            already_notified_this_run = False
            for threshold_days, field_name, label in REMINDER_THRESHOLDS:
                if getattr(asset, field_name):
                    continue
                if days_remaining > threshold_days:
                    continue

                if not already_notified_this_run and recipients:
                    for recipient in recipients:
                        Notification.objects.create(
                            recipient=recipient,
                            role=role_of(recipient),
                            message=(
                                f'📅 "{asset.name}" renews in {label} ({asset.next_renewal_date}) — '
                                f'{asset.renewal_cost if asset.renewal_cost is not None else "cost not set"}.'
                            ),
                            url=f'/tickets/assets/{asset.pk}/detail/',
                            type=Notification.Type.GENERAL,
                        )
                    sent_count += 1
                    already_notified_this_run = True

                setattr(asset, field_name, True)
                asset.save(update_fields=[field_name])

        if sent_count:
            self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} renewal reminder(s).'))
        else:
            self.stdout.write('No renewal reminders due.')
