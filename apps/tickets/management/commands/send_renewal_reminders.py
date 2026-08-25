# apps/tickets/management/commands/send_renewal_reminders.py
"""Single-pass command, meant to run on the same schedule as
run_sla_scheduler/process_sla, that sends 90/30/7-day reminders for
renewable assets (software licenses, subscriptions, support contracts)
approaching their next_renewal_date. Notifies Admin/Superadmin — an
org-wide financial/audit concern, same audience as the low-stock alert."""
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.common.models import Notification
from apps.common.utils import role_of, notify_recipients_by_email
from apps.common.permissions import effective_role_name
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

# Once a renewal is actually overdue, the 90/30/7-day flags above have all
# already fired once and stay True — nothing further would ever nag again.
# This re-notifies every OVERDUE_REPEAT_DAYS until the renewal is actioned
# (mark_renewed() clears renewal_reminder_overdue_last_sent).
OVERDUE_REPEAT_DAYS = 7


class Command(BaseCommand):
    help = 'Send 90/30/7-day renewal reminders for renewable assets approaching their next_renewal_date.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        upcoming = Asset.objects.filter(category__is_renewable=True, next_renewal_date__isnull=False)

        # Narrow via the legacy field or the roles M2M (either can lag
        # right after account creation), then resolve each candidate's
        # true active role in Python — a raw role__in=[...] filter misses/
        # wrongly-includes admins whose active role has diverged from the
        # legacy field.
        candidates = User.objects.filter(
            Q(role__in=['ADMIN', 'SUPERADMIN']) | Q(roles__name__in=['ADMIN', 'SUPERADMIN']),
            is_active=True,
        ).distinct()
        recipients = [u for u in candidates if effective_role_name(u) in ('ADMIN', 'SUPERADMIN')]

        sent_count = 0
        for asset in upcoming:
            days_remaining = (asset.next_renewal_date - today).days
            url = f'/tickets/assets/{asset.pk}/detail/'
            cost_display = asset.renewal_cost if asset.renewal_cost is not None else "cost not set"

            already_notified_this_run = False
            for threshold_days, field_name, label in REMINDER_THRESHOLDS:
                if getattr(asset, field_name):
                    continue
                if days_remaining > threshold_days:
                    continue

                if not already_notified_this_run and recipients:
                    message = f'📅 "{asset.name}" renews in {label} ({asset.next_renewal_date}) — {cost_display}.'
                    for recipient in recipients:
                        Notification.objects.create(
                            recipient=recipient,
                            role=role_of(recipient),
                            message=message,
                            url=url,
                            type=Notification.Type.GENERAL,
                        )
                    notify_recipients_by_email(recipients, f'Renewal due soon: {asset.name}', message, url)
                    sent_count += 1
                    already_notified_this_run = True

                setattr(asset, field_name, True)
                asset.save(update_fields=[field_name])

            # Overdue: the renewal date has already passed. Re-notify every
            # OVERDUE_REPEAT_DAYS rather than the one-shot flags above, so a
            # missed renewal keeps surfacing instead of going quiet once
            # the last threshold has fired.
            if days_remaining < 0 and not already_notified_this_run and recipients:
                last_sent = asset.renewal_reminder_overdue_last_sent
                due_for_repeat = last_sent is None or (today - last_sent).days >= OVERDUE_REPEAT_DAYS
                if due_for_repeat:
                    message = (
                        f'⚠️ "{asset.name}" renewal is {abs(days_remaining)} day(s) overdue '
                        f'(was due {asset.next_renewal_date}) — {cost_display}.'
                    )
                    for recipient in recipients:
                        Notification.objects.create(
                            recipient=recipient,
                            role=role_of(recipient),
                            message=message,
                            url=url,
                            type=Notification.Type.GENERAL,
                        )
                    notify_recipients_by_email(recipients, f'Renewal overdue: {asset.name}', message, url)
                    sent_count += 1
                    asset.renewal_reminder_overdue_last_sent = today
                    asset.save(update_fields=['renewal_reminder_overdue_last_sent'])

        if sent_count:
            self.stdout.write(self.style.SUCCESS(f'Sent {sent_count} renewal reminder(s).'))
        else:
            self.stdout.write('No renewal reminders due.')
